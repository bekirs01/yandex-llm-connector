"""Select 40 development dialogue IDs from train.jsonl.

Later waves must exclude these IDs from retrieval. test.jsonl is never opened.
Selection is deterministic: pinned benchmark dialogues first, then an even
stride through the remaining candidates of each category.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "autoservice_dataset"
TRAIN = DATASET / "train.jsonl"
MANIFEST = DATASET / "manifest.json"
OUTPUT = Path(__file__).resolve().parent / "dev_dialogue_ids.json"

SPECIAL = {
    "unknown",
    "conflicting",
    "unspecified",
    "ambiguous_candidates",
    "multiple",
}
CATEGORIES = (
    "ambiguous",
    "missing_information",
    "correction",
    "explicit_service",
    "symptom",
)
PER_CATEGORY = 8
PINNED = {
    "correction": ("train_000402",),
    "symptom": ("train_000015",),
    "explicit_service": ("train_000178",),
    "missing_information": (),
    "ambiguous": (),
}
MISSING_PRIORITY = ("vehicle", "search_area", "main_symptom", "known_service", "intent")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def analyze(dialogue: dict) -> dict:
    unknowns: set[str] = set()
    ambiguous: set[str] = set()
    conflicting: set[str] = set()
    intents: set[str] = set()
    supersedes: set[str] = set()
    service_request = False
    specific_symptom = False
    for turn in dialogue["turns"]:
        for name, value in (turn.get("slots_after_message") or {}).items():
            if value == "unknown":
                unknowns.add(name)
            elif value == "ambiguous_candidates":
                ambiguous.add(name)
            elif value == "conflicting":
                conflicting.add(name)
            if name == "intent":
                intents.add(value)
            if name == "main_symptom" and value not in SPECIAL:
                specific_symptom = True
        for item in turn.get("evidence") or []:
            if item.get("kind") == "service_request":
                service_request = True
            if item.get("supersedes"):
                supersedes.add(item.get("slot"))
    return {
        "dialogue_id": dialogue["dialogue_id"],
        "unknowns": unknowns,
        "ambiguous": ambiguous,
        "conflicting": conflicting,
        "intents": intents,
        "supersedes": supersedes,
        "service_request": service_request,
        "specific_symptom": specific_symptom,
        "complaint": "complaint" in intents,
    }


def reason_for(category: str, row: dict) -> str:
    if category == "ambiguous":
        if row["ambiguous"]:
            return "known value is ambiguous_candidates: " + ", ".join(sorted(row["ambiguous"]))
        if row["conflicting"]:
            return "unresolved conflicting value: " + ", ".join(sorted(row["conflicting"]))
        return "intent is unknown"
    if category == "missing_information":
        return "customer left a slot unknown: " + ", ".join(sorted(row["unknowns"]))
    if category == "correction":
        return "customer superseded a previous fact: " + ", ".join(sorted(row["supersedes"]))
    if category == "explicit_service":
        return "evidence contains a service_request"
    return "complaint with a specific symptom and no explicit service order"


def priority(category: str, row: dict) -> tuple:
    if category == "ambiguous":
        rank = 0 if row["ambiguous"] else 1 if row["conflicting"] else 2
        return (rank, row["dialogue_id"])
    if category == "missing_information":
        rank = 0 if row["unknowns"] & set(MISSING_PRIORITY) else 1
        return (rank, row["dialogue_id"])
    if category == "correction":
        if "search_area" in row["supersedes"]:
            rank = 0
        elif "vehicle" in row["supersedes"]:
            rank = 1
        else:
            rank = 2
        return (rank, row["dialogue_id"])
    return (row["dialogue_id"],)


def candidates(category: str, rows: list[dict]) -> list[dict]:
    if category == "ambiguous":
        pool = [row for row in rows if row["ambiguous"] or row["conflicting"] or "unknown" in row["intents"]]
    elif category == "missing_information":
        pool = [row for row in rows if row["unknowns"]]
    elif category == "correction":
        pool = [row for row in rows if row["supersedes"]]
    elif category == "explicit_service":
        pool = [row for row in rows if row["service_request"]]
    else:
        pool = [
            row for row in rows
            if row["specific_symptom"] and row["complaint"] and not row["service_request"]
        ]
    return sorted(pool, key=lambda row: priority(category, row))


def stride(pool: list[dict], count: int, used: set[str]) -> list[dict]:
    available = [row for row in pool if row["dialogue_id"] not in used]
    if count <= 0 or not available:
        return []
    if len(available) <= count:
        return available
    chosen: list[dict] = []
    seen: set[str] = set()
    for index in range(count):
        cursor = min(len(available) - 1, int(index * len(available) / count))
        while cursor < len(available) and available[cursor]["dialogue_id"] in seen:
            cursor += 1
        if cursor >= len(available):
            break
        chosen.append(available[cursor])
        seen.add(available[cursor]["dialogue_id"])
    return chosen


def main() -> None:
    if not TRAIN.is_file():
        raise SystemExit(f"missing {TRAIN}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    train_hash = sha256(TRAIN)
    expected = manifest["files_sha256"]["train.jsonl"]
    if train_hash != expected:
        raise SystemExit("train.jsonl SHA-256 does not match manifest.json")

    rows = []
    with TRAIN.open(encoding="utf-8") as stream:
        for line in stream:
            rows.append(analyze(json.loads(line)))
    by_id = {row["dialogue_id"]: row for row in rows}

    selected: list[dict] = []
    used: set[str] = set()
    for category in CATEGORIES:
        for dialogue_id in PINNED[category]:
            row = by_id[dialogue_id]
            selected.append({
                "dialogue_id": dialogue_id,
                "category": category,
                "reason": reason_for(category, row),
                "pinned": True,
            })
            used.add(dialogue_id)
        remaining = PER_CATEGORY - sum(1 for item in selected if item["category"] == category)
        for row in stride(candidates(category, rows), remaining, used):
            selected.append({
                "dialogue_id": row["dialogue_id"],
                "category": category,
                "reason": reason_for(category, row),
                "pinned": False,
            })
            used.add(row["dialogue_id"])

    counts: dict[str, int] = {}
    for item in selected:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    if len(selected) != PER_CATEGORY * len(CATEGORIES) or any(counts.get(name) != PER_CATEGORY for name in CATEGORIES):
        raise SystemExit(f"selection is incomplete: {counts}")
    if len(used) != len(selected):
        raise SystemExit("duplicate development ids")

    payload = {
        "selection_version": "wave1-dev-holdout-v1",
        "source": "autoservice_dataset/train.jsonl",
        "train_sha256": train_hash,
        "test_jsonl": "unopened",
        "exclude_from_retrieval": True,
        "rule": (
            "Eight dialogues in each category. Benchmark dialogues "
            "train_000402, train_000015, and train_000178 are pinned. "
            "The rest are an even stride over candidates sorted by priority "
            "then dialogue_id. A dialogue is used in only one category. "
            "Order is ambiguous, missing_information, correction, "
            "explicit_service, symptom."
        ),
        "counts": counts,
        "dialogue_ids": [item["dialogue_id"] for item in selected],
        "dialogues": selected,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(selected)} ids)")
    for name in CATEGORIES:
        ids = [item["dialogue_id"] for item in selected if item["category"] == name]
        print(f"{name}: {', '.join(ids)}")


if __name__ == "__main__":
    main()
