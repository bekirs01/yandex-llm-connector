-- Automotive-assistant dataset.
-- All splits are stored. autoservice_runtime can read only the catalog,
-- slot definitions, and training dialogues that are structurally valid and
-- not in the reserved development holdout.

create schema autoservice;
create schema autoservice_api;

revoke all on schema autoservice from public;
revoke all on schema autoservice_api from public;

create role autoservice_runtime
  login
  nosuperuser
  nobypassrls
  nocreatedb
  nocreaterole
  noinherit
  noreplication;

create table autoservice.source_metadata (
  dataset_version text primary key,
  schema_version text not null,
  language text not null,
  source_created_at timestamptz not null,
  generation_service text not null,
  generation_model text not null,
  annotation_method text not null,
  review_method text not null,
  generation_prompt_version text not null,
  scenario_seed integer not null,
  expert_approved boolean not null,
  test_frozen_after_expert_approval boolean not null,
  human_expert_reviewed integer not null,
  file_hashes jsonb not null,
  retrieval_eligible_count integer not null,
  imported_at timestamptz not null default now()
);

create table autoservice.services (
  service_id text primary key,
  source_title text not null,
  source_section text not null,
  inherits text not null,
  aliases jsonb not null,
  capabilities jsonb not null,
  required_information jsonb not null,
  selection text not null,
  catalog_schema_version integer not null
);

create table autoservice.slot_definitions (
  slot_id text primary key,
  position integer not null unique check (position > 0),
  purpose text not null,
  applies_when text not null,
  allowed_values jsonb not null,
  source text not null,
  question text not null,
  required boolean not null,
  missing_policy text not null,
  schema_version text not null
);

create table autoservice.dialogues (
  dialogue_id text primary key,
  split text not null check (split in ('train', 'test')),
  language text not null,
  schema_version text not null,
  structurally_valid boolean not null,
  check (
    (split = 'train' and dialogue_id ~ '^train_[0-9]{6}$')
    or (split = 'test' and dialogue_id ~ '^test_[0-9]{6}$')
  )
);

create index dialogues_retrievable_idx
  on autoservice.dialogues (dialogue_id)
  where split = 'train' and structurally_valid;

create table autoservice.dev_holdout (
  dialogue_id text primary key references autoservice.dialogues (dialogue_id),
  category text not null,
  reason text not null,
  pinned boolean not null,
  selection_version text not null
);

create table autoservice.turns (
  dialogue_id text not null references autoservice.dialogues (dialogue_id),
  message_id text not null,
  turn_index integer not null check (turn_index > 0),
  role text not null check (role in ('user', 'assistant')),
  body text not null,
  slots_after_message jsonb not null,
  primary key (dialogue_id, message_id)
);

create index turns_dialogue_order_idx
  on autoservice.turns (dialogue_id, turn_index);

create table autoservice.evidence (
  dialogue_id text not null,
  message_id text not null,
  slot_id text not null references autoservice.slot_definitions (slot_id),
  raw_text text not null,
  kind text not null check (kind in (
    'observation', 'hypothesis', 'reported_diagnosis', 'service_request'
  )),
  time_scope text not null check (time_scope in ('past', 'current', 'unspecified')),
  supersedes text,
  interpretation text not null,
  primary key (dialogue_id, message_id, slot_id),
  foreign key (dialogue_id, message_id)
    references autoservice.turns (dialogue_id, message_id),
  foreign key (dialogue_id, supersedes)
    references autoservice.turns (dialogue_id, message_id)
);

create index evidence_supersedes_idx
  on autoservice.evidence (dialogue_id, supersedes)
  where supersedes is not null;

create function autoservice.dialogue_is_retrievable(
  target_dialogue_id text,
  target_split text,
  target_valid boolean
) returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select target_split = 'train'
    and target_valid
    and not exists (
      select 1
      from autoservice.dev_holdout
      where dialogue_id = target_dialogue_id
    );
$$;

