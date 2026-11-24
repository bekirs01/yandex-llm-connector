"""Run the Wave 4A conversational evaluation against POST /api/chat.

The runner sends customer turns and the assistant replies actually returned
for this conversation. Grading notes stay in the case file and the local
review packet. They are not part of the request.

This module does not start a model and does not score reply quality by
exact wording.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "cases.json"
DEFAULT_OUTPUT = ROOT / "results" / "run.json"
SCHEMA = "wave4a-conversational-eval-1"
GRADING_CANARY = "GRADING_CANARY_DO_NOT_SEND"
DEFAULT_LABEL = "evaluation"
DEFAULT_TIMEOUT = 1800.0

REQUIRED_TAGS = frozenset({
    "casual_opening",
    "paraphrase",
    "colloquial",
    "typos",
    "vague",
    "greeting_with_question",
    "short_followup",
    "correction",
    "price_or_booking",
    "contrast_pair",
    "simple_conversation",
})
CASE_KEYS = frozenset({"id", "tags", "turns", "contrast_group", "contrast_anchor"})
TURN_KEYS = frozenset({
    "customer",
    "kind",
    "must_understand",
    "may_ask",
    "concrete_failures",
    "reviewer_judgments",
    "auto_facts",
})
AUTO_FACT_KEYS = frozenset({
    "expect_cyrillic",
    "price_amount_is_failure",
    "confirmed_booking_is_failure",
    "asserted_hours_is_failure",
})
KINDS = frozenset({"conversation", "automotive"})
FORBIDDEN_KEYS = frozenset({
    "expected",
    "expected_reply",
    "gold",
    "reference_answer",
    "quality_score",
})

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z",
    re.IGNORECASE,
)
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_CURRENCY_RE = re.compile(
    r"(?:\d[\d\s\u00a0]{0,12}\s*(?:₽|руб(?:\.|ля|лей|ль|лями)?)|"
    r"(?:₽|руб(?:\.|ля|лей|ль|лями)?)\s*\d|"
    r"(?:\$|€|£)\s*\d|\d\s*(?:\$|€|£))",
    re.IGNORECASE,
)
_PRICE_WORD_RE = re.compile(
    r"(?:стоит|обойд[её]тся|выйдет|цена)\s*"
    r"(?:примерно|около|где-то|где то|всего)?\s*[:—-]?\s*\d",
    re.IGNORECASE,
)
_BOOKING_RE = re.compile(
    r"(?:вы\s+записан[аы]|запись\s+подтвержден[аоы]|забронировал[аи]?|"
    r"бронь\s+оформлен[аоы]|я\s+вас\s+записал|слот\s+подтверж)",
    re.IGNORECASE,
)
_HOURS_RE = re.compile(
    r"(?:работаем\s+с\s+\d|открыт[ыа]?\s+(?:с|до)\s+\d|"
    r"график\s+работы\s*[:—-]\s*\d|"
    r"в\s+воскресенье\s+(?:мы\s+)?(?:закрыт|открыт))",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"(?<![\w])(?:не|нет)(?![\w])", re.IGNORECASE)

Post = Callable[[dict[str, Any], float], dict[str, Any]]


def load_dataset(path: Path = CASES_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    issues = validate_dataset(data)
    if issues:
        joined = "\n".join(issues)
        raise ValueError(f"Invalid evaluation dataset:\n{joined}")
    return data


def validate_dataset(data: Any) -> list[str]:
    """Return structural problems. Messages name ids and fields, not a score."""

    issues: list[str] = []
    if not isinstance(data, dict):
        return ["dataset must be an object"]
    if data.get("schema") != SCHEMA:
        issues.append("schema mismatch")
    if data.get("grading_canary") != GRADING_CANARY:
        issues.append("grading canary missing")
    scoring = data.get("scoring")
    if not isinstance(scoring, dict):
        issues.append("scoring must be an object")
    else:
        wording = scoring.get("wording")
        if not isinstance(wording, str) or "exact wording is not a score" not in wording.casefold():
            issues.append("scoring.wording must say exact wording is not a score")
        if not isinstance(wording, str) or "greeting is not required" not in wording.casefold():
            issues.append("scoring.wording must say a greeting is not required")
        for key in ("auto_facts", "reviewer"):
            if not isinstance(scoring.get(key), str) or not scoring[key].strip():
                issues.append(f"scoring.{key} must be text")
    auto_facts = data.get("auto_facts")
    if not isinstance(auto_facts, dict) or set(auto_facts) != AUTO_FACT_KEYS:
        issues.append("dataset auto_facts keys are incomplete")
    elif any(auto_facts[key] is not True for key in AUTO_FACT_KEYS):
        issues.append("dataset auto_facts must require the shared factual screens")
    if not isinstance(data.get("business_data"), str) or not data["business_data"].strip():
        issues.append("business_data must be text")
    cases = data.get("cases")
    if not isinstance(cases, list):
        return issues + ["cases must be a list"]
    if len(cases) != 24:
        issues.append(f"expected 24 cases, found {len(cases)}")

    seen_ids: set[str] = set()
    sequences: list[tuple[str, ...]] = []
    tags_seen: set[str] = set()
    groups: dict[str, list[str]] = {}
    anchors: dict[str, str] = {}
    kind_counts = {"conversation": 0, "automotive": 0}
    extra_keys = _forbidden_keys(data)
    if extra_keys:
        issues.append("forbidden grading keys present: " + ", ".join(sorted(extra_keys)))

    for case in cases:
        if not isinstance(case, dict):
            issues.append("case must be an object")
            continue
        case_id = case.get("id")
        label = case_id if isinstance(case_id, str) else "<unnamed>"
        unknown = set(case) - CASE_KEYS
        if unknown:
            issues.append(f"{label}: unknown case fields")
        if not isinstance(case_id, str) or not re.fullmatch(r"w4a-\d{2}", case_id):
            issues.append(f"{label}: id must look like w4a-01")
        elif case_id in seen_ids:
            issues.append(f"{label}: duplicate id")
        else:
            seen_ids.add(case_id)
        case_tags = case.get("tags")
        if not isinstance(case_tags, list) or not case_tags or not all(isinstance(tag, str) for tag in case_tags):
            issues.append(f"{label}: tags must be a nonempty string list")
        else:
            tags_seen.update(case_tags)
        turns = case.get("turns")
        if not isinstance(turns, list) or len(turns) < 2:
            issues.append(f"{label}: need at least two customer turns")
            turns = []
        customers: list[str] = []
        for index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                issues.append(f"{label}: turn {index} must be an object")
                continue
            if set(turn) - TURN_KEYS:
                issues.append(f"{label}: turn {index} has an unknown field")
            customer = turn.get("customer")
            if not isinstance(customer, str) or not customer.strip():
                issues.append(f"{label}: turn {index} needs customer text")
            elif len(customer) > 4000:
                issues.append(f"{label}: turn {index} exceeds 4000 characters")
            else:
                customers.append(customer)
                if GRADING_CANARY in customer:
                    issues.append(f"{label}: canary leaked into a customer turn")
            kind = turn.get("kind")
            if kind not in KINDS:
                issues.append(f"{label}: turn {index} kind is invalid")
            else:
                kind_counts[kind] += 1
            for field in ("must_understand", "concrete_failures", "reviewer_judgments", "may_ask"):
                value = turn.get(field)
                if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
                    issues.append(f"{label}: turn {index} field {field} must be nonempty text")
            if "auto_facts" in turn and (
                not isinstance(turn["auto_facts"], dict) or set(turn["auto_facts"]) != AUTO_FACT_KEYS
            ):
                issues.append(f"{label}: turn {index} auto_facts keys are incomplete")
        if customers:
            sequences.append(tuple(customers))
        group = case.get("contrast_group")
        anchor = case.get("contrast_anchor")
        if (group is None) != (anchor is None):
            issues.append(f"{label}: contrast group and anchor must appear together")
        if group is not None:
            if isinstance(case_tags, list) and "contrast_pair" not in case_tags:
                issues.append(f"{label}: contrast case needs the contrast_pair tag")
            if not isinstance(group, str) or not group.strip():
                issues.append(f"{label}: contrast group must be text")
            elif isinstance(case_id, str):
                groups.setdefault(group, []).append(case_id)
            if not isinstance(anchor, str) or not anchor.strip():
                issues.append(f"{label}: contrast anchor must be text")
            elif customers and customers[-1] != anchor:
                issues.append(f"{label}: contrast anchor must be the last customer turn")
            elif isinstance(group, str):
                previous = anchors.get(anchor)
                if previous is not None and previous != group:
                    issues.append(f"{label}: anchor reused by another contrast group")
                anchors[anchor] = group
                if customers[:-1].count(anchor):
                    issues.append(f"{label}: anchor also appears earlier in the case")

    if len(sequences) != len(set(sequences)):
        issues.append("duplicate customer-turn sequences")
    missing_tags = REQUIRED_TAGS - tags_seen
    if missing_tags:
        issues.append("missing tags: " + ", ".join(sorted(missing_tags)))
    if len(groups) < 4:
        issues.append("expected at least four contrast pairs")
    for group, members in groups.items():
        if len(members) != 2:
            issues.append(f"{group}: a contrast pair needs two cases")
        pair_prefixes = []
        pair_anchors = []
        for case in cases:
            if isinstance(case, dict) and case.get("contrast_group") == group:
                turns = case.get("turns")
                if isinstance(turns, list) and turns and all(isinstance(turn, dict) for turn in turns):
                    pair_anchors.append(case.get("contrast_anchor"))
                    pair_prefixes.append(tuple(turn.get("customer") for turn in turns[:-1]))
        if len(pair_anchors) == 2 and pair_anchors[0] != pair_anchors[1]:
            issues.append(f"{group}: anchors differ")
        if len(pair_prefixes) == 2 and pair_prefixes[0] == pair_prefixes[1]:
            issues.append(f"{group}: previous customer turns must differ")
    for case in cases:
        if not isinstance(case, dict):
            continue
        for turn in case.get("turns") or []:
            if not isinstance(turn, dict):
                continue
            customer = turn.get("customer")
            if customer in anchors and case.get("contrast_group") != anchors[customer]:
                issues.append(f"{case.get('id')}: short contrast text used outside its pair")
    if kind_counts["conversation"] < 1 or kind_counts["automotive"] < 1:
        issues.append("both conversation and automotive turns are required")
    expected_ids = {f"w4a-{number:02d}" for number in range(1, 25)}
    if seen_ids != expected_ids:
        issues.append("case ids must be w4a-01 through w4a-24")
    return issues


def _forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_KEYS:
                found.add(key)
            found.update(_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_forbidden_keys(item))
    return found


def effective_auto_facts(dataset: dict[str, Any], turn: dict[str, Any]) -> dict[str, bool]:
    facts = dict(dataset["auto_facts"])
    if isinstance(turn.get("auto_facts"), dict):
        facts.update(turn["auto_facts"])
    return facts


def public_request(request_id: str, conversation_id: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Build the only body that may be posted. Copies role and text, nothing else."""

    if _UUID_RE.fullmatch(request_id) is None or _UUID_RE.fullmatch(conversation_id) is None:
        raise ValueError("request ids must be UUIDs")
    messages = []
    for item in history:
        role = item["role"]
        text = item["text"]
        if role not in {"user", "assistant"} or not isinstance(text, str) or text == "":
            raise ValueError("history must be user and assistant text")
        messages.append({"role": role, "text": text})
    if not messages or messages[0]["role"] != "user" or messages[-1]["role"] != "user":
        raise ValueError("a request must start and end with a customer turn")
    payload = {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "messages": messages,
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    if GRADING_CANARY in encoded:
        raise RuntimeError("refusing to send grading material")
    return payload


def make_http_post(base_url: str) -> Post:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"}:
        raise ValueError("base_url must be an http://127.0.0.1 or http://localhost origin")
    endpoint = base_url.rstrip("/") + "/api/chat"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def post(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
                status: int | None = response.status
                transport_error = None
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
                status = exc.code
                transport_error = None
            finally:
                exc.close()
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            return {
                "http_status": None,
                "latency_ms": latency_ms,
                "body": None,
                "transport_error": f"{type(exc).__name__}: {exc}",
            }
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        try:
            body = json.loads(raw.decode("utf-8"))
            json_error = None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            body = None
            json_error = f"{type(exc).__name__}: {exc}"
        record = {
            "http_status": status,
            "latency_ms": latency_ms,
            "body": body if isinstance(body, dict) else None,
            "transport_error": transport_error,
        }
        if json_error is not None:
            record["json_error"] = json_error
        elif not isinstance(body, dict):
            record["json_error"] = "response JSON must be an object"
        return record

    return post


def observe_facts(text: str) -> dict[str, bool]:
    return {
        "cyrillic": _CYRILLIC_RE.search(text) is not None,
        "price_amount": _CURRENCY_RE.search(text) is not None or _PRICE_WORD_RE.search(text) is not None,
        "confirmed_booking_phrase": _unnegated_booking(text),
        "asserted_hours_phrase": _HOURS_RE.search(text) is not None,
    }


def _unnegated_booking(text: str) -> bool:
    for match in _BOOKING_RE.finditer(text):
        if not _prefix_negated(text, match.start()):
            return True
    return False


def _prefix_negated(text: str, start: int) -> bool:
    sentence_start = 0
    for index in range(start - 1, -1, -1):
        if text[index] in ".!?\n":
            sentence_start = index + 1
            break
    return _NEGATION_RE.search(text[sentence_start:start]) is not None


def fact_conflicts(text: str, auto_facts: dict[str, bool]) -> list[str]:
    if text.strip() == "":
        return ["empty_reply"]
    observed = observe_facts(text)
    conflicts = []
    if auto_facts.get("expect_cyrillic") and not observed["cyrillic"]:
        conflicts.append("missing_cyrillic")
    if auto_facts.get("price_amount_is_failure") and observed["price_amount"]:
        conflicts.append("price_amount")
    if auto_facts.get("confirmed_booking_is_failure") and observed["confirmed_booking_phrase"]:
        conflicts.append("confirmed_booking_phrase")
    if auto_facts.get("asserted_hours_is_failure") and observed["asserted_hours_phrase"]:
        conflicts.append("asserted_hours_phrase")
    return conflicts


def interpret_transport(record: dict[str, Any]) -> tuple[str | None, dict[str, str] | None, float | None]:
    """Return reply text, error object, and server elapsed_ms when present."""

    if record.get("transport_error"):
        return None, {"code": "TRANSPORT", "message": str(record["transport_error"])}, None
    if record.get("json_error"):
        return None, {"code": "INVALID_RESPONSE", "message": str(record["json_error"])}, None
    body = record.get("body")
    server_elapsed = _server_elapsed(body)
    if not isinstance(body, dict):
        return None, {"code": "INVALID_RESPONSE", "message": "Response JSON must be an object."}, server_elapsed
    error = body.get("error")
    if error is not None or record.get("http_status") != 200:
        code = error.get("code") if isinstance(error, dict) and isinstance(error.get("code"), str) else "HTTP_ERROR"
        message = error.get("message") if isinstance(error, dict) and isinstance(error.get("message"), str) else "The request failed."
        return None, {"code": code, "message": message}, server_elapsed
    message = body.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant" or not isinstance(message.get("text"), str):
        return None, {"code": "INVALID_RESPONSE", "message": "The response did not include an assistant message."}, server_elapsed
    if message["text"].strip() == "":
        return None, {"code": "EMPTY_REPLY", "message": "The assistant message was empty."}, server_elapsed
    return message["text"], None, server_elapsed


def _server_elapsed(body: Any) -> float | None:
    if not isinstance(body, dict) or not isinstance(body.get("metrics"), dict):
        return None
    value = body["metrics"].get("elapsed_ms")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def run_case(case: dict[str, Any], post: Post, timeout: float, dataset_auto_facts: dict[str, bool]) -> dict[str, Any]:
    conversation_id = str(uuid.uuid4())
    history: list[dict[str, str]] = []
    records = []
    stopped = False
    for index, turn in enumerate(case["turns"]):
        auto_facts = dict(dataset_auto_facts)
        if isinstance(turn.get("auto_facts"), dict):
            auto_facts.update(turn["auto_facts"])
        if stopped:
            records.append(_skipped_turn(index, turn, conversation_id, auto_facts))
            continue
        history.append({"role": "user", "text": turn["customer"]})
        request_id = str(uuid.uuid4())
        payload = public_request(request_id, conversation_id, history)
        transport = post(payload, timeout)
        reply, error, server_elapsed = interpret_transport(transport)
        observations = observe_facts(reply) if reply is not None else None
        conflicts = fact_conflicts(reply, auto_facts) if reply is not None else []
        records.append({
            "index": index,
            "kind": turn["kind"],
            "customer": turn["customer"],
            "must_understand": turn["must_understand"],
            "may_ask": turn["may_ask"],
            "concrete_failures": turn["concrete_failures"],
            "reviewer_judgments": turn["reviewer_judgments"],
            "auto_facts": auto_facts,
            "sent": True,
            "request_id": request_id,
            "conversation_id": conversation_id,
            "sent_messages": payload["messages"],
            "http_status": transport.get("http_status"),
            "latency_ms": transport.get("latency_ms"),
            "server_elapsed_ms": server_elapsed,
            "reply": reply,
            "error": error,
            "fact_observations": observations,
            "fact_conflicts": conflicts,
        })
        if reply is None:
            stopped = True
        else:
            history.append({"role": "assistant", "text": reply})
    return {
        "id": case["id"],
        "tags": case["tags"],
        "contrast_group": case.get("contrast_group"),
        "turns": records,
    }


def _skipped_turn(index: int, turn: dict[str, Any], conversation_id: str, auto_facts: dict[str, bool]) -> dict[str, Any]:
    return {
        "index": index,
        "kind": turn["kind"],
        "customer": turn["customer"],
        "must_understand": turn["must_understand"],
        "may_ask": turn["may_ask"],
        "concrete_failures": turn["concrete_failures"],
        "reviewer_judgments": turn["reviewer_judgments"],
        "auto_facts": auto_facts,
        "sent": False,
        "request_id": None,
        "conversation_id": conversation_id,
        "sent_messages": None,
        "http_status": None,
        "latency_ms": None,
        "server_elapsed_ms": None,
        "reply": None,
        "error": {
            "code": "NOT_SENT",
            "message": "No actual assistant reply was available to continue this conversation.",
        },
        "fact_observations": None,
        "fact_conflicts": [],
    }


def summarize(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {"conversation": [], "automotive": []}
    for case in case_results:
        for turn in case["turns"]:
            buckets[turn["kind"]].append(turn)
    return {"by_kind": {kind: _kind_summary(turns) for kind, turns in buckets.items()}}


def _kind_summary(turns: list[dict[str, Any]]) -> dict[str, Any]:
    sent = [turn for turn in turns if turn["sent"]]
    latencies = [turn["latency_ms"] for turn in sent if isinstance(turn.get("latency_ms"), (int, float))]
    total = round(sum(latencies), 1) if latencies else 0.0
    return {
        "turns": len(turns),
        "sent": len(sent),
        "errors": sum(1 for turn in sent if turn.get("error")),
        "not_sent": sum(1 for turn in turns if not turn["sent"]),
        "fact_conflicts": sum(len(turn.get("fact_conflicts") or []) for turn in sent),
        "latency_ms": {
            "count": len(latencies),
            "total": total,
            "mean": round(total / len(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
    }


def run_dataset(dataset: dict[str, Any], post: Post, timeout: float, label: str, base_url: str) -> dict[str, Any]:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results = [run_case(case, post, timeout, dataset["auto_facts"]) for case in dataset["cases"]]
    return {
        "run_label": label,
        "harness_test": label.startswith("harness"),
        "schema": dataset["schema"],
        "scoring": dataset["scoring"],
        "business_data": dataset["business_data"],
        "base_url": base_url,
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": summarize(results),
        "cases": results,
    }


def write_packet(packet: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_summary(packet: dict[str, Any], output: Path) -> None:
    if packet["harness_test"]:
        print("HARNESS TEST: labeled harness run. Not a conversational quality evaluation.")
    summary = packet["summary"]["by_kind"]
    print(f"run_label={packet['run_label']}")
    print(f"cases={len(packet['cases'])}")
    for kind in ("conversation", "automotive"):
        bucket = summary[kind]
        print(
            f"{kind}_sent={bucket['sent']} {kind}_errors={bucket['errors']} "
            f"{kind}_not_sent={bucket['not_sent']} {kind}_fact_conflicts={bucket['fact_conflicts']} "
            f"{kind}_latency_mean_ms={bucket['latency_ms']['mean']}"
        )
    print(f"output={output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate customer-only conversations through POST /api/chat.")
    parser.add_argument("--base-url", required=True, help="Local origin, for example http://127.0.0.1:8766")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dataset = load_dataset(args.cases)
        post = make_http_post(args.base_url)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    packet = run_dataset(dataset, post, args.timeout, args.label, args.base_url.rstrip("/"))
    write_packet(packet, args.output)
    print_summary(packet, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
