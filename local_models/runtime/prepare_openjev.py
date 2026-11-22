"""Verified preparation of Nikita's current data for Open-jev training.

This stage creates training inputs and checks the pinned tokenizer. It does
not perform optimization or claim that the model has reached the quality goal.
Original labels are preserved. Missing fields are represented as null here,
and are never silently relabelled as 'unknown'.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_ID = "sshalimov04/open-jev-base"
REVISION = "bf071a696e3a6ea486bfc16c22cedbfb9c3ee207"
WEIGHT_SHA256 = "216715a3fba176d19cf650bfaee52b8b11b33258b0e611aca4d3af79ad4a57a4"
TOKENIZER_SHA256 = "c01f8492531b2e569bd8d28ef1de1c66779275753c78cb497f7118762ae3230d"
SEED = "nikita-openjev-split-v1"
ENUM_FIELDS = (
    "intent", "current_state", "event", "previous_diagnosis", "powertrain",
    "gearbox", "observed_context", "location_format", "fitment", "access_proof",
    "commercial_scope",
)
OPEN_FIELDS = ("main_symptom", "vehicle", "affected_item", "search_area")
TARGET_FIELDS = ENUM_FIELDS + ("known_service",)
SERVICE_STATES = ("ambiguous_candidates", "unknown", "conflicting")
EVIDENCE_KEYS = {"slot", "message_id", "raw_text", "kind", "time_scope", "supersedes", "interpretation"}
KINDS = {"observation", "hypothesis", "reported_diagnosis", "service_request"}
SCOPES = {"past", "current", "unspecified"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Tekrarlanan JSON anahtari: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_json)


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_package(root):
    manifest = read_json(root / "package_manifest.json")
    for name, expected in manifest["files_sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or file_hash(path) != expected:
            raise ValueError(f"Paket dosyasi eksik veya degismis: {name}")
    return manifest


def load_schema(root):
    schema = read_json(root / "data/schema/slots.json")
    catalog = read_json(root / "data/schema/catalog.json")
    fields = {item["id"]: item for item in schema["slots"]}
    if len(fields) != len(schema["slots"]) or set(fields) != set(TARGET_FIELDS + OPEN_FIELDS):
        raise ValueError("Beklenen guncel 16 alanli sema bulunamadi.")
    services = {item["id"]: item for item in catalog["results"]}
    if len(services) != len(catalog["results"]):
        raise ValueError("Katalogda tekrar eden servis kimligi var.")
    if not services or any(not isinstance(item.get("source_title"), str) for item in services.values()):
        raise ValueError("Katalog bos veya servis aciklamasi eksik.")
    return schema, fields, catalog, services


def validate_dialogue(dialogue, fields, services):
    if not isinstance(dialogue.get("dialogue_id"), str) or not dialogue["dialogue_id"]:
        raise ValueError("Diyalog kimligi eksik.")
    turns = dialogue.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError("Diyalog mesajlari bos.")
    previous, source_by_slot, seen_ids = {}, {}, set()
    user_count = 0
    for turn in turns:
        identifier = turn.get("message_id")
        if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
            raise ValueError(f"Gecersiz veya tekrar eden mesaj kimligi: {identifier}")
        seen_ids.add(identifier)
        if turn.get("role") not in ("user", "assistant") or not isinstance(turn.get("text"), str):
            raise ValueError(f"Mesaj rolu/metni gecersiz: {identifier}")
        user_count += turn["role"] == "user"
        state = turn.get("slots_after_message")
        evidence = turn.get("evidence")
        if not isinstance(state, dict) or set(state) - set(fields) or not isinstance(evidence, list):
            raise ValueError(f"Slot veya evidence semasi gecersiz: {identifier}")
        for key, value in state.items():
            if not isinstance(value, str):
                raise ValueError(f"Slot degeri metin degil: {identifier}/{key}")
            if key in ENUM_FIELDS and value not in fields[key]["values"]:
                raise ValueError(f"Semada olmayan enum degeri: {identifier}/{key}={value}")
            if key == "known_service" and value not in services and value not in SERVICE_STATES:
                raise ValueError(f"Katalogda olmayan referans kodu: {identifier}/{value}")
        changes = {}
        if turn["role"] == "assistant" and evidence:
            raise ValueError(f"Asistan mesajinda yeni evidence var: {identifier}")
        for item in evidence:
            if not isinstance(item, dict) or set(item) != EVIDENCE_KEYS:
                raise ValueError(f"Evidence alanlari gecersiz: {identifier}")
            key = item["slot"]
            if not isinstance(key, str) or key not in fields or key in changes:
                raise ValueError(f"Evidence slotu gecersiz/tekrarli: {identifier}")
            if item["message_id"] != identifier or not isinstance(item["raw_text"], str) or not item["raw_text"] or item["raw_text"] not in turn["text"]:
                raise ValueError(f"Evidence alintisi/mesaj kimligi uyumsuz: {identifier}")
            if item["kind"] not in KINDS or item["time_scope"] not in SCOPES:
                raise ValueError(f"Evidence kind/time_scope gecersiz: {identifier}")
            if item["supersedes"] != source_by_slot.get(key):
                raise ValueError(f"Duzeltme baglantisi uyumsuz: {identifier}/{key}")
            changes[key] = item["interpretation"]
        updated = {**previous, **changes}
        if updated != state:
            raise ValueError(f"Slot durumu evidence ile eslesmiyor: {identifier}")
        for key in changes:
            source_by_slot[key] = identifier
        previous = dict(state)
    if not user_count:
        raise ValueError("Diyalogda kullanici mesaji yok.")


def load_training_dialogues(root, fields, services):
    dialogues, ids, signatures = [], set(), set()
    with (root / "data/train.jsonl").open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"Egitim verisinde bos satir: {number}")
            dialogue = json.loads(line, object_pairs_hook=unique_json)
            validate_dialogue(dialogue, fields, services)
            identifier = dialogue["dialogue_id"]
            signature = canonical([(turn["role"], turn["text"]) for turn in dialogue["turns"]])
            if identifier in ids or signature in signatures:
                raise ValueError(f"Tekrarlanan egitim diyalogu: {identifier}")
            ids.add(identifier)
            signatures.add(signature)
            dialogues.append(dialogue)
    if len(dialogues) != 1000:
        raise ValueError(f"Beklenen 1000 egitim diyalogu yerine {len(dialogues)} bulundu.")
    return dialogues


def support_tokens(dialogue):
    # Preserve at least one training dialogue for each observed closed-field
    # class. This uses training labels only, never held-out test labels.
    return {(field, turn["slots_after_message"][field])
            for turn in dialogue["turns"] if turn["role"] == "user"
            for field in ENUM_FIELDS if field in turn["slots_after_message"]}


def split_dialogues(dialogues, validation_count=100):
    supports = {item["dialogue_id"]: support_tokens(item) for item in dialogues}
    remaining = Counter(token for tokens in supports.values() for token in tokens)
    ordered = sorted(dialogues, key=lambda item: hashlib.sha256((SEED + item["dialogue_id"]).encode()).hexdigest())
    validation = []
    for dialogue in ordered:
        tokens = supports[dialogue["dialogue_id"]]
        if len(validation) < validation_count and all(remaining[token] >= 2 for token in tokens):
            validation.append(dialogue)
            remaining.subtract(tokens)
    if len(validation) != validation_count:
        raise ValueError("Sinif destegini koruyarak dogrulama ayrimi yapilamadi.")
    validation_ids = {item["dialogue_id"] for item in validation}
    training = [item for item in ordered if item["dialogue_id"] not in validation_ids]
    return training, validation


def make_cases(dialogues):
    cases = []
    for dialogue in dialogues:
        history = []
        for turn in dialogue["turns"]:
            history.append({key: turn[key] for key in ("message_id", "role", "text")})
            if turn["role"] != "user":
                continue
            state = turn["slots_after_message"]
            cases.append({
                "dialogue_id": dialogue["dialogue_id"], "message_id": turn["message_id"],
                "history": list(history),
                "targets": {field: state.get(field) for field in TARGET_FIELDS},
            })
    return cases


def render_context(history):
    return "\n".join(f"{turn['message_id']} | {'Клиент' if turn['role'] == 'user' else 'Помощник'}: {turn['text']}" for turn in history)


def candidate_options(field, fields, services):
    missing = {"id": "__not_provided__", "text": "Значение этого поля в диалоге ещё не указано"}
    if field == "known_service":
        values = [{"id": item["id"], "text": item["source_title"]}
                  for item in sorted(services.values(), key=lambda item: item["id"])]
        values += [{"id": value, "text": value.replace("_", " ")} for value in SERVICE_STATES]
    else:
        values = [{"id": value, "text": value.replace("_", " ")} for value in fields[field]["values"]]
    return [missing] + values


def build_tasks(fields, services):
    return {field: {
        "type": "choice", "question": fields[field]["question"],
        "options": candidate_options(field, fields, services),
    } for field in TARGET_FIELDS}


def render_question(task, option, tokenizer):
    rendered = [f"{item['id']}: {item['text']}" for item in task["options"]]
    contrast, used = [], 0
    for text in rendered:
        count = len(tokenizer(text, add_special_tokens=False)["input_ids"]) + 1
        if used + count > 96:
            break
        contrast.append(text)
        used += count
    choices = " | ".join(contrast)
    if len(contrast) < len(rendered):
        choices += f"…(+{len(rendered) - len(contrast)} more)"
    question = ("По диалогу до последнего сообщения определи текущее значение поля. "
                "Учитывай исправления клиента. Вопросы помощника не являются фактами клиента. "
                + task["question"])
    return f"choice | Q: {question} | option: {option['id']}: {option['text']} | options: {choices}"


def length_audit(cases, tasks, tokenizer, maximum=1024):
    # Paired tokenization encodes the two segments separately. Bound every
    # candidate/history pair using both separate maxima and pair special tokens.
    contexts = [render_context(case["history"]) for case in cases]
    context_lengths = [len(tokenizer(text, add_special_tokens=False)["input_ids"]) for text in contexts]
    longest_index = max(range(len(contexts)), key=context_lengths.__getitem__)
    prompts = [(field, option["id"], render_question(task, option, tokenizer))
               for field, task in tasks.items() for option in task["options"]]
    prompt_lengths = [len(tokenizer(item[2], add_special_tokens=False)["input_ids"]) for item in prompts]
    prompt_index = max(range(len(prompts)), key=prompt_lengths.__getitem__)
    bound = max(context_lengths) + max(prompt_lengths) + tokenizer.num_special_tokens_to_add(pair=True)
    actual = len(tokenizer(prompts[prompt_index][2], contexts[longest_index], truncation=False)["input_ids"])
    if actual > bound:
        raise ValueError("Tokenizer ciftli girdi uzunlugu beklenen siniri asti.")
    result = {"maximum_context_tokens": max(context_lengths), "maximum_question_tokens": max(prompt_lengths),
              "pair_upper_bound_tokens": bound, "training_limit": maximum, "truncation": False,
              "longest_context": {key: cases[longest_index][key] for key in ("dialogue_id", "message_id")}}
    if bound > maximum:
        raise ValueError(f"Tam konusma + secenek icin {bound} token gerek; {maximum} siniri asiliyor. Veri kirpilmadi. Ayrinti: {canonical(result)}")
    return result


def slot_support(cases):
    result = {}
    for field in TARGET_FIELDS:
        labels = Counter(case["targets"][field] for case in cases if case["targets"][field] is not None)
        result[field] = {"provided_messages": sum(labels.values()), "missing_messages": len(cases) - sum(labels.values()),
                         "label_counts": dict(sorted(labels.items()))}
    return result


def prepare_data(root, output):
    package = verify_package(root)
    schema, fields, catalog, services = load_schema(root)
    dialogues = load_training_dialogues(root, fields, services)
    training, validation = split_dialogues(dialogues)
    train_cases, validation_cases = make_cases(training), make_cases(validation)
    if len(train_cases) + len(validation_cases) != 3211:
        raise ValueError("Beklenen 3211 kullanici mesaji korunamadi.")
    identity = {
        "data_format": 1, "model_id": MODEL_ID, "revision": REVISION,
        "seed": SEED, "targets": list(TARGET_FIELDS),
        "source_train_sha256": file_hash(root / "data/train.jsonl"),
        "source_test_sha256": file_hash(root / "data/test.jsonl"),
        "schema_sha256": file_hash(root / "data/schema/slots.json"),
        "catalog_sha256": file_hash(root / "data/schema/catalog.json"),
        "preparer_sha256": file_hash(Path(__file__)),
    }
    output.mkdir(parents=True, exist_ok=True)
    old_manifest = output / "prepared_manifest.json"
    if old_manifest.is_file() and read_json(old_manifest)["identity"] != identity:
        raise ValueError("Bu hazirlik klasoru farkli model/veri/koda ait. Mevcut dosyalar degistirilmedi.")
    split = {"training_dialogue_ids": [d["dialogue_id"] for d in training],
             "validation_dialogue_ids": [d["dialogue_id"] for d in validation]}
    audit = {
        "training_dialogues": len(training), "validation_dialogues": len(validation),
        "training_user_messages": len(train_cases), "validation_user_messages": len(validation_cases),
        "enum_fields": list(ENUM_FIELDS), "catalog_fields": ["known_service"],
        "excluded_free_text_fields": list(OPEN_FIELDS),
        "schema_fields": len(fields), "catalog_entries": len(services),
        "training_support": slot_support(train_cases), "validation_support": slot_support(validation_cases),
        "warnings": [],
        "notes": [
            "Only user turns create training cases; preceding assistant text remains in history.",
            "Histories contain only message_id, role, text. Target annotations are separate.",
            "Null targets mean absent in the source state, not unknown and not false.",
            "Original evidence stays in source data; evidence generation is outside this classifier stage.",
            "Validation uses held-out training dialogues. No test labels select the split or training inputs.",
            "Four free-text fields remain outside this classifier; this stage does not complete their quality target.",
        ],
    }
    for field in TARGET_FIELDS:
        a, b = audit["training_support"][field], audit["validation_support"][field]
        if a["provided_messages"] < 50:
            audit["warnings"].append(f"{field}: egitimde yalnizca {a['provided_messages']} dolu mesaj var.")
        if b["provided_messages"] == 0:
            audit["warnings"].append(f"{field}: dogrulamada dolu ornek yok; bu alanin kalitesi buradan kanitlanamaz.")
    for name, cases in (("train_cases.jsonl", train_cases), ("validation_cases.jsonl", validation_cases)):
        path = output / name
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text("".join(canonical(case) + "\n" for case in cases), encoding="utf-8")
        temporary.replace(path)
    write_json(output / "split.json", split)
    tasks = build_tasks(fields, services)
    write_json(output / "tasks.json", tasks)
    write_json(output / "data_audit.json", audit)
    write_json(old_manifest, {"identity": identity,
        "checks": {"source_validated": True, "tokenizer_checked": False}, "files_sha256": {
        name: file_hash(output / name) for name in ("train_cases.jsonl", "validation_cases.jsonl", "split.json", "tasks.json", "data_audit.json")
    }})
    return audit, train_cases + validation_cases, tasks


def tokenizer_check(root, cases, tasks, output):
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    snapshot = Path(snapshot_download(
        repo_id=MODEL_ID, revision=REVISION, token=False,
        allow_patterns=["student/config.json", "student/tokenizer.json", "student/tokenizer_config.json"],
    ))
    directory = snapshot / "student"
    if file_hash(directory / "tokenizer.json") != TOKENIZER_SHA256:
        raise ValueError("Tokenizer dosyasinin SHA256 degeri resmi sabit surumle eslesmiyor.")
    configuration = read_json(directory / "config.json")
    if configuration.get("model_type") != "modernbert" or configuration.get("architectures") != ["ModernBertForSequenceClassification"]:
        raise ValueError("Beklenen Open-jev ModernBERT siniflandirici yapisi bulunamadi.")
    if len(configuration.get("id2label", {})) != 1 or configuration.get("max_position_embeddings", 0) < 1024:
        raise ValueError("Modelin karar basi veya konum siniri beklenenden farkli.")
    tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
    result = length_audit(cases, tasks, tokenizer, 1024)
    result.update({"model_id": MODEL_ID, "revision": REVISION,
                   "expected_base_weight_sha256": WEIGHT_SHA256, "tokenizer_sha256": TOKENIZER_SHA256,
                   "architecture_position_limit": configuration["max_position_embeddings"],
                   "source_pretraining_window": 512,
                   "note": "Our intended 1024-token fine-tuning input preserves full histories. Model architecture supports it; accuracy is not assumed from the position limit."})
    write_json(output / "tokenizer_audit.json", result)
    prepared = read_json(output / "prepared_manifest.json")
    prepared["checks"]["tokenizer_checked"] = True
    prepared["files_sha256"]["tokenizer_audit.json"] = file_hash(output / "tokenizer_audit.json")
    write_json(output / "prepared_manifest.json", prepared)
    return result


def main():
    output = Path("/content/drive/MyDrive/autoservice_colab/openjev_run_v1/prepared")
    audit, cases, tasks = prepare_data(ROOT, output)
    print("SOURCE_LABELS_VALIDATED", flush=True)
    print(f"Egitim: {audit['training_dialogues']} diyalog, {audit['training_user_messages']} kullanici mesaji.", flush=True)
    print(f"Dogrulama: {audit['validation_dialogues']} diyalog, {audit['validation_user_messages']} kullanici mesaji.", flush=True)
    print(f"Hedef: {len(TARGET_FIELDS)} alan; serbest metin alanlari bu siniflandiriciya dahil degil.", flush=True)
    for warning in audit["warnings"]:
        print("DATA_WARNING:", warning, flush=True)
    result = tokenizer_check(ROOT, cases, tasks, output)
    print("PINNED_TOKENIZER_OK", flush=True)
    print("Tam girdi icin token ust siniri:", result["pair_upper_bound_tokens"], flush=True)
    print("OPENJEV_DATA_READY", flush=True)
    print("Hazirlik sonuclari:", output, flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print("PREPARATION_ERROR:", exc, flush=True)
        raise SystemExit(1)
