-- One editable feedback row for one completed live exchange.
-- The exchange itself is not rewritten. Unknown ids cannot insert a row.
-- autoservice_runtime may call the API functions only.
-- Future branch summaries reserve the names rating_count and average_stars.
-- This wave does not store those aggregates and does not change the question-tree read.

create table autoservice.customer_exchange_feedback (
  conversation_id text not null,
  request_id text not null,
  stars smallint,
  resolved boolean,
  revision integer not null,
  updated_at timestamptz not null default clock_timestamp(),
  primary key (conversation_id, request_id),
  foreign key (conversation_id, request_id)
    references autoservice.customer_exchanges (conversation_id, request_id),
  check (stars is null or stars between 1 and 5),
  check (revision >= 1),
  check (conversation_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  check (request_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
);

revoke all on table autoservice.customer_exchange_feedback from public;

alter table autoservice.customer_exchange_feedback enable row level security;
alter table autoservice.customer_exchange_feedback force row level security;

comment on table autoservice.customer_exchange_feedback is
  'One editable feedback row per completed live exchange. No row means unrated. resolved null is unanswered and is distinct from false (Нет). Future branch summaries reserve rating_count and average_stars; those aggregates are not stored here.';

create function autoservice_api.read_exchange_feedback(
  p_conversation_id text,
  p_request_id text
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

  perform 1
  from autoservice.customer_exchanges
  where conversation_id = v_conversation_id
    and request_id = v_request_id;
  if not found then
    raise exception 'unknown exchange' using errcode = '22023';
  end if;

  select stars, resolved, revision
  into v_stars, v_resolved, v_revision
  from autoservice.customer_exchange_feedback
  where conversation_id = v_conversation_id
    and request_id = v_request_id;

  if not found then
    return jsonb_build_object(
      'conversation_id', v_conversation_id,
      'request_id', v_request_id,
      'revision', 0
    );
  end if;

  return jsonb_build_object(
    'conversation_id', v_conversation_id,
    'request_id', v_request_id,
    'revision', v_revision,
    'feedback', jsonb_build_object(
      'stars', v_stars,
      'resolved', v_resolved
    )
  );
end;
$function$;

create function autoservice_api.save_exchange_feedback(
  p_conversation_id text,
  p_request_id text,
  p_stars integer,
  p_resolved boolean,
  p_revision integer
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
  v_applied boolean;
begin
  v_conversation_id := lower(btrim(coalesce(p_conversation_id, '')));
  v_request_id := lower(btrim(coalesce(p_request_id, '')));
  if v_conversation_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    raise exception 'invalid conversation_id' using errcode = '22023';
  end if;
  if v_request_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    raise exception 'invalid request_id' using errcode = '22023';
  end if;
  if p_stars is not null and (p_stars < 1 or p_stars > 5) then
    raise exception 'invalid stars' using errcode = '22023';
  end if;
  if p_revision is null or p_revision < 1 or p_revision > 1000000000 then
    raise exception 'invalid revision' using errcode = '22023';
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

  if not found then
    if p_stars is null and p_resolved is null then
      return jsonb_build_object(
        'applied', true,
        'conversation_id', v_conversation_id,
        'request_id', v_request_id,
        'revision', 0
      );
    end if;
    insert into autoservice.customer_exchange_feedback (
      conversation_id, request_id, stars, resolved, revision, updated_at
    ) values (
      v_conversation_id, v_request_id, p_stars::smallint, p_resolved, p_revision, clock_timestamp()
    );
    return jsonb_build_object(
      'applied', true,
      'conversation_id', v_conversation_id,
      'request_id', v_request_id,
      'revision', p_revision,
      'feedback', jsonb_build_object('stars', p_stars, 'resolved', p_resolved)
    );
  end if;

  v_applied := false;
  if p_revision > v_revision then
    if p_stars is null and p_resolved is null then
      delete from autoservice.customer_exchange_feedback
      where conversation_id = v_conversation_id
        and request_id = v_request_id;
      return jsonb_build_object(
        'applied', true,
        'conversation_id', v_conversation_id,
        'request_id', v_request_id,
        'revision', p_revision
      );
    end if;
    update autoservice.customer_exchange_feedback
    set stars = p_stars::smallint,
        resolved = p_resolved,
        revision = p_revision,
        updated_at = clock_timestamp()
    where conversation_id = v_conversation_id
      and request_id = v_request_id
      and revision = v_revision;
    v_stars := p_stars::smallint;
    v_resolved := p_resolved;
    v_revision := p_revision;
    v_applied := true;
  elsif p_revision = v_revision
    and v_stars is not distinct from p_stars::smallint
    and v_resolved is not distinct from p_resolved then
    v_applied := true;
  end if;

  if v_stars is null and v_resolved is null then
    return jsonb_build_object(
      'applied', v_applied,
      'conversation_id', v_conversation_id,
      'request_id', v_request_id,
      'revision', v_revision
    );
  end if;

  return jsonb_build_object(
    'applied', v_applied,
    'conversation_id', v_conversation_id,
    'request_id', v_request_id,
    'revision', v_revision,
    'feedback', jsonb_build_object('stars', v_stars, 'resolved', v_resolved)
  );
end;
$function$;

revoke all on function autoservice_api.read_exchange_feedback(text, text) from public;
grant execute on function autoservice_api.read_exchange_feedback(text, text) to autoservice_runtime;

revoke all on function autoservice_api.save_exchange_feedback(text, text, integer, boolean, integer) from public;
grant execute on function autoservice_api.save_exchange_feedback(text, text, integer, boolean, integer) to autoservice_runtime;

comment on function autoservice_api.read_exchange_feedback(text, text) is
  'Reads feedback for one live exchange. No row means unrated. Does not list transcripts or ratings.';
comment on function autoservice_api.save_exchange_feedback(text, text, integer, boolean, integer) is
  'Inserts or updates the single feedback row for one existing exchange. A lower revision does not overwrite. The same revision and values are idempotent.';