revoke all on function autoservice.dialogue_is_retrievable(text, text, boolean) from public;
grant execute on function autoservice.dialogue_is_retrievable(text, text, boolean) to autoservice_runtime;

create view autoservice_api.services
with (security_barrier = true, security_invoker = false) as
select
  service_id,
  source_title,
  source_section,
  inherits,
  aliases,
  capabilities,
  required_information,
  selection,
  catalog_schema_version
from autoservice.services;

create view autoservice_api.slot_definitions
with (security_barrier = true, security_invoker = false) as
select
  slot_id,
  position,
  purpose,
  applies_when,
  allowed_values,
  source,
  question,
  required,
  missing_policy,
  schema_version
from autoservice.slot_definitions;

create view autoservice_api.dialogues
with (security_barrier = true, security_invoker = false) as
select dialogue_id, language, schema_version
from autoservice.dialogues
where autoservice.dialogue_is_retrievable(dialogue_id, split, structurally_valid);

create view autoservice_api.turns
with (security_barrier = true, security_invoker = false) as
select
  turns.dialogue_id,
  turns.message_id,
  turns.turn_index,
  turns.role,
  turns.body,
  turns.slots_after_message
from autoservice.turns
where exists (
  select 1
  from autoservice_api.dialogues
  where dialogues.dialogue_id = turns.dialogue_id
);

create view autoservice_api.evidence
with (security_barrier = true, security_invoker = false) as
select
  evidence.dialogue_id,
  evidence.message_id,
  evidence.slot_id,
  evidence.raw_text,
  evidence.kind,
  evidence.time_scope,
  evidence.supersedes,
  evidence.interpretation
from autoservice.evidence
where exists (
  select 1
  from autoservice_api.dialogues
  where dialogues.dialogue_id = evidence.dialogue_id
);

grant usage on schema autoservice_api to autoservice_runtime;
grant select on
  autoservice_api.services,
  autoservice_api.slot_definitions,
  autoservice_api.dialogues,
  autoservice_api.turns,
  autoservice_api.evidence
to autoservice_runtime;

alter table autoservice.source_metadata enable row level security;
alter table autoservice.source_metadata force row level security;
alter table autoservice.services enable row level security;
alter table autoservice.services force row level security;
alter table autoservice.slot_definitions enable row level security;
alter table autoservice.slot_definitions force row level security;
alter table autoservice.dialogues enable row level security;
alter table autoservice.dialogues force row level security;
alter table autoservice.dev_holdout enable row level security;
alter table autoservice.dev_holdout force row level security;
alter table autoservice.turns enable row level security;
alter table autoservice.turns force row level security;
alter table autoservice.evidence enable row level security;
alter table autoservice.evidence force row level security;

create policy runtime_read_services on autoservice.services
  for select to autoservice_runtime
  using (true);

create policy runtime_read_slots on autoservice.slot_definitions
  for select to autoservice_runtime
  using (true);

create policy runtime_read_dialogues on autoservice.dialogues
  for select to autoservice_runtime
  using (autoservice.dialogue_is_retrievable(dialogue_id, split, structurally_valid));

create policy runtime_read_turns on autoservice.turns
  for select to autoservice_runtime
  using (autoservice.dialogue_is_retrievable(
    dialogue_id,
    (select split from autoservice.dialogues where dialogues.dialogue_id = turns.dialogue_id),
    (select structurally_valid from autoservice.dialogues where dialogues.dialogue_id = turns.dialogue_id)
  ));

create policy runtime_read_evidence on autoservice.evidence
  for select to autoservice_runtime
  using (autoservice.dialogue_is_retrievable(
    dialogue_id,
    (select split from autoservice.dialogues where dialogues.dialogue_id = evidence.dialogue_id),
    (select structurally_valid from autoservice.dialogues where dialogues.dialogue_id = evidence.dialogue_id)
  ));

comment on schema autoservice_api is
  'Retrieval interface for catalog data and eligible training dialogues only.';
comment on role autoservice_runtime is
  'Reads autoservice_api only. Development holdout and final test dialogues are excluded.';
