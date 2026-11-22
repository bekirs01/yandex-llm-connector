"""Evaluate cached Mica Q4 on the 12 OpenJev slots and 39 pilot messages."""

import argparse
import hashlib
import json
import math
import os
import re
import runpy
import statistics
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

from transformers import AutoTokenizer


DOWNLOADS = Path.home() / "Downloads"
STARTER = Path.home() / "Desktop/auto_service_slot_filling_starter/auto_service_slot_filling_starter"
MISSING = "__not_provided__"
SERVICE = "known_service"
SERVICE_STATES = {"unknown", "conflicting", "ambiguous_candidates"}
OPEN_FIELDS = {"main_symptom", "vehicle", "affected_item", "search_area"}


def read_jsonl(archive, member):
    return [json.loads(line) for line in archive.read(member).splitlines() if line.strip()]


def load_pilot():
    with zipfile.ZipFile(DOWNLOADS / "openjev_eski_qwen_test.zip") as archive:
        dialogues = read_jsonl(archive, "data/test.jsonl")[:10]
        schema = json.loads(archive.read("data/schema/slots.json"))
        catalog = json.loads(archive.read("data/schema/catalog.json"))
        identity = json.loads(archive.read("model_identity.json"))
    fields = {field["id"]: field for field in schema["slots"] if field["id"] not in OPEN_FIELDS}
    cases = []
    for dialogue in dialogues:
        history = []
        for turn in dialogue["turns"]:
            role = "Клиент" if turn["role"] == "user" else "Помощник"
            history.append(f"{turn['message_id']} | {role}: {turn['text']}")
            if turn["role"] == "user":
                cases.append({
                    "dialogue_id": dialogue["dialogue_id"],
                    "message_id": turn["message_id"],
                    "history": "\n".join(history),
                    "targets": {field: turn["slots_after_message"].get(field) for field in fields},
                })
    if len(fields) != 12 or len(cases) != 39 or len(catalog["results"]) != 394:
        raise ValueError("Unexpected OpenJev pilot schema or sample size")
    return cases, fields, catalog["results"], identity


def grams(text):
    words = re.findall(r"[^\W\d_]+", text.lower().replace("ё", "е"))
    return {word[i:i + 3] for word in words for i in range(len(word) - 2)}


class CatalogSearch:
    def __init__(self, services):
        self.terms = {service["id"]: grams(service["source_title"]) for service in services}
        frequencies = Counter(term for terms in self.terms.values() for term in terms)
        self.weights = {term: 1 + math.log(len(services) / count) for term, count in frequencies.items()}

    def shortlist(self, context, limit):
        query = grams(context)
        def rank(item):
            identifier, terms = item
            score = sum(self.weights[term] for term in sorted(terms & query))
            return -score / math.sqrt(max(len(terms), 1)), identifier
        return [identifier for identifier, _ in sorted(self.terms.items(), key=rank)[:limit]]


def load_baseline(cases, identity):
    prefix = "openjev_run_v1/training_v1/"
    with zipfile.ZipFile(DOWNLOADS / "openjev_model_yedek.zip") as archive:
        baseline = read_jsonl(archive, prefix + "test_predictions.jsonl")
        info = json.loads(archive.read(prefix + "training_finished.json"))
        adapter_hash = hashlib.sha256(archive.read(prefix + "final_adapter/adapter_model.safetensors")).hexdigest()
    indexed = {(row["dialogue_id"], row["message_id"]): row for row in baseline}
    matched = []
    for case in cases:
        row = indexed[(case["dialogue_id"], case["message_id"])]
        if row["targets"] != case["targets"]:
            raise ValueError("OpenJev baseline labels differ from the pilot")
        matched.append(row)
    return matched, {
        "run_id": info["run_id"],
        "generation": info["best_generation"],
        "adapter_sha256": adapter_hash,
        "matches_joint_pilot_checkpoint": adapter_hash == identity["openjev_adapter_sha256"],
        "hardware": matched[0]["environment"]["gpu"],
    }


def score(rows, fields):
    result = {}
    for field in fields:
        present = [row for row in rows if row["targets"][field] is not None]
        absent = [row for row in rows if row["targets"][field] is None]
        result[field] = {
            "present_correct": sum(row["prediction"].get(field) == row["targets"][field] for row in present),
            "present_total": len(present),
            "absent_correct": sum(row["prediction"].get(field) is None for row in absent),
            "absent_total": len(absent),
        }
    return result


