"""Replay local chat prefixes and record a latency baseline.

Requests contain only role and text. Slot labels, evidence, and the expected
next assistant reply are never sent. autoservice_dataset/test.jsonl is never opened.

The model processes are reused. "Cold" is the first measured request in this
run, not a process restart. Warm requests follow it.

Example:
    .venv312/bin/python benchmark/run_baseline.py
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "autoservice_dataset" / "train.jsonl"
HOLDOUT = Path(__file__).resolve().parent / "dev_dialogue_ids.json"
RESULTS = Path(__file__).resolve().parent / "results" / "baseline.json"
CHAT_URL = "http://127.0.0.1:8766/api/chat"
HEALTH_URL = "http://127.0.0.1:8766/api/health"
EXTRACT_HEALTH_URL = "http://127.0.0.1:8767/health"
TIMEOUT_SECONDS = 1800.0

COLD_TEXT = (
    "Добрый день. Hyundai Solaris 2016, бензин, Екатеринбург. "
    "При торможении слышен скрежет спереди. Подскажите, пожалуйста, что с этим делать."
)

CASES = (
    {
        "case_id": "city_correction",
        "dialogue_id": "train_000402",
        "end_message_id": "m7",
        "latest_city": "Великий Новгород",
        "stale_city": "Псков",
    },
    {
        "case_id": "known_vehicle_and_city",
        "dialogue_id": "train_000015",
        "end_message_id": "m5",
        "vehicle_marker": "тигуан",
        "city_marker": "казан",
    },
    {
        "case_id": "price_or_booking_without_data",
        "dialogue_id": "train_000178",
        "end_message_id": "m1",
    },
)

PRICE_RE = re.compile(r"(?:₽|\bруб(?:\.|л(?:ей|я|ь)?)?\b|\b\d{2,}\s*(?:тыс|тысяч))", re.IGNORECASE)
BOOKING_RE = re.compile(r"записал(?:и|а)? вас|запись подтверж|вы записаны|время подтверж", re.IGNORECASE)
CITY_ASK_RE = re.compile(r"в каком городе|какой город|какое место верное|где искать", re.IGNORECASE)
VEHICLE_ASK_RE = re.compile(r"какая машина|марку, модель|какая у вас машина", re.IGNORECASE)
FORMAT_ASK_RE = re.compile(r"нужен выезд.*или.*сервис|выезд к машине или подбор", re.IGNORECASE)
COOLANT_ASK_RE = re.compile(r"антифриз.*уходит|уходит.*антифриз", re.IGNORECASE)
GENERIC_CONTEXT_RE = re.compile(
    r"при торможении, на ходу, при повороте или на месте",
    re.IGNORECASE,
)
PRICE_LIMIT_RE = re.compile(r"стоимость|не называ|не подтвержда|время и стоимость", re.IGNORECASE)


def get_json(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} did not return an object")
    return payload


def load_prefix(dialogue_id: str, end_message_id: str) -> list[dict[str, str]]:
    if not TRAIN.is_file():
        raise SystemExit(f"missing {TRAIN}")
    with TRAIN.open(encoding="utf-8") as stream:
        for line in stream:
            dialogue = json.loads(line)
            if dialogue.get("dialogue_id") != dialogue_id:
                continue
            messages: list[dict[str, str]] = []
            found = False
            for turn in dialogue["turns"]:
                role = turn.get("role")
                text = turn.get("text")
                if role not in {"user", "assistant"} or not isinstance(text, str):
                    raise SystemExit(f"{dialogue_id} has a turn without role and text")
                messages.append({"role": role, "text": text})
                if turn.get("message_id") == end_message_id:
                    found = True
                    break
            if not found:
                raise SystemExit(f"{dialogue_id} has no message {end_message_id}")
            if messages[-1]["role"] != "user":
                raise SystemExit(f"{dialogue_id} {end_message_id} is not a user turn")
            return messages
    raise SystemExit(f"{dialogue_id} was not found in train.jsonl")


def require_holdout(dialogue_ids: list[str]) -> None:
    if not HOLDOUT.is_file():
        raise SystemExit("missing benchmark/dev_dialogue_ids.json; run select_dev_dialogues.py")
    payload = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    reserved = set(payload.get("dialogue_ids") or [])
    missing = [dialogue_id for dialogue_id in dialogue_ids if dialogue_id not in reserved]
    if missing:
        raise SystemExit("benchmark dialogues are not in the retrieval holdout: " + ", ".join(missing))


def cyrillic_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    cyrillic = sum(1 for char in letters if "а" <= char.casefold() <= "я" or char.casefold() == "ё")
    return cyrillic / len(letters)


def question_count(text: str) -> int:
    return text.count("?") + text.count("？")


def judge(case: dict, reply: str, slots: dict) -> list[str]:
    failures: list[str] = []
    if not reply.strip():
        failures.append("empty_reply")
        return failures
    if cyrillic_ratio(reply) < 0.8:
        failures.append("reply_is_not_natural_russian")
    if question_count(reply) > 1:
        failures.append("more_than_one_question")
    if PRICE_RE.search(reply):
        failures.append("invented_price")
    if BOOKING_RE.search(reply):
        failures.append("invented_booking")

    case_id = case["case_id"]
    folded = reply.casefold()
    if case_id == "city_correction":
        latest = case["latest_city"].casefold()
        stale = case["stale_city"].casefold()
        slot_city = str(slots.get("search_area", "")).casefold()
        if latest not in slot_city:
            failures.append("extraction_missed_latest_city")
        if stale in slot_city and latest not in slot_city:
            failures.append("extraction_kept_stale_city")
        if CITY_ASK_RE.search(reply):
            failures.append("asked_city_after_correction")
        if stale in folded and latest not in folded:
            failures.append("reply_kept_stale_city")
        if latest not in folded and "новгород" not in folded:
            failures.append("reply_ignored_latest_city")
        symptom = str(slots.get("main_symptom", "")).casefold()
        timing_known = "постоянно" in symptom or "холодн" in symptom
        if GENERIC_CONTEXT_RE.search(reply) and timing_known:
            failures.append("asked_generic_context_after_timing_was_known")
        if ";" in symptom:
            failures.append("symptom_joined_with_semicolon")
    elif case_id == "known_vehicle_and_city":
        vehicle = str(slots.get("vehicle", "")).casefold()
        city = str(slots.get("search_area", "")).casefold()
        if case["vehicle_marker"] not in vehicle and "tiguan" not in vehicle:
            failures.append("extraction_lost_vehicle")
        if case["city_marker"] not in city:
            failures.append("extraction_lost_city")
        if VEHICLE_ASK_RE.search(reply):
            failures.append("reasked_vehicle")
        if CITY_ASK_RE.search(reply):
            failures.append("reasked_city")
        if FORMAT_ASK_RE.search(reply):
            failures.append("reasked_answered_format")
        if COOLANT_ASK_RE.search(reply):
            failures.append("ignored_coolant_fact")
        if case["city_marker"] not in folded:
            failures.append("reply_omitted_known_city")
        if str(slots.get("location_format", "")) == "workshop" and "сервис" not in folded:
            failures.append("reply_omitted_workshop_choice")
        if "печк" not in folded and "холодн" not in folded:
            failures.append("reply_omitted_known_symptom")
        if "догад" in folded:
            failures.append("framed_latest_turn_as_unconfirmed_guess")
    elif case_id == "price_or_booking_without_data":
        asks_needed = bool(VEHICLE_ASK_RE.search(reply) or CITY_ASK_RE.search(reply) or "какую именно работу" in folded)
        if not asks_needed:
            failures.append("did_not_ask_for_missing_vehicle_or_city")
        if not PRICE_LIMIT_RE.search(reply):
            failures.append("ignored_price_and_booking_question")
    return failures


def post_chat(messages: list[dict[str, str]]) -> dict:
    payload = {
        "request_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "messages": messages,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        CHAT_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "http_status": exc.code,
            "wall_ms": round(elapsed_ms, 1),
            "error": "http_error",
            "detail": detail[:500],
            "request_messages": messages,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "wall_ms": round(elapsed_ms, 1),
            "error": type(exc).__name__,
            "detail": str(exc),
            "request_messages": messages,
        }
    elapsed_ms = (time.perf_counter() - started) * 1000
    data = json.loads(raw.decode("utf-8"))
    message = data.get("message") if isinstance(data, dict) else None
    text = message.get("text") if isinstance(message, dict) else ""
    structured = data.get("structured") if isinstance(data, dict) else None
    slots = {}
    if isinstance(structured, dict) and isinstance(structured.get("slots_after_message"), dict):
        slots = structured["slots_after_message"]
    metrics = data.get("metrics") if isinstance(data, dict) else {}
    extraction_ms = metrics.get("elapsed_ms") if isinstance(metrics, dict) else None
    overhead_ms = None
    if isinstance(extraction_ms, int):
        overhead_ms = round(elapsed_ms - extraction_ms, 1)
    return {
        "ok": status == 200 and isinstance(text, str) and text.strip() != "",
        "http_status": status,
        "wall_ms": round(elapsed_ms, 1),
        "extraction_ms": extraction_ms,
        "policy_and_http_overhead_ms": overhead_ms,
        "model": data.get("model") if isinstance(data, dict) else None,
        "reply": text if isinstance(text, str) else "",
        "slots": slots,
        "metrics": metrics,
        "request_id": data.get("request_id") if isinstance(data, dict) else None,
        "request_messages": messages,
        "error": None if status == 200 else "bad_status",
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def summarize(runs: list[dict]) -> dict:
    walls = [run["wall_ms"] for run in runs if run.get("ok") and isinstance(run.get("wall_ms"), (int, float))]
    extract = [run["extraction_ms"] for run in runs if isinstance(run.get("extraction_ms"), (int, float))]
    overhead = [
        run["policy_and_http_overhead_ms"]
        for run in runs
        if isinstance(run.get("policy_and_http_overhead_ms"), (int, float))
    ]
    return {
        "sample_size": len(runs),
        "completed": len(walls),
        "errors": sum(1 for run in runs if not run.get("ok")),
        "timeouts": sum(1 for run in runs if run.get("error") in {"TimeoutError", "timeout"}),
        "wall_ms": {
            "median": None if not walls else round(statistics.median(walls), 1),
            "p95": None if not walls else round(percentile(walls, 0.95), 1),
            "min": None if not walls else round(min(walls), 1),
            "max": None if not walls else round(max(walls), 1),
        },
        "extraction_ms": {
            "median": None if not extract else round(statistics.median(extract), 1),
            "p95": None if not extract else round(percentile(extract, 0.95), 1),
        },
        "policy_and_http_overhead_ms": {
            "median": None if not overhead else round(statistics.median(overhead), 1),
        },
        "retrieval_ms": None,
        "retrieval_note": "No dialogue retrieval stage exists. Catalog shortlist inside Mica is not timed separately.",
        "generation_note": (
            "Customer text is produced by the local dialogue policy after extraction. "
            "The server does not time that step alone. policy_and_http_overhead_ms is wall time minus metrics.elapsed_ms."
        ),
        "mica_vs_qwen_note": "The live extract response does not split Mica classification from Qwen generation.",
    }


def run_case(case: dict, repeat_index: int) -> dict:
    messages = load_prefix(case["dialogue_id"], case["end_message_id"])
    result = post_chat(messages)
    result["case_id"] = case["case_id"]
    result["dialogue_id"] = case["dialogue_id"]
    result["end_message_id"] = case["end_message_id"]
    result["repeat_index"] = repeat_index
    result["failures"] = judge(case, result.get("reply") or "", result.get("slots") or {})
    if not result.get("ok") and result.get("error"):
        result["failures"] = list(result["failures"]) + [f"request_{result['error']}"]
    return result


def judge_cold(reply: str, slots: dict) -> list[str]:
    failures: list[str] = []
    if cyrillic_ratio(reply) < 0.8:
        failures.append("reply_is_not_natural_russian")
    city = str(slots.get("search_area", "")).strip()
    if city and city.casefold() not in reply.casefold():
        failures.append("reply_omitted_known_city")
    return failures


def load_cold_file(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    message = response.get("message") if isinstance(response, dict) else {}
    text = message.get("text") if isinstance(message, dict) else ""
    structured = response.get("structured") if isinstance(response, dict) else {}
    slots = structured.get("slots_after_message") if isinstance(structured, dict) else {}
    metrics = response.get("metrics") if isinstance(response, dict) else {}
    wall_ms = payload.get("elapsed_s")
    if isinstance(wall_ms, (int, float)):
        wall_ms = round(wall_ms * 1000, 1)
    extraction_ms = metrics.get("elapsed_ms") if isinstance(metrics, dict) else None
    overhead_ms = None
    if isinstance(wall_ms, (int, float)) and isinstance(extraction_ms, int):
        overhead_ms = round(wall_ms - extraction_ms, 1)
    messages = []
    request = payload.get("request")
    if isinstance(request, dict) and isinstance(request.get("messages"), list):
        messages = request["messages"]
    return {
        "ok": bool(payload.get("ok")),
        "http_status": payload.get("http_status"),
        "wall_ms": wall_ms,
        "extraction_ms": extraction_ms,
        "policy_and_http_overhead_ms": overhead_ms,
        "model": response.get("model") if isinstance(response, dict) else None,
        "reply": text if isinstance(text, str) else "",
        "slots": slots if isinstance(slots, dict) else {},
        "metrics": metrics,
        "request_messages": messages,
        "case_id": "cold_single_turn",
        "failures": judge_cold(text if isinstance(text, str) else "", slots if isinstance(slots, dict) else {}),
        "source_file": str(path),
    }


def rescore(path: Path) -> None:
    report = json.loads(path.read_text(encoding="utf-8"))
    cold = report.get("cold")
    if isinstance(cold, dict):
        cold["failures"] = judge_cold(cold.get("reply") or "", cold.get("slots") or {})
    cases = {case["case_id"]: case for case in CASES}
    for run in report.get("warm_runs") or []:
        case = cases[run["case_id"]]
        run["failures"] = judge(case, run.get("reply") or "", run.get("slots") or {})
    report["meaning_check"] = "reapplied locally to the saved live replies; the model was not called again"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"rescored {path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local automotive chat baseline")
    parser.add_argument("--skip-cold", action="store_true", help="Do not send the first single-turn request")
    parser.add_argument(
        "--cold-file",
        type=Path,
        help="Attach an already measured cold request instead of sending another one",
    )
    parser.add_argument("--warm-repeats", type=int, default=2, help="How many times to run the three warm cases")
    parser.add_argument("--output", type=Path, default=RESULTS)
    parser.add_argument(
        "--rescore",
        action="store_true",
        help="Reapply meaning checks to a saved baseline without calling the model",
    )
    args = parser.parse_args()
    if args.warm_repeats < 1:
        raise SystemExit("--warm-repeats must be at least 1")
    if args.rescore:
        rescore(args.output)
        return

    health = get_json(HEALTH_URL)
    extract_health = get_json(EXTRACT_HEALTH_URL)
    if health.get("provider") != "local" or health.get("model") != "Mica + Qwen local preview":
        raise SystemExit(f"chat endpoint is not the local model path: {health}")

    require_holdout([case["dialogue_id"] for case in CASES])
    cold = load_cold_file(args.cold_file) if args.cold_file else None
    if args.cold_file and not args.skip_cold:
        raise SystemExit("pass --skip-cold when attaching --cold-file")
    if not args.skip_cold:
        cold_result = post_chat([{"role": "user", "text": COLD_TEXT}])
        cold_result["case_id"] = "cold_single_turn"
        cold_result["failures"] = judge_cold(cold_result.get("reply") or "", cold_result.get("slots") or {})
        if not cold_result.get("ok"):
            cold_result["failures"].append(cold_result.get("error") or "cold_failed")
        cold = cold_result
        print(
            f"cold {cold_result.get('wall_ms')} ms model={cold_result.get('model')} "
            f"reply={cold_result.get('reply')}",
            flush=True,
        )

    warm_runs = []
    for repeat_index in range(args.warm_repeats):
        for case in CASES:
            result = run_case(case, repeat_index)
            warm_runs.append(result)
            print(
                f"warm {case['case_id']} repeat={repeat_index} "
                f"wall={result.get('wall_ms')} ms failures={result.get('failures')} "
                f"reply={result.get('reply')}",
                flush=True,
            )

    report = {
        "endpoint": CHAT_URL,
        "health": health,
        "extract_health": extract_health,
        "cold_definition": (
            "First measured request after the model processes were already resident. "
            "This is not a process-cold start and does not reload Mica or Qwen."
        ),
        "stages": {
            "extraction": "metrics.elapsed_ms on /api/chat, covering Mica and Qwen as one call",
            "retrieval": "absent",
            "response_generation": "local dialogue policy; estimated only as wall_ms minus extraction_ms",
        },
        "cold": cold,
        "warm_summary": summarize(warm_runs),
        "warm_runs": warm_runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
