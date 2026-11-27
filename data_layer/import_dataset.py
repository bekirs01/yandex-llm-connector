"""Import the autoservice dataset into the local Postgres database.

The import is repeatable: primary keys are the original ids and a second run
updates those rows instead of inserting duplicates. A dry run loads the rows
and then rolls the transaction back.

This command does not connect to a hosted Supabase project. Hosted import
requires an explicit automotive-assistant project configuration that is not
present in this repository.

Example:
    python data_layer/import_dataset.py --dry-run
    python data_layer/import_dataset.py --apply
    python data_layer/import_dataset.py --prove
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_layer.validate_dataset import DATASET, HOLDOUT_PATH, validate

SOCKET_DIR = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", "/tmp/autoservice-pg")
PORT = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", "54332")
USER = os.environ.get("AUTOSERVICE_LOCAL_PGUSER", "autoservice_owner")
DATABASE = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", "autoservice_assistant")
PSQL = os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")
RESULTS = ROOT / "benchmark" / "results"
MISSING_HOSTED = (
    "Hosted import was not run. There is no SUPABASE_URL, no database URL, "
    "and no linked Supabase project explicitly named for this automotive "
    "assistant. AUTOSERVICE_HOSTED_PROJECT is unset."
)


def psql_base() -> list[str]:
    return [
        PSQL,
        "-h", SOCKET_DIR,
        "-p", PORT,
        "-U", USER,
        "-d", DATABASE,
        "-v", "ON_ERROR_STOP=1",
        "-X",
        "-q",
    ]


def run_sql(script: str) -> str:
    if any(marker in script for marker in ("supabase.co", "supabase.com")):
        raise SystemExit(MISSING_HOSTED)
    completed = subprocess.run(
        psql_base() + ["-f", "-"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        raise SystemExit(message or f"psql exited {completed.returncode}")
    return completed.stdout


def load_dialogues(report: dict) -> list[dict]:
    invalid = set(report["invalid_train_dialogue_ids"])
    dialogues = []
    for split in ("train", "test"):
        with (DATASET / f"{split}.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                dialogue = json.loads(line)
                dialogue["split"] = split
                dialogue["structurally_valid"] = dialogue["dialogue_id"] not in invalid
                dialogues.append(dialogue)
    return dialogues


def quote_ident_rows() -> tuple[list[list[object]], list[list[object]], list[list[object]], list[list[object]], list[list[object]], list[list[object]]]:
    report = validate()
    if report["manifest"]["status"] != "passed":
        raise SystemExit("manifest validation failed; import aborted")
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    quality = json.loads((DATASET / "quality_report.json").read_text(encoding="utf-8"))
    catalog = json.loads((DATASET / "schema" / "catalog.json").read_text(encoding="utf-8"))
    slots_doc = json.loads((DATASET / "schema" / "slots.json").read_text(encoding="utf-8"))
    holdout = json.loads(HOLDOUT_PATH.read_text(encoding="utf-8"))
    review = quality["annotation_review"]
    metadata = [[
        manifest["dataset_version"],
        manifest["schema_version"],
        manifest["language"],
        manifest["created_at"],
        manifest["generation_service"],
        manifest["generation_model"],
        manifest["annotation_method"],
        manifest["review_method"],
        manifest["generation_prompt_version"],
        manifest["scenario_seed"],
        pg_bool(bool(manifest["expert_approved"])),
        pg_bool(bool(manifest["test_frozen_after_expert_approval"])),
        int(review["human_expert_reviewed"]),
        json.dumps(manifest["files_sha256"], ensure_ascii=False),
        report["retrieval_pool"]["eligible"],
    ]]
    services = [[
        item["id"],
        item["source_title"],
        item["source_section"],
        item["inherits"],
        json.dumps(item["aliases"], ensure_ascii=False),
        json.dumps(item["capabilities"], ensure_ascii=False),
        json.dumps(item["required_information"], ensure_ascii=False),
        item["selection"],
        catalog["schema_version"],
    ] for item in catalog["results"]]
    slots = [[
        slot["id"],
        position,
        slot["purpose"],
        slot["applies_when"],
        json.dumps(slot["values"], ensure_ascii=False),
        slot["source"],
        slot["question"],
        pg_bool(bool(slot["required"])),
        slot["missing_policy"],
        slots_doc["version"],
    ] for position, slot in enumerate(slots_doc["slots"], start=1)]
    dialogues = load_dialogues(report)
    dialogue_rows = [[
        dialogue["dialogue_id"],
        dialogue["split"],
        dialogue["language"],
        dialogue["schema_version"],
        pg_bool(dialogue["structurally_valid"]),
    ] for dialogue in dialogues]
    turn_rows = []
    evidence_rows = []
    for dialogue in dialogues:
        for index, turn in enumerate(dialogue["turns"], start=1):
            turn_rows.append([
                dialogue["dialogue_id"],
                turn["message_id"],
                index,
                turn["role"],
                turn["text"],
                json.dumps(turn["slots_after_message"], ensure_ascii=False),
            ])
            for entry in turn["evidence"]:
                evidence_rows.append([
                    dialogue["dialogue_id"],
                    turn["message_id"],
                    entry["slot"],
                    entry["raw_text"],
                    entry["kind"],
                    entry["time_scope"],
                    entry["supersedes"] if entry["supersedes"] is not None else "",
                    entry["interpretation"],
                ])
    holdout_rows = [[
        item["dialogue_id"],
        item["category"],
        item["reason"],
        pg_bool(bool(item["pinned"])),
        holdout["selection_version"],
    ] for item in holdout["dialogues"]]
    return metadata, services, slots, dialogue_rows, turn_rows, evidence_rows, holdout_rows, report


def merge_sql() -> str:
    return """
