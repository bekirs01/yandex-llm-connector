-- Additive link from saved feedback to the question tree, plus a separate
-- developer decision for training export. Customer exchanges are not rewritten.
-- A star click does not change prompts, retrieval, or the next reply.
-- autoservice_runtime may call the functions only. It still cannot list the
-- feedback or review tables directly.

create or replace view autoservice_api.customer_exchanges
with (security_barrier = true, security_invoker = false) as
select
  exchanges.conversation_id,
  exchanges.request_id,
  exchanges.customer_message,
  exchanges.assistant_reply,
  exchanges.exchanged_at,
  exchanges.service_id,
  services.source_title as service_title,
  exchanges.category_id,
  exchanges.supplied_service_id,
  exchanges.supplied_category_id,
  exchanges.resolution,
  coalesce(
    (
      select json_agg(intents.question_type order by intents.question_type)
      from autoservice.customer_exchange_intents as intents
      where intents.conversation_id = exchanges.conversation_id
        and intents.request_id = exchanges.request_id
    ),
    '[]'::json
  ) as question_types,
  feedback.stars,
  feedback.resolved
from autoservice.customer_exchanges as exchanges
left join autoservice.services as services
  on services.service_id = exchanges.service_id
left join autoservice.customer_exchange_feedback as feedback
  on feedback.conversation_id = exchanges.conversation_id
 and feedback.request_id = exchanges.request_id;

revoke all on table autoservice_api.customer_exchanges from public;
grant select on table autoservice_api.customer_exchanges to autoservice_runtime;

comment on view autoservice_api.customer_exchanges is
  'Live customer exchanges for the question tree, with the saved stars and resolved flag when a feedback row exists. No feedback row leaves both null. Aggregates are not stored here.';

create table autoservice.exchange_training_reviews (
  conversation_id text not null,
  request_id text not null,
  decision text not null,
  feedback_revision integer not null,
  stars smallint,
  resolved boolean,
  decided_at timestamptz not null default clock_timestamp(),
  primary key (conversation_id, request_id),
  foreign key (conversation_id, request_id)
    references autoservice.customer_exchanges (conversation_id, request_id),
  check (decision in ('approved', 'excluded')),
  check (feedback_revision >= 0),
  check (stars is null or stars between 1 and 5),
  check (conversation_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  check (request_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
);

revoke all on table autoservice.exchange_training_reviews from public;

alter table autoservice.exchange_training_reviews enable row level security;
alter table autoservice.exchange_training_reviews force row level security;

comment on table autoservice.exchange_training_reviews is
  'Developer decision for one exchange. Approval stores the feedback snapshot. A later change of stars or resolved reopens the example. This table is not a prompt, a retrieval document, or a model weight.';

create function autoservice_api.panel_revision()
returns text
language sql
security definer
stable
set search_path = ''
as $function$
  select concat_ws(
    '|',
    (select count(*)::text from autoservice.customer_exchanges),
    (select coalesce(max(exchanged_at)::text, '') from autoservice.customer_exchanges),
    (select count(*)::text from autoservice.customer_exchange_feedback),
    (select coalesce(max(updated_at)::text, '') from autoservice.customer_exchange_feedback),
    (select count(*)::text from autoservice.exchange_training_reviews),
    (select coalesce(max(decided_at)::text, '') from autoservice.exchange_training_reviews)
  );
$function$;

create function autoservice_api.read_training_reviews()
returns jsonb
language sql
security definer
stable
set search_path = ''
as $function$
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'conversation_id', reviews.conversation_id,
        'request_id', reviews.request_id,
        'decision', reviews.decision,
        'feedback_revision', reviews.feedback_revision,
        'stars', reviews.stars,
        'resolved', reviews.resolved
      )
    ),
    '[]'::jsonb
  )
  from autoservice.exchange_training_reviews as reviews;
$function$;

create function autoservice_api.save_training_review(
  p_conversation_id text,
  p_request_id text,
  p_decision text
) returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_conversation_id text;
  v_request_id text;
  v_stars smallint;
  v_resolved boolean;
  v_revision integer;
begin
  v_conversation_id := lower(btrim(coalesce(p_conversation_id, '')));
  v_request_id := lower(btrim(coalesce(p_request_id, '')));
  if v_conversation_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    raise exception 'invalid conversation_id' using errcode = '22023';
  end if;
  if v_request_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    raise exception 'invalid request_id' using errcode = '22023';
  end if;
  if p_decision is null or p_decision not in ('approved', 'excluded') then
    raise exception 'invalid decision' using errcode = '22023';
  end if;

  perform 1
  from autoservice.customer_exchanges
  where conversation_id = v_conversation_id
    and request_id = v_request_id
  for update;
  if not found then
    raise exception 'unknown exchange' using errcode = '22023';
  end if;

  select stars, resolved, revision
  into v_stars, v_resolved, v_revision
  from autoservice.customer_exchange_feedback
  where conversation_id = v_conversation_id
    and request_id = v_request_id
  for update;
  if not found or (v_stars is null and v_resolved is null) then
    raise exception 'feedback required' using errcode = '22023';
  end if;

  insert into autoservice.exchange_training_reviews (
    conversation_id, request_id, decision, feedback_revision, stars, resolved, decided_at
  ) values (
    v_conversation_id, v_request_id, p_decision, v_revision, v_stars, v_resolved, clock_timestamp()
  )
  on conflict (conversation_id, request_id) do update
  set decision = excluded.decision,
      feedback_revision = excluded.feedback_revision,
      stars = excluded.stars,
      resolved = excluded.resolved,
      decided_at = clock_timestamp();

  return jsonb_build_object(
    'conversation_id', v_conversation_id,
    'request_id', v_request_id,
    'decision', p_decision,
    'feedback_revision', v_revision,
    'stars', v_stars,
    'resolved', v_resolved
  );
end;
$function$;

revoke all on function autoservice_api.panel_revision() from public;
grant execute on function autoservice_api.panel_revision() to autoservice_runtime;

revoke all on function autoservice_api.read_training_reviews() from public;
grant execute on function autoservice_api.read_training_reviews() to autoservice_runtime;

revoke all on function autoservice_api.save_training_review(text, text, text) from public;
grant execute on function autoservice_api.save_training_review(text, text, text) to autoservice_runtime;

comment on function autoservice_api.panel_revision() is
  'One token for the open team panel. It changes when an exchange, a feedback row, or a training decision changes. It does not return transcripts.';
comment on function autoservice_api.read_training_reviews() is
  'Developer decisions only. Transcripts stay on the exchange view.';
comment on function autoservice_api.save_training_review(text, text, text) is
  'Stores an explicit approve or exclude decision and the feedback snapshot. It does not change the exchange or the live assistant.';
