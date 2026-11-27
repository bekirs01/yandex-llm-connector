-- Live customer question tree.
-- One completed exchange is stored once, separate from synthetic dialogues.
-- Retrieval views do not read these tables. Test and holdout rows stay hidden.
-- autoservice_runtime may call the API function and read the API view only.

create table autoservice.customer_exchanges (
  conversation_id text not null,
  request_id text not null,
  customer_message text not null,
  assistant_reply text not null,
  exchanged_at timestamptz not null,
  service_id text,
  category_id text,
  supplied_service_id text,
  supplied_category_id text,
  resolution text not null,
  primary key (conversation_id, request_id),
  foreign key (service_id) references autoservice.services (service_id),
  check (resolution in ('resolved', 'uncertain')),
  check (
    resolution <> 'resolved'
    or (service_id is not null and category_id is not null)
  ),
  check (
    resolution <> 'resolved'
    or (supplied_service_id is null and supplied_category_id is null)
  ),
  check (conversation_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  check (request_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  check (char_length(customer_message) between 1 and 4000),
  check (char_length(btrim(customer_message)) > 0),
  check (char_length(assistant_reply) between 1 and 8000),
  check (char_length(btrim(assistant_reply)) > 0),
  check (category_id is null or category_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  check (supplied_service_id is null or supplied_service_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  check (supplied_category_id is null or supplied_category_id ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

create index customer_exchanges_resolution_idx
  on autoservice.customer_exchanges (resolution, category_id, service_id);

create table autoservice.customer_exchange_intents (
  conversation_id text not null,
  request_id text not null,
  question_type text not null,
  primary key (conversation_id, request_id, question_type),
  foreign key (conversation_id, request_id)
    references autoservice.customer_exchanges (conversation_id, request_id),
  check (question_type ~ '^[a-z][a-z0-9-]{0,40}$')
);

revoke all on table autoservice.customer_exchanges from public;
revoke all on table autoservice.customer_exchange_intents from public;

alter table autoservice.customer_exchanges enable row level security;
alter table autoservice.customer_exchanges force row level security;
alter table autoservice.customer_exchange_intents enable row level security;
alter table autoservice.customer_exchange_intents force row level security;

-- No policy is granted to autoservice_runtime. The role also has no usage
-- on schema autoservice, matching the retrieval boundary.

create function autoservice_api.record_customer_exchange(
  p_conversation_id text,
  p_request_id text,
  p_customer_message text,
  p_assistant_reply text,
  p_exchanged_at timestamptz,
  p_service_id text,
  p_category_id text,
  p_question_types jsonb,
  p_uncertain boolean
) returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_conversation_id text;
  v_request_id text;
  v_question_types jsonb;
  v_input_service text;
  v_input_category text;
  v_types text[];
  v_all_known boolean;
  v_uncertain boolean;
  v_catalog_category text;
  v_resolution text;
  v_service_id text;
  v_category_id text;
  v_supplied_service text;
  v_supplied_category text;
  v_recorded boolean;
begin
  v_conversation_id := lower(btrim(coalesce(p_conversation_id, '')));
  v_request_id := lower(btrim(coalesce(p_request_id, '')));
  if v_conversation_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    raise exception 'invalid conversation_id' using errcode = '22023';
  end if;
  if v_request_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' then
    raise exception 'invalid request_id' using errcode = '22023';
  end if;
  if p_customer_message is null
     or char_length(p_customer_message) > 4000
     or char_length(btrim(p_customer_message)) = 0 then
    raise exception 'invalid customer_message' using errcode = '22023';
  end if;
  if p_assistant_reply is null
     or char_length(p_assistant_reply) > 8000
     or char_length(btrim(p_assistant_reply)) = 0 then
    raise exception 'invalid assistant_reply' using errcode = '22023';
  end if;
  if p_exchanged_at is null then
    raise exception 'invalid exchanged_at' using errcode = '22023';
  end if;

  v_input_service := nullif(btrim(coalesce(p_service_id, '')), '');
  v_input_category := nullif(btrim(coalesce(p_category_id, '')), '');
  if v_input_service is not null and (
    char_length(v_input_service) > 80
    or v_input_service !~ '^[a-z0-9]+(-[a-z0-9]+)*$'
  ) then
    raise exception 'invalid service_id' using errcode = '22023';
  end if;
  if v_input_category is not null and (
    char_length(v_input_category) > 80
    or v_input_category !~ '^[a-z0-9]+(-[a-z0-9]+)*$'
  ) then
    raise exception 'invalid category_id' using errcode = '22023';
  end if;

  v_question_types := coalesce(p_question_types, '[]'::jsonb);
  if jsonb_typeof(v_question_types) <> 'array' then
    raise exception 'invalid question_types' using errcode = '22023';
  end if;
  if exists (
    select 1
    from jsonb_array_elements(v_question_types) as item
    where jsonb_typeof(item) <> 'string'
  ) then
    raise exception 'invalid question_types' using errcode = '22023';
  end if;

  select coalesce(array_agg(distinct canonical order by canonical), array[]::text[])
  into v_types
  from (
    select case lower(btrim(item))
      when 'equipment-availability' then 'equipment'
      when 'equipment_availability' then 'equipment'
      else lower(btrim(item))
    end as canonical
    from jsonb_array_elements_text(v_question_types) as item
  ) normalized;

  if exists (
    select 1
    from unnest(v_types) as item
    where item !~ '^[a-z][a-z0-9-]{0,40}$'
  ) then
    raise exception 'invalid question_types' using errcode = '22023';
  end if;

  v_all_known := cardinality(v_types) > 0
    and not exists (
      select 1
      from unnest(v_types) as item
      where not (item = any (array[
        'availability', 'booking', 'diagnosis', 'equipment', 'hours', 'price', 'workshop'
      ]))
    );
  v_uncertain := coalesce(p_uncertain, false);
  v_catalog_category := null;
  if v_input_service is not null then
    select inherits
    into v_catalog_category
    from autoservice.services
    where service_id = v_input_service;
    if not found then
      v_catalog_category := null;
    end if;
  end if;

  if v_catalog_category is not null
     and v_all_known
     and not v_uncertain
     and (v_input_category is null or v_input_category = v_catalog_category)
  then
    v_resolution := 'resolved';
    v_service_id := v_input_service;
    v_category_id := v_catalog_category;
    v_supplied_service := null;
    v_supplied_category := null;
  else
    v_resolution := 'uncertain';
    if v_catalog_category is not null then
      v_service_id := v_input_service;
      v_category_id := v_catalog_category;
      v_supplied_service := null;
      v_supplied_category := case
        when v_input_category is not null and v_input_category <> v_catalog_category
          then v_input_category
        else null
      end;
    else
      v_service_id := null;
      v_category_id := null;
      v_supplied_service := v_input_service;
      v_supplied_category := v_input_category;
    end if;
  end if;

  v_recorded := false;
  insert into autoservice.customer_exchanges (
    conversation_id,
    request_id,
    customer_message,
    assistant_reply,
    exchanged_at,
    service_id,
    category_id,
    supplied_service_id,
    supplied_category_id,
    resolution
  ) values (
    v_conversation_id,
    v_request_id,
    p_customer_message,
    p_assistant_reply,
    p_exchanged_at,
    v_service_id,
    v_category_id,
    v_supplied_service,
    v_supplied_category,
    v_resolution
  )
  on conflict (conversation_id, request_id) do nothing
  returning true into v_recorded;

  if v_recorded is true then
    insert into autoservice.customer_exchange_intents (
      conversation_id, request_id, question_type
    )
    select v_conversation_id, v_request_id, item
    from unnest(v_types) as item;
  else
    v_recorded := false;
    select
      resolution,
      service_id,
      category_id,
      supplied_service_id,
      supplied_category_id
    into
      v_resolution,
      v_service_id,
      v_category_id,
      v_supplied_service,
      v_supplied_category
    from autoservice.customer_exchanges
    where conversation_id = v_conversation_id
      and request_id = v_request_id;
    select coalesce(array_agg(question_type order by question_type), array[]::text[])
    into v_types
    from autoservice.customer_exchange_intents
    where conversation_id = v_conversation_id
      and request_id = v_request_id;
  end if;

  return jsonb_build_object(
    'recorded', v_recorded,
    'conversation_id', v_conversation_id,
    'request_id', v_request_id,
    'resolution', v_resolution,
    'service_id', v_service_id,
    'category_id', v_category_id,
    'supplied_service_id', v_supplied_service,
    'supplied_category_id', v_supplied_category,
    'question_types', to_jsonb(v_types)
  );
end;
$function$;

revoke all on function autoservice_api.record_customer_exchange(
  text, text, text, text, timestamptz, text, text, jsonb, boolean
) from public;
grant execute on function autoservice_api.record_customer_exchange(
  text, text, text, text, timestamptz, text, text, jsonb, boolean
) to autoservice_runtime;

create view autoservice_api.customer_exchanges
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
  ) as question_types
from autoservice.customer_exchanges as exchanges
left join autoservice.services as services
  on services.service_id = exchanges.service_id;

revoke all on table autoservice_api.customer_exchanges from public;
grant select on table autoservice_api.customer_exchanges to autoservice_runtime;

comment on table autoservice.customer_exchanges is
  'One completed live customer exchange. Not a synthetic dialogue.';
comment on table autoservice.customer_exchange_intents is
  'Question types attached to one live exchange. A price-and-booking turn has two rows and one transcript.';
comment on function autoservice_api.record_customer_exchange(
  text, text, text, text, timestamptz, text, text, jsonb, boolean
) is
  'Inserts one completed exchange. The same conversation_id and request_id do not write again.';
comment on view autoservice_api.customer_exchanges is
  'Live customer exchanges for the question tree. Synthetic dialogues, the holdout, and the test split are not included.';