insert into autoservice.source_metadata (
  dataset_version, schema_version, language, source_created_at, generation_service,
  generation_model, annotation_method, review_method, generation_prompt_version,
  scenario_seed, expert_approved, test_frozen_after_expert_approval,
  human_expert_reviewed, file_hashes, retrieval_eligible_count
)
select
  dataset_version, schema_version, language, source_created_at::timestamptz,
  generation_service, generation_model, annotation_method, review_method,
  generation_prompt_version, scenario_seed, expert_approved,
  test_frozen_after_expert_approval, human_expert_reviewed, file_hashes::jsonb,
  retrieval_eligible_count
from staging_source
on conflict (dataset_version) do update set
  schema_version = excluded.schema_version,
  language = excluded.language,
  source_created_at = excluded.source_created_at,
  generation_service = excluded.generation_service,
  generation_model = excluded.generation_model,
  annotation_method = excluded.annotation_method,
  review_method = excluded.review_method,
  generation_prompt_version = excluded.generation_prompt_version,
  scenario_seed = excluded.scenario_seed,
  expert_approved = excluded.expert_approved,
  test_frozen_after_expert_approval = excluded.test_frozen_after_expert_approval,
  human_expert_reviewed = excluded.human_expert_reviewed,
  file_hashes = excluded.file_hashes,
  retrieval_eligible_count = excluded.retrieval_eligible_count,
  imported_at = now();

insert into autoservice.services (
  service_id, source_title, source_section, inherits, aliases, capabilities,
  required_information, selection, catalog_schema_version
)
select
  service_id, source_title, source_section, inherits, aliases::jsonb,
  capabilities::jsonb, required_information::jsonb, selection, catalog_schema_version
from staging_services
on conflict (service_id) do update set
  source_title = excluded.source_title,
  source_section = excluded.source_section,
  inherits = excluded.inherits,
  aliases = excluded.aliases,
  capabilities = excluded.capabilities,
  required_information = excluded.required_information,
  selection = excluded.selection,
  catalog_schema_version = excluded.catalog_schema_version;

insert into autoservice.slot_definitions (
  slot_id, position, purpose, applies_when, allowed_values, source, question,
  required, missing_policy, schema_version
)
select
  slot_id, position, purpose, applies_when, allowed_values::jsonb, source, question,
  required, missing_policy, schema_version
