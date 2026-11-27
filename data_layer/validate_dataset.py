"""Validate the autoservice dataset without printing dialogue text.

Structural errors, possible semantic overlap, and human-review status are
reported separately. Test dialogues are checked in memory. Their text is not
written to the report or to stdout.

Example:
    python data_layer/validate_dataset.py
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "autoservice_dataset"
HOLDOUT_PATH = ROOT / "benchmark" / "dev_dialogue_ids.json"
REPORT_PATH = ROOT / "benchmark" / "results" / "import_validation.json"

SPLITS = ("train", "test")
DIALOGUE_ID_RE = re.compile(r"^(train|test)_[0-9]{6}$")
EVIDENCE_FIELDS = (
    "interpretation",
    "kind",
    "message_id",
    "raw_text",
    "slot",
    "supersedes",
    "time_scope",
)
KINDS = {"observation", "hypothesis", "reported_diagnosis", "service_request"}
TIME_SCOPES = {"past", "current", "unspecified"}
FREE_TEXT_SLOTS = {"main_symptom", "vehicle", "affected_item", "search_area"}
SERVICE_SPECIAL = {"ambiguous_candidates", "unknown", "conflicting"}
MASK_SLOTS = {"vehicle": "<vehicle>", "search_area": "<city>"}
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
NEAR_THRESHOLD = 0.6
MAX_LISTED_PAIRS = 20

# Names in slots.json that describe a free-text type. They are not stored
# category values. ambiguous_candidates is a real known_service value.
TYPE_PLACEHOLDERS = {
    "known_service": {"catalog_id"},
    "main_symptom": {"free_text"},
    "vehicle": {"make_model_year_free_text", "document_data"},
    "affected_item": {"free_text"},
    "search_area": {"city_district_free_text"},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def check_manifest() -> dict:
    manifest_path = DATASET / "manifest.json"
    manifest = load_json(manifest_path)
    mismatches = []
    checked = 0
    files = manifest.get("files_sha256")
    if not isinstance(files, dict):
        return {"status": "failed", "files_checked": 0, "mismatches": ["files_sha256 missing"]}
    for name, expected in files.items():
        checked += 1
        path = DATASET / name
        if not path.is_file():
            mismatches.append({"file": name, "problem": "missing"})
            continue
        actual = sha256_file(path)
        if actual != expected:
            mismatches.append({"file": name, "problem": "sha256_mismatch"})
    return {
        "status": "passed" if not mismatches else "failed",
        "files_checked": checked,
        "mismatches": mismatches,
        "dataset_version": manifest.get("dataset_version"),
        "schema_version": manifest.get("schema_version"),
    }


def slot_rules(slots_doc: dict) -> dict[str, set[str]]:
    rules = {}
    for slot in slots_doc["slots"]:
        rules[slot["id"]] = set(slot["values"])
    return rules


def service_ids(catalog: dict) -> set[str]:
    return {item["id"] for item in catalog["results"]}


def structural_errors_for(
    dialogue: dict,
    split: str,
    rules: dict[str, set[str]],
    services: set[str],
) -> list[dict]:
    errors = []
    dialogue_id = dialogue.get("dialogue_id")

    def add(code: str, message_id: str | None = None) -> None:
        item = {"split": split, "dialogue_id": dialogue_id, "code": code}
        if message_id is not None:
            item["message_id"] = message_id
        errors.append(item)

    if not isinstance(dialogue_id, str) or DIALOGUE_ID_RE.fullmatch(dialogue_id) is None:
        add("dialogue_id_format")
    elif not dialogue_id.startswith(split + "_"):
        add("dialogue_id_split_prefix")
    if dialogue.get("language") != "ru":
        add("language")
    if dialogue.get("schema_version") != "0.1-draft":
        add("schema_version")
    turns = dialogue.get("turns")
    if not isinstance(turns, list) or not turns:
        add("turns_missing")
        return errors

    previous_slots: dict = {}
    user_state: dict[str, dict] = {}
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict):
            add("turn_type", f"m{index}")
            continue
        message_id = turn.get("message_id")
        expected_id = f"m{index}"
        if message_id != expected_id:
            add("message_id_sequence", str(message_id))
        role = turn.get("role")
        if role not in {"user", "assistant"}:
            add("role", expected_id)
        text = turn.get("text")
        if not isinstance(text, str) or not text.strip():
            add("empty_text", expected_id)
            text = text if isinstance(text, str) else ""
        slots = turn.get("slots_after_message")
        evidence = turn.get("evidence")
        if not isinstance(slots, dict) or not isinstance(evidence, list):
            add("turn_shape", expected_id)
            continue
        if set(turn) != {"evidence", "message_id", "role", "slots_after_message", "text"}:
            add("turn_fields", expected_id)
        if index == 1 and role != "user":
            add("first_turn_not_user", expected_id)
        for slot_name, value in slots.items():
            if slot_name not in rules:
                add("unknown_slot", expected_id)
                continue
            if not isinstance(value, str) or not value.strip():
                add("slot_value_type", expected_id)
                continue
            if slot_name == "known_service":
                if value not in services and value not in SERVICE_SPECIAL:
                    add("unknown_service", expected_id)
            elif slot_name not in FREE_TEXT_SLOTS and value not in rules[slot_name]:
                add("slot_value_not_allowed", expected_id)
            elif slot_name in FREE_TEXT_SLOTS and value in rules[slot_name] - {"unknown", "conflicting", "multiple"}:
                if value in TYPE_PLACEHOLDERS.get(slot_name, set()):
                    add("type_placeholder_stored", expected_id)
        if role == "assistant":
            if evidence:
                add("assistant_evidence", expected_id)
            if slots != previous_slots:
                add("assistant_changed_slots", expected_id)
            previous_slots = slots
            continue
        if not set(slots) >= set(previous_slots):
            add("slot_key_removed", expected_id)
        seen_slots: set[str] = set()
        for entry in evidence:
            if not isinstance(entry, dict) or tuple(sorted(entry)) != EVIDENCE_FIELDS:
                add("evidence_fields", expected_id)
                continue
            slot_name = entry.get("slot")
            if slot_name in seen_slots:
                add("duplicate_evidence_slot", expected_id)
            if isinstance(slot_name, str):
                seen_slots.add(slot_name)
            if entry.get("message_id") != message_id:
                add("evidence_message_id", expected_id)
            if entry.get("kind") not in KINDS or entry.get("time_scope") not in TIME_SCOPES:
                add("evidence_enum", expected_id)
            raw_text = entry.get("raw_text")
            interpretation = entry.get("interpretation")
            if not isinstance(raw_text, str) or not raw_text or raw_text not in text:
                add("evidence_quote", expected_id)
            if not isinstance(interpretation, str) or slots.get(slot_name) != interpretation:
                add("evidence_interpretation", expected_id)
            if previous_slots.get(slot_name) == slots.get(slot_name) and entry.get("supersedes") is None:
                add("evidence_without_change", expected_id)
            supersedes = entry.get("supersedes")
            if supersedes is not None:
                prior = user_state.get(supersedes)
                if prior is None or not isinstance(slot_name, str) or slot_name not in prior:
                    add("correction_reference", expected_id)
        for slot_name, value in slots.items():
            if previous_slots.get(slot_name) != value and slot_name not in seen_slots:
                add("changed_slot_without_evidence", expected_id)
        user_state[message_id] = dict(slots)
        previous_slots = slots
    return errors


def normalized_user_profile(dialogue: dict) -> tuple[str, frozenset[tuple[str, str, str]]]:
    tokens: list[str] = []
    for turn in dialogue["turns"]:
        if turn.get("role") != "user" or not isinstance(turn.get("text"), str):
            continue
        text = turn["text"].casefold().replace("ё", "е")
        for entry in turn.get("evidence") or []:
            if not isinstance(entry, dict):
                continue
            placeholder = MASK_SLOTS.get(entry.get("slot"))
            raw_text = entry.get("raw_text")
            if placeholder and isinstance(raw_text, str) and len(raw_text.strip()) >= 3:
                text = text.replace(raw_text.casefold().replace("ё", "е"), f" {placeholder} ")
        tokens.extend(WORD_RE.findall(text))
    grams = frozenset(tuple(tokens[index:index + 3]) for index in range(len(tokens) - 2))  # type: ignore[misc]
    return " ".join(tokens), grams


def jaccard(left: frozenset, right: frozenset) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    if union == 0:
        return 0.0
    return len(left & right) / union


def screen_duplicates(dialogues: list[dict]) -> dict:
    profiles = []
    for dialogue in dialogues:
        normalized, grams = normalized_user_profile(dialogue)
        profiles.append({
            "dialogue_id": dialogue["dialogue_id"],
            "split": dialogue["_split"],
            "normalized": normalized,
            "grams": grams,
        })
    exact_groups: dict[str, list[dict]] = defaultdict(list)
    for profile in profiles:
        if profile["normalized"]:
            exact_groups[profile["normalized"]].append(profile)
    exact = {"within_train": 0, "within_test": 0, "cross_split": 0}
    for group in exact_groups.values():
        if len(group) < 2:
            continue
        splits = {item["split"] for item in group}
        if splits == {"train", "test"}:
            exact["cross_split"] += 1
        elif "train" in splits:
            exact["within_train"] += len(group) * (len(group) - 1) // 2
        else:
            exact["within_test"] += len(group) * (len(group) - 1) // 2

    buckets: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, profile in enumerate(profiles):
        for gram in profile["grams"]:
            buckets[gram].append(index)
    candidates: set[tuple[int, int]] = set()
    for indexes in buckets.values():
        if not 2 <= len(indexes) <= 30:
            continue
        unique = sorted(set(indexes))
        if len(unique) > 30:
            continue
        for left_at, left in enumerate(unique):
            for right in unique[left_at + 1:]:
                candidates.add((left, right))
    near = {"within_train": 0, "within_test": 0, "cross_split": 0}
    listed = []
    for left, right in candidates:
        score = jaccard(profiles[left]["grams"], profiles[right]["grams"])
        if score < NEAR_THRESHOLD:
            continue
        pair_splits = {profiles[left]["split"], profiles[right]["split"]}
        if pair_splits == {"train", "test"}:
            near["cross_split"] += 1
        elif profiles[left]["split"] == "train":
            near["within_train"] += 1
            if len(listed) < MAX_LISTED_PAIRS:
                listed.append({
                    "dialogue_id_a": profiles[left]["dialogue_id"],
                    "dialogue_id_b": profiles[right]["dialogue_id"],
                    "jaccard": round(score, 3),
                })
        else:
            near["within_test"] += 1
    return {
        "threshold": NEAR_THRESHOLD,
        "method": (
            "Jaccard similarity of consecutive user-word triples after vehicle "
            "and city evidence quotes are replaced with placeholders"
        ),
        "normalized_exact": exact,
        "near_pairs": near,
        "listed_within_train_near_pairs": listed,
    }


def service_overlap(dialogues: list[dict], services: set[str]) -> list[str]:
    by_split: dict[str, set[str]] = {"train": set(), "test": set()}
    for dialogue in dialogues:
        for turn in dialogue["turns"]:
            for entry in turn.get("evidence") or []:
                if entry.get("slot") != "known_service":
                    continue
                value = entry.get("interpretation")
                if value in services:
                    by_split[dialogue["_split"]].add(value)
    return sorted(by_split["train"] & by_split["test"])


def read_dialogues() -> list[dict]:
    dialogues = []
    for split in SPLITS:
        path = DATASET / f"{split}.jsonl"
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    dialogue = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{split}.jsonl line {line_number} is not valid JSON") from exc
                if isinstance(dialogue, dict):
                    dialogue["_split"] = split
                dialogues.append(dialogue)
    return dialogues


def validate() -> dict:
    manifest = check_manifest()
    slots_doc = load_json(DATASET / "schema" / "slots.json")
    catalog = load_json(DATASET / "schema" / "catalog.json")
    quality = load_json(DATASET / "quality_report.json")
    holdout = load_json(HOLDOUT_PATH)
    rules = slot_rules(slots_doc)
    services = service_ids(catalog)
    dialogues = read_dialogues()

    counts = {split: {"dialogues": 0, "turns": 0, "evidence": 0} for split in SPLITS}
    ids: dict[str, list[str]] = {split: [] for split in SPLITS}
    structural = []
    ambiguous = 0
    for dialogue in dialogues:
        split = dialogue.get("_split")
        if split not in counts or not isinstance(dialogue, dict):
            structural.append({"split": split, "dialogue_id": None, "code": "dialogue_type"})
            continue
        counts[split]["dialogues"] += 1
        turns = dialogue.get("turns") if isinstance(dialogue.get("turns"), list) else []
        counts[split]["turns"] += len(turns)
        for turn in turns:
            if isinstance(turn, dict) and isinstance(turn.get("evidence"), list):
                counts[split]["evidence"] += len(turn["evidence"])
            slots = turn.get("slots_after_message") if isinstance(turn, dict) else None
            if isinstance(slots, dict) and slots.get("known_service") == "ambiguous_candidates":
                ambiguous += 1
        ids[split].append(dialogue.get("dialogue_id"))
        structural.extend(structural_errors_for(dialogue, split, rules, services))

    train_ids = [dialogue_id for dialogue_id in ids["train"] if isinstance(dialogue_id, str)]
    test_ids = [dialogue_id for dialogue_id in ids["test"] if isinstance(dialogue_id, str)]
    train_set = set(train_ids)
    test_set = set(test_ids)
    holdout_ids = holdout.get("dialogue_ids") if isinstance(holdout, dict) else None
    if not isinstance(holdout_ids, list):
        holdout_ids = []
    holdout_set = set(holdout_ids)
    duplicate_ids = [dialogue_id for dialogue_id, count in Counter(train_ids + test_ids).items() if count > 1]
    if duplicate_ids:
        structural.append({
            "split": "both",
            "dialogue_id": None,
            "code": "duplicate_dialogue_id",
            "count": len(duplicate_ids),
        })

    invalid_ids = {
        item["dialogue_id"]
        for item in structural
        if item.get("split") == "train" and isinstance(item.get("dialogue_id"), str)
    }
    before_exclusions = len(train_set - holdout_set)
    eligible = len((train_set - holdout_set) - invalid_ids)
    review = quality.get("annotation_review", {})
    human_reviewed = review.get("human_expert_reviewed")
    expert_approved = review.get("expert_approved")
    duplicates = screen_duplicates([
        dialogue for dialogue in dialogues
        if isinstance(dialogue, dict) and isinstance(dialogue.get("turns"), list)
    ])
    overlap = service_overlap([
        dialogue for dialogue in dialogues
        if isinstance(dialogue, dict) and isinstance(dialogue.get("turns"), list)
    ], services)
    test_hash = sha256_file(DATASET / "test.jsonl")
    expected_test_hash = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))["files_sha256"]["test.jsonl"]
    report = {
        "manifest": manifest,
        "counts": counts,
        "catalog_services": len(services),
        "slot_definitions": len(rules),
        "accepted_schema_values": {
            "ambiguous_candidates_on_known_service": ambiguous,
            "note": "ambiguous_candidates is a valid known_service value and is not a structural error",
        },
        "structural": {
            "status": "passed" if not structural else "failed",
            "error_count": len(structural),
            "errors": structural[:MAX_LISTED_PAIRS],
        },
        "split_isolation": {
            "train_test_id_overlap": len(train_set & test_set),
            "duplicate_dialogue_ids": len(duplicate_ids),
            "dev_count": len(holdout_set),
            "dev_not_in_train": sorted(holdout_set - train_set),
            "dev_in_test": len(holdout_set & test_set),
            "holdout_hash_matches_train_manifest": holdout.get("train_sha256") == json.loads(
                (DATASET / "manifest.json").read_text(encoding="utf-8")
            )["files_sha256"]["train.jsonl"],
        },
        "possible_semantic_issues": {
            "duplicates": duplicates,
            "explicit_service_id_overlap_between_splits": overlap,
            "effect_on_retrieval": "not excluded",
        },
        "human_review": {
            "expert_approved": expert_approved,
            "human_expert_reviewed": human_reviewed,
            "status": "not_reviewed" if not expert_approved else "approved",
            "effect_on_retrieval": "recorded only; missing human review does not exclude dialogues",
        },
        "retrieval_pool": {
            "train_dialogues": len(train_set),
            "reserved_dev_dialogues": len(holdout_set & train_set),
            "before_validation_exclusions": before_exclusions,
            "structural_exclusions": len(invalid_ids - holdout_set),
            "eligible": eligible,
            "semantic_issues_excluded": False,
            "human_review_excluded": False,
        },
        "test_integrity": {
            "opened_for_validation": True,
            "examples_printed": False,
            "content_used_for_development": False,
            "hash_matches_manifest": test_hash == expected_test_hash,
            "dialogues": counts["test"]["dialogues"],
            "turns": counts["test"]["turns"],
            "structural_error_count": sum(1 for item in structural if item.get("split") == "test"),
            "isolated_from_train": len(train_set & test_set) == 0,
        },
        "invalid_train_dialogue_ids": sorted(invalid_ids),
    }
    return report


def main() -> None:
    report = validate()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pool = report["retrieval_pool"]
    print(
        "validation",
        report["structural"]["status"],
        "manifest",
        report["manifest"]["status"],
        "eligible",
        pool["eligible"],
        "structural_errors",
        report["structural"]["error_count"],
        "report",
        REPORT_PATH,
    )


if __name__ == "__main__":
    main()
