"""Replay the three Wave 1 cases and record separate stage timings.

The Wave 1 baseline file is not modified. autoservice_dataset/test.jsonl is
not opened. One warmup request is sent after a service restart and is not
included in the sample.

Example:
    .venv312/bin/python benchmark/run_stage_timing.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_baseline import (
    CASES,
    COLD_TEXT,
    CHAT_URL,
    EXTRACT_HEALTH_URL,
    HEALTH_URL,
    get_json,
    judge,
    load_prefix,
    post_chat,
    require_holdout,
)

RESULTS = Path(__file__).resolve().parent / "results" / "stage_timing.json"
STAGES = ("catalog_shortlist_ms", "mica_ms", "qwen_ms", "reply_plan_ms")


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "median": round(statistics.median(ordered), 1),
        "min": round(ordered[0], 1),
        "max": round(ordered[-1], 1),
    }


def main() -> None:
    require_holdout([case["dialogue_id"] for case in CASES])
    health = get_json(HEALTH_URL)
    extract_health = get_json(EXTRACT_HEALTH_URL)
    get_json("http://127.0.0.1:8768/health")
    prefixes = {
        case["case_id"]: load_prefix(case["dialogue_id"], case["end_message_id"])
        for case in CASES
    }
    warmup_started = time.perf_counter()
    warmup = post_chat([{"role": "user", "text": COLD_TEXT}])
    warmup_ms = round((time.perf_counter() - warmup_started) * 1000, 1)
    if not warmup.get("ok"):
        raise SystemExit("warmup request failed")
    runs = []
    for repeat_index in (0, 1):
        for case in CASES:
            result = post_chat(prefixes[case["case_id"]])
            stages = ((result.get("metrics") or {}).get("stages") or {})
            missing = [name for name in STAGES if not isinstance(stages.get(name), (int, float))]
            if missing:
                raise SystemExit(f"{case['case_id']} is missing stage timings: {', '.join(missing)}")
            stage_values = {name: round(float(stages[name]), 1) for name in STAGES}
            runs.append({
                "case_id": case["case_id"],
                "dialogue_id": case["dialogue_id"],
                "end_message_id": case["end_message_id"],
                "repeat_index": repeat_index,
                "ok": result.get("ok"),
                "http_status": result.get("http_status"),
                "end_to_end_ms": result.get("wall_ms"),
                "extract_http_ms": result.get("extraction_ms"),
                "stages": stage_values,
                "stage_sum_ms": round(sum(stage_values.values()), 1),
                "unstaged_ms": round(result["wall_ms"] - sum(stage_values.values()), 1),
                "failures": judge(case, result.get("reply") or "", result.get("slots") or {}),
                "error": result.get("error"),
            })
    by_stage = {
        name: summarize([run["stages"][name] for run in runs])
        for name in STAGES
    }
    dominant = max(STAGES, key=lambda name: by_stage[name]["median"])
    payload = {
        "endpoint": CHAT_URL,
        "health": health,
        "extract_health": extract_health,
        "baseline_file": "benchmark/results/baseline.json",
        "baseline_modified": False,
        "warmup_excluded": {
            "requests": 1,
            "wall_ms": warmup_ms,
            "reason": "Discarded so the measured repeats run after Mica and Qwen are warm",
        },
        "sample_count": len(runs),
        "cases": 3,
        "warm_repeats_per_case": 2,
        "counting": (
            "catalog_shortlist_ms is outside mica_ms. reply_plan_ms is outside "
            "extract_http_ms. end_to_end_ms is the chat request wall time and is "
            "not the sum of the stages. unstaged_ms is the remainder."
        ),
        "summary": {
            "end_to_end_ms": summarize([run["end_to_end_ms"] for run in runs]),
            "stages": by_stage,
            "dominant_stage": dominant,
        },
        "runs": runs,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "sample_count": payload["sample_count"],
        "end_to_end_ms": payload["summary"]["end_to_end_ms"],
        "stages": by_stage,
        "dominant_stage": dominant,
        "saved": str(RESULTS),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