from staging_slots
on conflict (slot_id) do update set
  position = excluded.position,
  purpose = excluded.purpose,
  applies_when = excluded.applies_when,
  allowed_values = excluded.allowed_values,
  source = excluded.source,
  question = excluded.question,
  required = excluded.required,
  missing_policy = excluded.missing_policy,
  schema_version = excluded.schema_version;

insert into autoservice.dialogues (
  dialogue_id, split, language, schema_version, structurally_valid
)
select dialogue_id, split, language, schema_version, structurally_valid
from staging_dialogues
on conflict (dialogue_id) do update set
  split = excluded.split,
  language = excluded.language,
  schema_version = excluded.schema_version,
  structurally_valid = excluded.structurally_valid;

insert into autoservice.turns (
  dialogue_id, message_id, turn_index, role, body, slots_after_message
)
select dialogue_id, message_id, turn_index, role, body, slots_after_message::jsonb
from staging_turns
on conflict (dialogue_id, message_id) do update set
  turn_index = excluded.turn_index,
  role = excluded.role,
  body = excluded.body,
  slots_after_message = excluded.slots_after_message;

insert into autoservice.evidence (
  dialogue_id, message_id, slot_id, raw_text, kind, time_scope, supersedes, interpretation
)
select
  dialogue_id, message_id, slot_id, raw_text, kind, time_scope,
  nullif(supersedes, ''), interpretation
from staging_evidence
on conflict (dialogue_id, message_id, slot_id) do update set
  raw_text = excluded.raw_text,
  kind = excluded.kind,
  time_scope = excluded.time_scope,
  supersedes = excluded.supersedes,
  interpretation = excluded.interpretation;

insert into autoservice.dev_holdout (
  dialogue_id, category, reason, pinned, selection_version
)
select dialogue_id, category, reason, pinned, selection_version
from staging_holdout
on conflict (dialogue_id) do update set
  category = excluded.category,
  reason = excluded.reason,
  pinned = excluded.pinned,
  selection_version = excluded.selection_version;
"""


def staging_sql() -> str:
    return """
create temp table staging_source (
  dataset_version text, schema_version text, language text, source_created_at text,
  generation_service text, generation_model text, annotation_method text,
  review_method text, generation_prompt_version text, scenario_seed integer,
  expert_approved boolean, test_frozen_after_expert_approval boolean,
  human_expert_reviewed integer, file_hashes text, retrieval_eligible_count integer
) on commit drop;
create temp table staging_services (
  service_id text, source_title text, source_section text, inherits text,
  aliases text, capabilities text, required_information text, selection text,
  catalog_schema_version integer
) on commit drop;
create temp table staging_slots (
  slot_id text, position integer, purpose text, applies_when text,
  allowed_values text, source text, question text, required boolean,
  missing_policy text, schema_version text
) on commit drop;
create temp table staging_dialogues (
  dialogue_id text, split text, language text, schema_version text,
  structurally_valid boolean
) on commit drop;
create temp table staging_turns (
  dialogue_id text, message_id text, turn_index integer, role text,
  body text, slots_after_message text
) on commit drop;
create temp table staging_evidence (
  dialogue_id text, message_id text, slot_id text, raw_text text, kind text,
  time_scope text, supersedes text, interpretation text
) on commit drop;
create temp table staging_holdout (
  dialogue_id text, category text, reason text, pinned boolean,
  selection_version text
) on commit drop;
"""


def count_sql() -> str:
    return """
