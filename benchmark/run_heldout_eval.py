"""Replay the reserved test dialogues through the live chat endpoint.

Requests contain only role and text. Slot labels, evidence, and this file's
expected service ids stay on disk and are applied after the response arrives.
A skipped turn is not a pass.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp.grounding import _CITIES, _NAMES, ground_conversation
from webapp.turn_reading import read_turn


DATASET = ROOT / "autoservice_dataset" / "test.jsonl"
NOT_AN_ID = {"unknown", "ambiguous_candidates", "conflicting", "none", ""}
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def explicit_service(turn: dict) -> str | None:
    slots = turn.get("slots_after_message") or {}
    service = slots.get("known_service")
    if not isinstance(service, str) or service in NOT_AN_ID or " " in service:
        return None
    evidence = turn.get("evidence") or []
    named_here = any(
        isinstance(item, dict) and item.get("slot") == "known_service" and item.get("interpretation") == service
        for item in evidence
    )
    if slots.get("intent") == "known_service" and named_here:
        return service
    return None


def unsupported_claims(reply: str, customer_texts: list[str]) -> list[str]:
    messages = [{"role": "user", "text": text} for text in customer_texts]
    grounded = ground_conversation(messages, read_turn(messages))
    allowed = {part.casefold() for part in (grounded.make, grounded.model, grounded.year, grounded.city) if part}
    customer = " ".join(customer_texts).casefold()
    claims: list[str] = []
    for year in _YEAR.findall(reply):
        if year not in customer and year != grounded.year:
            claims.append(f"year:{year}")
    folded = reply.casefold()
    for canonical, _implied, aliases in _NAMES:
        if canonical.casefold() in folded or any(alias in folded for alias in aliases if len(alias) >= 4):
            if canonical.casefold() not in allowed and not any(alias in customer for alias in aliases):
                claims.append(f"name:{canonical}")
    for stem, canonical in _CITIES:
        if stem in folded and canonical.casefold() not in allowed and stem not in customer:
            claims.append(f"city:{canonical}")
    return claims


def post(base: str, messages: list[dict[str, str]], timeout: float) -> tuple[int, dict | None, str | None]:
    payload = {
        "request_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "messages": [{"role": item["role"], "text": item["text"]} for item in messages],
    }
    request = urllib.request.Request(
        base.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode()), None
    except Exception as exc:
        status = getattr(exc, "code", None)
        detail = None
        if hasattr(exc, "read"):
            try:
                detail = exc.read().decode()[:300]
            except Exception:
                detail = None
        return status or 0, None, f"{type(exc).__name__}: {detail or exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8769")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark" / "results" / "heldout_eval.json")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    dialogues = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        dialogues = dialogues[:args.limit]
    completed = 0
    failed = 0
    turns_sent = 0
    turns_failed = 0
    turns_skipped = 0
    degraded = 0
    explicit_hits = 0
    explicit_total = 0
    unsupported = 0
    rows = []
    started = time.perf_counter()
    for index, dialogue in enumerate(dialogues, 1):
        history: list[dict[str, str]] = []
        customer_so_far: list[str] = []
        dialogue_failed = False
        stopped = False
        for turn in dialogue["turns"]:
            if turn["role"] != "user":
                continue
            service_id = explicit_service(turn)
            if stopped:
                turns_skipped += 1
                continue
            history.append({"role": "user", "text": turn["text"]})
            customer_so_far.append(turn["text"])
            status, body, error = post(args.base_url, history, args.timeout)
            turns_sent += 1
            reply = ""
            origin = None
            service_ids: list[str] = []
            if status != 200 or not body or not isinstance(body.get("message"), dict):
                turns_failed += 1
                dialogue_failed = True
                stopped = True
                if service_id:
                    explicit_total += 1
                rows.append({
                    "dialogue_id": dialogue["dialogue_id"],
                    "message_id": turn["message_id"],
                    "status": status,
                    "error": error,
                    "skipped_rest": True,
                })
                continue
            reply = body["message"].get("text") or ""
            metrics = body.get("metrics") or {}
            origin = metrics.get("response_origin")
            if origin == "degraded" or metrics.get("degraded"):
                degraded += 1
            retrieval = metrics.get("retrieval") or {}
            service_ids = list(retrieval.get("service_ids") or [])[:3]
            claims = unsupported_claims(reply, customer_so_far)
            if claims:
                unsupported += 1
            if service_id:
                explicit_total += 1
                if service_id in service_ids:
                    explicit_hits += 1
            history.append({"role": "assistant", "text": reply})
            if service_id or claims or origin == "degraded":
                rows.append({
                    "dialogue_id": dialogue["dialogue_id"],
                    "message_id": turn["message_id"],
                    "status": status,
                    "origin": origin,
                    "explicit_service": service_id,
                    "top3": service_ids,
                    "hit": bool(service_id and service_id in service_ids),
                    "unsupported": claims,
                    "reply": reply,
                })
        if dialogue_failed:
            failed += 1
        else:
            completed += 1
        if index % 10 == 0:
            print(
                f"progress {index}/{len(dialogues)} completed={completed} failed={failed} "
                f"explicit={explicit_hits}/{explicit_total} unsupported_turns={unsupported} "
                f"degraded={degraded}",
                flush=True,
            )
    payload = {
        "endpoint": args.base_url.rstrip("/") + "/api/chat",
        "dialogues": len(dialogues),
        "completed": completed,
        "failed": failed,
        "turns_sent": turns_sent,
        "turns_failed": turns_failed,
        "turns_skipped": turns_skipped,
        "degraded_responses": degraded,
        "explicit_service_top3_hits": explicit_hits,
        "explicit_service_denominator": explicit_total,
        "unsupported_claim_turns": unsupported,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "notes": {
            "skipped_turns_are_not_passes": True,
            "labels_were_not_sent": True,
            "degraded_is_not_a_successful_model_response": True,
        },
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