def option(identifier, text):
    return {"id": identifier, "text": text}


def make_queries(case, fields, shortlist, titles):
    queries = []
    for field, definition in fields.items():
        choices = [option(MISSING, "Значение этого поля в диалоге ещё не указано")]
        if field == SERVICE:
            choices.extend(option(identifier, titles[identifier]) for identifier in shortlist)
            choices.extend(option(value, value.replace("_", " ")) for value in sorted(SERVICE_STATES))
        else:
            choices.extend(option(value, value.replace("_", " ")) for value in definition["values"])
        queries.append({
            "id": field,
            "kind": "choice",
            "state": case["history"],
            "question": (
                "Определи текущее значение поля к последнему сообщению. Учитывай исправления клиента. "
                "Вопросы помощника не являются фактами клиента. " + definition["question"]
            ),
            "candidates": choices,
        })
    return queries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, choices=range(1, 40), default=39)
    parser.add_argument("--output", type=Path, default=Path("mica_pilot_results.json"))
    args = parser.parse_args()
    cases, fields, services, identity = load_pilot()
    cases = cases[:args.limit]
    baseline, baseline_info = load_baseline(cases, identity)
    search = CatalogSearch(services)
    titles = {service["id"]: service["source_title"] for service in services}

    sys.path.insert(0, str(STARTER))
    starter = runpy.run_path(str(STARTER / "test_mica_19.py"))
    local = Path(os.environ["LOCALAPPDATA"])
    sys.path.insert(0, str(local / "mica-inference-code" / starter["SOURCE_COMMIT"]))
    from mica.codebook import MAX_CANDIDATES
    from mica.direct_backend import DirectJudge

    short_count = min(16, MAX_CANDIDATES - 4)
    cached_repo = "models--" + starter["MODEL_REPO"].replace("/", "--")
    tokenizer_path = Path.home() / ".cache/huggingface/hub" / cached_repo / "snapshots" / starter["MODEL_REVISION"]
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    rows = []
    print(f"Mica Q4 CPU: {len(cases)} messages, {len(fields)} slots, top {short_count}/{len(titles)} services", flush=True)
    with DirectJudge(
        str(starter["find_model"]()), tokenizer, runtime_dir=str(local / "mica-llama-b11010"),
        n_gpu_layers=0, n_ctx=3072, max_length=3072, n_seq_max=1,
        n_ubatch=256, n_threads=min(6, os.cpu_count() or 4), temperature=1.124473,
    ) as judge:
        for index, case in enumerate(cases, 1):
            started = time.perf_counter()
            shortlist = search.shortlist(case["history"], short_count)
            queries = make_queries(case, fields, shortlist, titles)
            distributions = judge.judge(queries, session_id="mica-pilot")
            prediction = {}
            for query, probabilities in zip(queries, distributions, strict=True):
                winner = max(range(len(probabilities)), key=probabilities.__getitem__)
                value = query["candidates"][winner]["id"]
                if value != MISSING:
                    prediction[query["id"]] = value
            rows.append({
                "dialogue_id": case["dialogue_id"], "message_id": case["message_id"],
                "targets": case["targets"], "prediction": prediction,
                "service_shortlist": shortlist, "seconds": time.perf_counter() - started,
            })
            service_rows = [row for row in rows if row["targets"][SERVICE] in titles]
            report = {
                "messages_completed": len(rows), "messages_requested": len(cases),
                "service_shortlist_size": short_count,
                "service_shortlist_hits": sum(row["targets"][SERVICE] in row["service_shortlist"] for row in service_rows),
                "service_shortlist_total": len(service_rows),
                "mica": {"hardware": "local CPU", "median_seconds": statistics.median(row["seconds"] for row in rows),
                         "scores": score(rows, fields)},
                "openjev": {**baseline_info, "median_seconds": statistics.median(row["seconds"] for row in baseline[:index]),
                            "scores": score(baseline[:index], fields)},
                "rows": rows,
            }
            temporary = args.output.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(args.output)
            print(f"{index}/{len(cases)} {case['dialogue_id']}/{case['message_id']} {rows[-1]['seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