select 'services' as item, count(*) from autoservice.services
union all select 'slot_definitions', count(*) from autoservice.slot_definitions
union all select 'dialogues', count(*) from autoservice.dialogues
union all select 'train_dialogues', count(*) from autoservice.dialogues where split = 'train'
union all select 'test_dialogues', count(*) from autoservice.dialogues where split = 'test'
union all select 'turns', count(*) from autoservice.turns
union all select 'evidence', count(*) from autoservice.evidence
union all select 'dev_holdout', count(*) from autoservice.dev_holdout
union all select 'source_metadata', count(*) from autoservice.source_metadata
union all select 'retrieval_dialogues', count(*) from autoservice_api.dialogues
union all select 'retrieval_turns', count(*) from autoservice_api.turns
union all select 'retrieval_evidence', count(*) from autoservice_api.evidence
union all select 'retrieval_services', count(*) from autoservice_api.services;
"""


def pg_bool(value: bool) -> str:
    return "true" if value else "false"


def build_script(commit: bool) -> str:
    metadata, services, slots, dialogues, turns, evidence, holdout, _report = quote_ident_rows()
    parts = ["begin;\n", staging_sql()]

    def add_copy(table: str, columns: list[str], rows: list[list[object]]) -> None:
        parts.append(f"copy {table} ({', '.join(columns)}) from stdin with (format csv);\n")
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerows(rows)
        parts.append(buffer.getvalue())
        parts.append("\\.\n")

    add_copy("staging_source", [
        "dataset_version", "schema_version", "language", "source_created_at",
        "generation_service", "generation_model", "annotation_method", "review_method",
        "generation_prompt_version", "scenario_seed", "expert_approved",
        "test_frozen_after_expert_approval", "human_expert_reviewed", "file_hashes",
        "retrieval_eligible_count",
    ], metadata)
    add_copy("staging_services", [
        "service_id", "source_title", "source_section", "inherits", "aliases",
        "capabilities", "required_information", "selection", "catalog_schema_version",
    ], services)
    add_copy("staging_slots", [
        "slot_id", "position", "purpose", "applies_when", "allowed_values", "source",
        "question", "required", "missing_policy", "schema_version",
    ], slots)
    add_copy("staging_dialogues", [
        "dialogue_id", "split", "language", "schema_version", "structurally_valid",
    ], dialogues)
    add_copy("staging_turns", [
        "dialogue_id", "message_id", "turn_index", "role", "body", "slots_after_message",
    ], turns)
    add_copy("staging_evidence", [
        "dialogue_id", "message_id", "slot_id", "raw_text", "kind", "time_scope",
        "supersedes", "interpretation",
    ], evidence)
    add_copy("staging_holdout", [
        "dialogue_id", "category", "reason", "pinned", "selection_version",
    ], holdout)
    parts.append(merge_sql())
    parts.append(count_sql())
    parts.append("commit;\n" if commit else "rollback;\n")
    return "".join(parts)


def parse_counts(output: str) -> dict[str, int]:
    counts = {}
    for line in output.splitlines():
        if "|" not in line:
            continue
        item, raw = (part.strip() for part in line.split("|", 1))
        if item and raw.isdigit():
            counts[item] = int(raw)
    return counts


def prove() -> dict:
    holdout = json.loads(HOLDOUT_PATH.read_text(encoding="utf-8"))
    dev_ids = holdout["dialogue_ids"]
    if len(dev_ids) != 40 or any(not item.startswith("train_") for item in dev_ids):
        raise SystemExit("dev holdout is not the expected 40 training ids")
    dev_sql = ", ".join("'" + item.replace("'", "") + "'" for item in dev_ids)
    safe_runtime = f"""
create temp table probe_hidden (dialogue_id text);
insert into probe_hidden
select dialogue_id from autoservice.dialogues where split = 'test' limit 1;
grant select on probe_hidden to autoservice_runtime;
\\pset format unaligned
\\pset tuples_only on
set role autoservice_runtime;
select 'retrieval_dialogues|' || count(*)::text from autoservice_api.dialogues;
select 'retrieval_services|' || count(*)::text from autoservice_api.services;
select 'retrieval_slots|' || count(*)::text from autoservice_api.slot_definitions;
select 'retrieval_turns|' || count(*)::text from autoservice_api.turns;
select 'retrieval_evidence|' || count(*)::text from autoservice_api.evidence;
select 'test_prefix|' || count(*)::text from autoservice_api.dialogues where dialogue_id like 'test_%';
select 'dev_ids|' || count(*)::text from autoservice_api.dialogues where dialogue_id in ({dev_sql});
select 'specific_hidden|' || count(*)::text
from autoservice_api.dialogues
where dialogue_id in (select dialogue_id from probe_hidden);
select 'base_dialogues|' || count(*)::text from autoservice.dialogues;
"""
    completed = subprocess.run(
        psql_base() + ["-f", "-"],
        input=safe_runtime,
        text=True,
        capture_output=True,
        check=False,
    )
    combined = completed.stdout + "\n" + completed.stderr
    values = {}
    for line in completed.stdout.splitlines():
        if "|" in line:
            key, raw = line.split("|", 1)
            if raw.strip().isdigit():
                values[key.strip()] = int(raw.strip())
    base_denied = "permission denied" in combined.lower()
    holdout_probe = subprocess.run(
        psql_base() + ["-f", "-"],
        input=(
            "set role autoservice_runtime;\n"
            "select count(*) from autoservice.dev_holdout;\n"
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    holdout_denied = "permission denied" in (holdout_probe.stderr + holdout_probe.stdout).lower()
    fresh = subprocess.run(
        [
            PSQL, "-h", SOCKET_DIR, "-p", PORT, "-U", "autoservice_runtime",
            "-d", DATABASE, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c",
            "select current_user || '|' || count(*)::text from autoservice_api.dialogues;",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    fresh_line = next((line.strip() for line in fresh.stdout.splitlines() if "|" in line), "")
    proof = {
        "scope": "local",
        "hosted": False,
        "hosted_status": MISSING_HOSTED,
        "runtime_role": "autoservice_runtime",
        "runtime_connection_user": fresh_line.split("|", 1)[0] if "|" in fresh_line else None,
        "runtime_connection_dialogues": int(fresh_line.split("|", 1)[1]) if "|" in fresh_line and fresh_line.split("|", 1)[1].isdigit() else None,
        "retrieval_dialogues": values.get("retrieval_dialogues"),
        "retrieval_services": values.get("retrieval_services"),
        "retrieval_slots": values.get("retrieval_slots"),
        "retrieval_turns": values.get("retrieval_turns"),
        "retrieval_evidence": values.get("retrieval_evidence"),
        "test_prefix_visible": values.get("test_prefix"),
        "specific_hidden_visible": values.get("specific_hidden"),
        "dev_ids_visible": values.get("dev_ids"),
        "base_table_permission_denied": base_denied,
        "dev_holdout_permission_denied": holdout_denied,
    }
    proof["passed"] = (
        proof["runtime_connection_user"] == "autoservice_runtime"
        and proof["retrieval_dialogues"] == 960
        and proof["runtime_connection_dialogues"] == 960
        and proof["test_prefix_visible"] == 0
        and proof["specific_hidden_visible"] == 0
        and proof["dev_ids_visible"] == 0
        and proof["retrieval_services"] == 394
        and base_denied
        and holdout_denied
    )
    return proof


def write_counts(name: str, counts: dict[str, int]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prove", action="store_true")
    args = parser.parse_args()
    if not any((args.dry_run, args.apply, args.prove)):
        raise SystemExit("Choose --dry-run, --apply, or --prove")
    if args.dry_run or args.apply:
        output = run_sql(build_script(commit=args.apply))
        counts = parse_counts(output)
        label = "import_counts_apply.json" if args.apply else "import_counts_dry_run.json"
        payload = {"scope": "local", "committed": bool(args.apply), "counts": counts}
        write_counts(label, payload)
        print(json.dumps(payload, ensure_ascii=False))
    if args.prove:
        proof = prove()
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "retrieval_proof.json").write_text(
            json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({key: proof[key] for key in (
            "scope", "passed", "retrieval_dialogues", "test_prefix_visible",
            "dev_ids_visible", "base_table_permission_denied",
        )}, ensure_ascii=False))
        if not proof["passed"]:
            raise SystemExit("retrieval proof failed")


if __name__ == "__main__":
    main()
