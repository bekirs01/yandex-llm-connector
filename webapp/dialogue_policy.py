"""Turn one slot extraction into a short Russian customer reply.

The extractor result is a single object:

- ``slots_after_message``: accumulated slot state, string keys and string values.
- ``evidence``: facts added or corrected by the current turn. Each item has
  exactly ``slot``, ``message_id``, ``raw_text``, ``kind``, ``time_scope``,
  ``supersedes``, and ``interpretation``.

``plan_reply`` does not call a model, read model files, or talk to the chat
handler. It returns the customer text plus metadata a later integrator can
store. Customer-facing strings are Russian. Identifiers and metadata stay
English.

Optional ``prior_slots`` is the previous ``slots_after_message``. It is used
only to phrase a correction. Optional ``asked_slots`` lists slot ids already
asked in this conversation; those questions are not asked again.

The reply acknowledges what the customer said, asks at most one useful
question, and withholds diagnosis, repair, workshop, price, availability, and
booking. An observation is a reported fact. A hypothesis or ``user_guess`` is
an assumption. A reported diagnosis is an unconfirmed claim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping, Sequence


EVIDENCE_FIELDS = frozenset({
    "slot",
    "message_id",
    "raw_text",
    "kind",
    "time_scope",
    "supersedes",
    "interpretation",
})
KINDS = frozenset({
    "observation",
    "hypothesis",
    "reported_diagnosis",
    "service_request",
})
TIME_SCOPES = frozenset({"past", "current", "unspecified"})
WITHHELD = (
    "diagnosis",
    "repair",
    "workshop",
    "price",
    "availability",
    "booking",
)
_NON_ANSWERS = frozenset({
    "unknown",
    "conflicting",
    "unspecified",
    "ambiguous_candidates",
    "multiple",
})
_TYPE_ONLY = frozenset({
    "free_text",
    "make_model_year_free_text",
    "catalog_id",
    "city_district_free_text",
    "document_data",
    "known_specification",
    "confirm_with_shop",
})
_SLUG_RE = re.compile(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+$")

# Customer-facing Russian for schema tokens. These are not diagnoses.
_ENUM_RU = {
    "powertrain": {
        "petrol": "бензин",
        "diesel": "дизель",
        "gas": "газ",
        "hybrid": "гибрид",
        "electric": "электромобиль",
    },
    "current_state": {
        "present": "это есть сейчас",
        "disappeared": "сейчас этого уже нет",
        "intermittent": "проявляется не всегда",
        "immobile": "сама сейчас не едет",
    },
    "event": {
        "water": "после воды",
        "collision": "после удара",
        "refuel": "после заправки",
        "after_repair": "после ремонта",
    },
    "observed_context": {
        "braking": "при торможении",
        "moving": "на ходу",
        "steering": "при повороте",
        "stationary": "на месте",
    },
    "gearbox": {
        "manual": "механика",
        "automatic_unspecified": "автомат",
        "automatic": "автомат",
        "cvt": "вариатор",
        "robot": "робот",
    },
    "location_format": {
        "onsite": "выезд к машине",
        "workshop": "сервис",
        "transport": "перевозка",
        "no_preference": "без предпочтения по формату",
    },
    "previous_diagnosis": {
        "reported_conclusion": "заключение сервиса",
        "user_guess": "ваше предположение",
        "document_quote": "цитата из документа",
        "none_reported": "диагноз не называли",
    },
}

# Customer-facing Russian questions. At most one is used.
_QUESTIONS = {
    "intent": "Что нужно: выполнить конкретную работу или разобраться, что случилось?",
    "main_symptom": "Что именно происходит с машиной?",
    "known_service": "Какую именно работу нужно сделать?",
    "observed_context": "Когда это заметно: при торможении, на ходу, при повороте или на месте?",
    "location_format": "Нужен выезд к машине или подбор сервиса?",
    "search_area": "В каком городе или районе искать?",
    "gearbox": "Какая коробка: механика, автомат, вариатор или робот?",
    "powertrain": "Какая машина по типу: бензин, дизель, гибрид, электромобиль или газ?",
    "vehicle": "Какая машина: марка, модель и примерно год?",
    "affected_item": "Что именно установить, проверить или привести в порядок?",
    "event": "После чего это началось?",
    "current_state": "Это происходит сейчас или уже прошло?",
    "several": "С чего удобнее начать?",
    "rephrase": (
        "Напишите, пожалуйста, своими словами: что происходит с машиной "
        "или какую работу нужно сделать?"
    ),
}
_CONFLICT_QUESTION = {
    "vehicle": "Какая машина верная?",
    "powertrain": "Какой тип двигателя верный?",
    "main_symptom": "Что из этого происходит на самом деле?",
    "known_service": "Какую работу считать актуальной?",
    "observed_context": "В какой ситуации это заметно на самом деле?",
    "event": "После чего это было на самом деле?",
    "search_area": "Какое место верное?",
    "gearbox": "Какая коробка верная?",
    "location_format": "Какой формат помощи верный?",
}
_CONFLICT_TOPIC = {
    "vehicle": "По машине",
    "powertrain": "По типу двигателя",
    "main_symptom": "По жалобе",
    "known_service": "По работе",
    "observed_context": "По ситуации",
    "event": "По обстоятельству",
    "search_area": "По месту",
    "gearbox": "По коробке",
    "location_format": "По формату помощи",
}
_SLOT_NOUN = {
    "main_symptom": "жалоба",
    "known_service": "работа",
    "vehicle": "машина",
    "powertrain": "тип",
    "gearbox": "коробка",
    "event": "обстоятельство",
    "search_area": "место",
    "observed_context": "ситуация",
    "current_state": "состояние",
    "affected_item": "предмет",
    "location_format": "формат",
    "previous_diagnosis": "заключение",
    "fitment": "параметры",
}
_CONFLICT_ORDER = (
    "vehicle",
    "main_symptom",
    "known_service",
    "powertrain",
    "gearbox",
    "observed_context",
    "location_format",
    "event",
    "search_area",
    "current_state",
)
_QUOTE_SLOTS = frozenset({
    "main_symptom",
    "known_service",
    "affected_item",
    "fitment",
})
_PLAIN_SLOTS = frozenset({"vehicle", "search_area"})
_NOISE_HINTS = (
    "шум", "стук", "стуч", "скрип", "вибра", "гул", "грем", "свист", "скреж", "бьет", "бьёт",
)
_GEARBOX_HINTS = ("коробк", "акпп", "мкпп", "вариатор", "передач", "сцеплен")
_POWERTRAIN_HINTS = (
    "не заводит", "заводит", "заглох", "заряд", "батаре", "двигател", "мотор",
    "масло", "топлив", "бензин", "дизел", "гибрид", "электро", "климат", "печк",
    "кондицион", "грм", "свеч",
)
_POWERTRAIN_IRRELEVANT = (
    "колод", "тормоз", "ступиц", "амортиз", "сайлент", "развал", "шин", "колес",
    "стекл", "фаркоп",
)
_IMMOBILE_HINTS = (
    "не заводит", "не едет", "заглох", "не трогается", "стоит во дворе", "не завелась",
)
_SHOP_HINTS = (
    "мастерск", "подбер", "ближайш", "куда отдать", "где помен", "где сделать",
    "найдите сервис", "нужен сервис",
)
_ONSITE_HINTS = ("выезд", "эвакуа", "на месте")
_CONCRETE_EVENT_HINTS = (
    "луж", "затоп", "после мойк", "в воду", "удар", "дтп", "авар", "столкн",
    "заправ", "после ремонт", "после сервис",
)
_UNNAMED_EVENT_HINTS = ("после этого", "после того", "ни с того")
_ACCESS_HINTS = ("ключ", "вскрыт", "иммобилайз", "привязк")
_INSTALL_HINTS = ("установ", "поставить", "врезать", "фаркоп", "сигнализац")
_INTERMITTENT_HINTS = ("иногда", "то пропадает", "то появляется", "бывает что")


@dataclass(frozen=True)
class AcknowledgedItem:
    """One slot the reply is allowed to rely on."""

    slot: str
    value: str
    spoken_as: str
    grounding: str
    raw_text: str | None
    message_id: str | None
    supersedes: str | None
    from_current_evidence: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkippedQuestion:
    """A question that was considered and not asked."""

    slot: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PolicyResult:
    """Customer reply plus metadata for a later chat integration."""

    customer_text: str
    reply: str
    follow_up_question: str | None
    follow_up_slot: str | None
    follow_up_reason: str | None
    primary_situation: str
    situations: tuple[str, ...]
    uncertain: bool
    uncertainty_reasons: tuple[str, ...]
    acknowledged: tuple[AcknowledgedItem, ...]
    skipped_questions: tuple[SkippedQuestion, ...]
    withheld: tuple[str, ...] = WITHHELD

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["acknowledged"] = [item.to_dict() for item in self.acknowledged]
        payload["skipped_questions"] = [item.to_dict() for item in self.skipped_questions]
        payload["situations"] = list(self.situations)
        payload["uncertainty_reasons"] = list(self.uncertainty_reasons)
        payload["withheld"] = list(self.withheld)
        return payload


@dataclass(frozen=True)
class _FollowUp:
    slot: str | None
    question: str
    reason: str


@dataclass
class _Evidence:
    slot: str
    message_id: str
    raw_text: str
    kind: str
    time_scope: str
    supersedes: str | None
    interpretation: str


@dataclass
class _Slot:
    slot: str
    value: str | None
    raw_text: str | None
    kind: str | None
    time_scope: str | None
    supersedes: str | None
    message_id: str | None
    specific: bool
    conflicting: bool
    trusted: bool
    from_current_evidence: bool


@dataclass
class _Parsed:
    fatal: bool
    issues: list[str]
    slots: dict[str, _Slot]
    evidence: list[_Evidence]
    prior: dict[str, str]
    blob: str


@dataclass
class _Change:
    slot: str
    old: str | None
    new: str


def plan_reply(
    extraction: Mapping[str, Any] | None,
    *,
    prior_slots: Mapping[str, Any] | None = None,
    asked_slots: Sequence[str] | None = None,
) -> PolicyResult:
    """Build one Russian reply from an extraction result.

    Bad model output does not raise. It becomes an uncertain reply that asks
    the customer to say the request again, without quoting the raw payload.
    """

    parsed = _parse(extraction, prior_slots)
    asked = _asked(asked_slots)
    if parsed.fatal or (parsed.issues and not _any_specific(parsed)):
        return _rephrase_result(parsed)

    follow, skipped = _select_follow_up(parsed, asked)
    changes = _changes(parsed)
    established = _request_established(parsed, changes)
    if parsed.issues and not established:
        if follow is not None:
            skipped = (*skipped, SkippedQuestion(follow.slot or "rephrase", "uncertain_output"))
        follow = _FollowUp(None, _QUESTIONS["rephrase"], "rephrase")
        primary = "uncertain_output"
    elif not parsed.evidence and parsed.slots:
        if follow is not None and follow.slot:
            skipped = (*skipped, SkippedQuestion(follow.slot, "no_new_customer_facts"))
        follow = None
        primary = "no_new_facts"
    else:
        primary = _classify(parsed, changes, follow, asked)

    body = _render(parsed, primary, changes, follow)
    reply, customer = _attach(body, None if follow is None else follow.question)
    situations = _situations(parsed, primary, follow, changes)
    return PolicyResult(
        customer_text=customer,
        reply=reply,
        follow_up_question=None if follow is None else follow.question,
        follow_up_slot=None if follow is None else follow.slot,
        follow_up_reason=None if follow is None else follow.reason,
        primary_situation=primary,
        situations=situations,
        uncertain=bool(parsed.issues),
        uncertainty_reasons=tuple(parsed.issues),
        acknowledged=_acknowledged(parsed),
        skipped_questions=skipped,
    )


def _asked(asked_slots: Sequence[str] | None) -> set[str]:
    if not asked_slots:
        return set()
    return {item for item in asked_slots if isinstance(item, str) and item}


def _parse(extraction: Mapping[str, Any] | None, prior_slots: Mapping[str, Any] | None) -> _Parsed:
    issues: list[str] = []
    prior = _prior(prior_slots, issues)
    if not isinstance(extraction, Mapping):
        issues.append("extraction must be an object with slots_after_message and evidence")
        return _Parsed(True, issues, {}, [], prior, "")

    extra = set(extraction) - {"slots_after_message", "evidence"}
    if extra:
        names = ", ".join(sorted(str(name) for name in extra))
        issues.append(f"extraction includes fields outside the contract: {names}")

    raw_slots = extraction.get("slots_after_message")
    raw_evidence = extraction.get("evidence")
    if not isinstance(raw_slots, Mapping) or not isinstance(raw_evidence, list):
        issues.append("slots_after_message must be an object and evidence must be a list")
        return _Parsed(True, issues, {}, [], prior, "")

    slots: dict[str, str] = {}
    for key, value in raw_slots.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
            issues.append("slot names and values must be text")
            return _Parsed(True, issues, {}, [], prior, "")
        slots[key.strip()] = value.strip()

    valid, invalid_slots = _parse_evidence(raw_evidence, slots, issues)
    by_slot = {item.slot: item for item in valid}
    state: dict[str, _Slot] = {}
    for name, value in slots.items():
        item = by_slot.get(name)
        trusted = name not in invalid_slots
        raw = item.raw_text if item is not None else None
        state[name] = _Slot(
            slot=name,
            value=value,
            raw_text=raw,
            kind=item.kind if item is not None else None,
            time_scope=item.time_scope if item is not None else None,
            supersedes=item.supersedes if item is not None else None,
            message_id=item.message_id if item is not None else None,
            specific=trusted and _is_specific(value, raw),
            conflicting=trusted and value == "conflicting",
            trusted=trusted,
            from_current_evidence=item is not None,
        )
    blob = _blob(valid, state)
    return _Parsed(False, issues, state, valid, prior, blob)


def _prior(prior_slots: Mapping[str, Any] | None, issues: list[str]) -> dict[str, str]:
    if prior_slots is None:
        return {}
    if not isinstance(prior_slots, Mapping):
        issues.append("prior_slots must be an object of text values when provided")
        return {}
    cleaned: dict[str, str] = {}
    for key, value in prior_slots.items():
        if not isinstance(key, str) or not isinstance(value, str):
            issues.append("prior_slots must be an object of text values when provided")
            return {}
        cleaned[key] = value.strip()
    return cleaned


def _parse_evidence(
    raw_evidence: list[Any],
    slots: dict[str, str],
    issues: list[str],
) -> tuple[list[_Evidence], set[str]]:
    valid: list[_Evidence] = []
    invalid: set[str] = set()
    seen: set[str] = set()
    for index, entry in enumerate(raw_evidence, 1):
        prefix = f"evidence[{index}]"
        if not isinstance(entry, Mapping) or set(entry) != EVIDENCE_FIELDS:
            issues.append(f"{prefix} does not match the evidence schema")
            if isinstance(entry, Mapping) and isinstance(entry.get("slot"), str):
                invalid.add(entry["slot"].strip())
            continue
        supersedes = entry["supersedes"]
        string_fields = EVIDENCE_FIELDS - {"supersedes"}
        if any(not isinstance(entry[key], str) for key in string_fields):
            issues.append(f"{prefix} uses a non-text field")
            invalid.add(str(entry["slot"]))
            continue
        if entry["kind"] not in KINDS or entry["time_scope"] not in TIME_SCOPES:
            issues.append(f"{prefix} has a kind or time_scope outside the schema")
            invalid.add(entry["slot"].strip())
            continue
        if supersedes is not None and (not isinstance(supersedes, str) or not supersedes.strip()):
            issues.append(f"{prefix} has an invalid supersedes value")
            invalid.add(entry["slot"].strip())
            continue
        slot = entry["slot"].strip()
        if not slot:
            issues.append(f"{prefix} has an empty slot name")
            continue
        if slot in seen:
            issues.append(f"{prefix} repeats slot {slot}")
            invalid.add(slot)
            continue
        seen.add(slot)
        interpretation = entry["interpretation"].strip()
        if slot not in slots or slots[slot] != interpretation:
            issues.append(f"{prefix} interpretation does not match slots_after_message.{slot}")
            invalid.add(slot)
            continue
        valid.append(_Evidence(
            slot=slot,
            message_id=entry["message_id"].strip(),
            raw_text=entry["raw_text"].strip(),
            kind=entry["kind"],
            time_scope=entry["time_scope"],
            supersedes=None if supersedes is None else supersedes.strip(),
            interpretation=interpretation,
        ))
    return valid, invalid


def _is_specific(value: str | None, raw_text: str | None) -> bool:
    if not value:
        return False
    token = value.strip()
    if token in _NON_ANSWERS:
        return False
    if token in _TYPE_ONLY:
        return bool(_plain(raw_text))
    return True


def _blob(evidence: list[_Evidence], slots: dict[str, _Slot]) -> str:
    parts: list[str] = []
    for item in evidence:
        parts.append(item.raw_text)
        if item.interpretation not in _ENUM_RU.get(item.slot, {}) and item.interpretation not in _NON_ANSWERS:
            parts.append(item.interpretation)
    for state in slots.values():
        if state.trusted and state.value and state.value not in _NON_ANSWERS:
            if state.value not in _ENUM_RU.get(state.slot, {}):
                parts.append(state.value)
    return " ".join(parts).casefold()


def _has_hint(blob: str, hints: Sequence[str]) -> bool:
    return any(hint in blob for hint in hints)


def _slot(parsed: _Parsed, name: str) -> _Slot | None:
    state = parsed.slots.get(name)
    if state is None or not state.trusted:
        return None
    return state


def _specific(parsed: _Parsed, name: str) -> bool:
    state = _slot(parsed, name)
    return bool(state and state.specific)


def _value(parsed: _Parsed, name: str) -> str | None:
    state = _slot(parsed, name)
    if state is None:
        return None
    return state.value


def _any_specific(parsed: _Parsed) -> bool:
    return any(state.specific for state in parsed.slots.values())


def _quote(text: str | None) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).replace("?", " ").replace("«", " ").replace("»", " ").split())
    cleaned = cleaned.strip(" .,!…:;")
    if not cleaned:
        return ""
    return f"«{cleaned}»"


def _plain(text: str | None) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).replace("?", " ").split())
    return cleaned.strip(" .,!…:;")


def _speak(slot: str, value: str | None, raw_text: str | None) -> str:
    token = (value or "").strip()
    gloss = _ENUM_RU.get(slot, {}).get(token)
    if gloss:
        return gloss
    if token == "other" and raw_text:
        return _quote(raw_text)
    if slot in _PLAIN_SLOTS and token and token not in _TYPE_ONLY and not _SLUG_RE.match(token):
        return token
    if slot in _PLAIN_SLOTS and raw_text:
        return _plain(raw_text)
    quoted = _quote(raw_text)
    if slot in _QUOTE_SLOTS and quoted:
        return quoted
    if token and token not in _TYPE_ONLY and token not in _NON_ANSWERS and not _SLUG_RE.match(token):
        if slot in _QUOTE_SLOTS:
            return _quote(token)
        return token.rstrip(".")
    return quoted


def _spoken(parsed: _Parsed, name: str) -> str:
    state = _slot(parsed, name)
    if state is None or not state.specific:
        return ""
    return _speak(state.slot, state.value, state.raw_text)


def _speak_prior(slot: str, value: str | None) -> str:
    return _speak(slot, value, None)


def _immobile(parsed: _Parsed) -> bool:
    state = _value(parsed, "current_state")
    if state == "disappeared":
        return False
    if state == "immobile":
        return True
    if state in {"present", "intermittent"}:
        return False
    return _has_hint(parsed.blob, _IMMOBILE_HINTS)


def _shop(parsed: _Parsed) -> bool:
    location = _value(parsed, "location_format")
    if location in {"workshop", "onsite", "transport"}:
        return True
    return _has_hint(parsed.blob, _SHOP_HINTS)


def _powertrain_needed(parsed: _Parsed) -> bool:
    if _specific(parsed, "powertrain") or _value(parsed, "current_state") == "disappeared":
        return False
    if _has_hint(parsed.blob, _POWERTRAIN_IRRELEVANT) and not _has_hint(parsed.blob, _POWERTRAIN_HINTS):
        return False
    return _has_hint(parsed.blob, _POWERTRAIN_HINTS)


def _noise(parsed: _Parsed) -> bool:
    if _value(parsed, "intent") == "known_service" and not _has_hint(parsed.blob, _NOISE_HINTS):
        return False
    if _value(parsed, "intent") == "known_service" and _has_hint(parsed.blob, _POWERTRAIN_IRRELEVANT):
        return False
    return _has_hint(parsed.blob, _NOISE_HINTS)


def _access(parsed: _Parsed) -> bool:
    return _has_hint(parsed.blob, _ACCESS_HINTS)


def _changes(parsed: _Parsed) -> list[_Change]:
    changes: list[_Change] = []
    for item in parsed.evidence:
        state = parsed.slots.get(item.slot)
        if state is None or not state.trusted or not state.specific:
            continue
        prior_value = parsed.prior.get(item.slot)
        changed = prior_value is not None and prior_value != (state.value or "")
        if item.supersedes is None and not changed:
            continue
        old = _speak_prior(item.slot, prior_value) if changed else None
        new = _speak(item.slot, state.value, state.raw_text)
        if not new:
            continue
        changes.append(_Change(item.slot, old or None, new))
    return changes


def _request_established(parsed: _Parsed, changes: list[_Change]) -> bool:
    if changes:
        return True
    if _specific(parsed, "main_symptom") or _specific(parsed, "known_service"):
        return True
    if _specific(parsed, "affected_item") or _immobile(parsed):
        return True
    kinds = {item.kind for item in parsed.evidence}
    if kinds & {"hypothesis", "reported_diagnosis", "service_request"}:
        return True
    if _value(parsed, "current_state") in {"disappeared", "immobile", "present", "intermittent"}:
        return True
    return False


def _select_follow_up(
    parsed: _Parsed,
    asked: set[str],
) -> tuple[_FollowUp | None, tuple[SkippedQuestion, ...]]:
    skipped: list[SkippedQuestion] = []
    chosen: _FollowUp | None = None
    seen: set[str] = set()

    def consider(slot: str | None, status: str, question: str, reason: str) -> None:
        nonlocal chosen
        key = slot or reason
        if key in seen:
            return
        seen.add(key)
        if status == "ask":
            if slot and slot in asked:
                skipped.append(SkippedQuestion(slot, "already_asked"))
                return
            if chosen is None:
                chosen = _FollowUp(slot, question, reason)
                return
            if slot:
                skipped.append(SkippedQuestion(slot, "deferred"))
            return
        if slot:
            skipped.append(SkippedQuestion(slot, status))

    for name in _CONFLICT_ORDER:
        state = _slot(parsed, name)
        if state is not None and state.conflicting:
            question = _CONFLICT_QUESTION.get(name, "Какой из вариантов верный?")
            consider(name, "ask", question, "conflict")

    intent = _value(parsed, "intent")
    symptom_multiple = _value(parsed, "main_symptom") == "multiple"
    if intent == "multiple" or symptom_multiple:
        consider("intent", "ask", _QUESTIONS["several"], "several_topics")
    elif _specific(parsed, "intent"):
        consider("intent", "already_known", "", "")
    elif not _any_specific(parsed):
        consider("intent", "ask", _QUESTIONS["intent"], "unclear_request")
    else:
        consider("intent", "irrelevant", "", "")

    if _specific(parsed, "main_symptom"):
        consider("main_symptom", "already_known", "", "")
    elif intent in {"complaint", "desired_result", "event"} or _noise(parsed) or _immobile(parsed) or "intent" in asked:
        consider("main_symptom", "ask", _QUESTIONS["main_symptom"], "missing_symptom")
    else:
        consider("main_symptom", "irrelevant", "", "")

    if _specific(parsed, "known_service"):
        consider("known_service", "already_known", "", "")
    elif intent == "known_service" or _value(parsed, "known_service") in {"ambiguous_candidates", "unknown"}:
        consider("known_service", "ask", _QUESTIONS["known_service"], "ambiguous_service")
    else:
        consider("known_service", "irrelevant", "", "")

    if _specific(parsed, "observed_context"):
        consider("observed_context", "already_known", "", "")
    elif _noise(parsed):
        consider("observed_context", "ask", _QUESTIONS["observed_context"], "noise_context")
    else:
        consider("observed_context", "irrelevant", "", "")

    location = _value(parsed, "location_format")
    if _specific(parsed, "location_format"):
        consider("location_format", "already_known", "", "")
    elif _immobile(parsed) or (_has_hint(parsed.blob, _ONSITE_HINTS) and not _shop(parsed)):
        consider("location_format", "ask", _QUESTIONS["location_format"], "immobile_location")
    else:
        consider("location_format", "irrelevant", "", "")

    need_vehicle = bool(
        _specific(parsed, "known_service")
        or _specific(parsed, "main_symptom")
        or _specific(parsed, "affected_item")
        or _shop(parsed)
        or _immobile(parsed)
        or intent in {"known_service", "complaint", "desired_result"}
        or {"main_symptom", "intent", "known_service"} & asked
    )
    if _specific(parsed, "vehicle"):
        consider("vehicle", "already_known", "", "")
    elif need_vehicle:
        consider("vehicle", "ask", _QUESTIONS["vehicle"], "missing_vehicle")
    else:
        consider("vehicle", "irrelevant", "", "")

    area_needed = _shop(parsed) or location in {"workshop", "onsite", "transport"}
    if _specific(parsed, "search_area"):
        consider("search_area", "already_known", "", "")
    elif area_needed:
        consider("search_area", "ask", _QUESTIONS["search_area"], "shop_area")
    else:
        consider("search_area", "irrelevant", "", "")

    if _specific(parsed, "gearbox"):
        consider("gearbox", "already_known", "", "")
    elif _has_hint(parsed.blob, _GEARBOX_HINTS):
        consider("gearbox", "ask", _QUESTIONS["gearbox"], "gearbox_needed")
    else:
        consider("gearbox", "irrelevant", "", "")

    if _specific(parsed, "powertrain"):
        consider("powertrain", "already_known", "", "")
    elif _powertrain_needed(parsed):
        consider("powertrain", "ask", _QUESTIONS["powertrain"], "powertrain_needed")
    else:
        consider("powertrain", "irrelevant", "", "")

    diagnosis = _value(parsed, "previous_diagnosis")
    guess_and_report = _has_hint(parsed.blob, ("мне кажется", "предполагаю")) and _has_hint(
        parsed.blob, ("в сервисе сказали", "в заключении", "диагностировали")
    )
    if diagnosis in {"user_guess", "reported_conclusion", "document_quote", "none_reported"}:
        consider("previous_diagnosis", "already_known", "", "")
    elif guess_and_report:
        consider(
            "previous_diagnosis",
            "ask",
            "Это заключение сервиса или ваше предположение?",
            "diagnosis_ambiguity",
        )
    else:
        consider("previous_diagnosis", "irrelevant", "", "")

    if _specific(parsed, "affected_item"):
        consider("affected_item", "already_known", "", "")
    elif intent == "desired_result" or _has_hint(parsed.blob, _INSTALL_HINTS):
        if not _specific(parsed, "known_service"):
            consider("affected_item", "ask", _QUESTIONS["affected_item"], "missing_item")
        else:
            consider("affected_item", "irrelevant", "", "")
    else:
        consider("affected_item", "irrelevant", "", "")

    if _specific(parsed, "current_state"):
        consider("current_state", "already_known", "", "")
    elif _has_hint(parsed.blob, _INTERMITTENT_HINTS) and not _immobile(parsed):
        consider("current_state", "ask", _QUESTIONS["current_state"], "intermittent_state")
    else:
        consider("current_state", "irrelevant", "", "")

    event_in_text = _has_hint(parsed.blob, _CONCRETE_EVENT_HINTS)
    unnamed_event = _has_hint(parsed.blob, _UNNAMED_EVENT_HINTS) and not event_in_text
    if _specific(parsed, "event") or event_in_text:
        consider("event", "already_known", "", "")
    elif unnamed_event:
        consider("event", "ask", _QUESTIONS["event"], "unnamed_event")
    else:
        consider("event", "irrelevant", "", "")

    if _specific(parsed, "fitment"):
        consider("fitment", "already_known", "", "")
    elif _has_hint(parsed.blob, _INSTALL_HINTS) and not _specific(parsed, "fitment"):
        consider(
            "fitment",
            "ask",
            "Есть точное название или параметры? Если нет, это сверит сервис по машине.",
            "fitment",
        )
    else:
        consider("fitment", "irrelevant", "", "")

    return chosen, tuple(skipped)


def _classify(
    parsed: _Parsed,
    changes: list[_Change],
    follow: _FollowUp | None,
    asked: set[str],
) -> str:
    if changes:
        return "correction"
    if follow is not None and follow.reason == "conflict":
        return "conflict"
    if follow is not None and follow.reason == "several_topics":
        return "several_topics"
    if _assumption(parsed) and _value(parsed, "intent") != "known_service":
        return "assumption"
    if _reported(parsed) and not _assumption(parsed):
        return "reported_conclusion"
    if _value(parsed, "current_state") == "disappeared":
        return "symptom_resolved"
    if (_specific(parsed, "known_service") or _service_request(parsed)) and _shop(parsed):
        return "shop_search"
    if _specific(parsed, "known_service") or _service_request(parsed) or (
        _value(parsed, "intent") == "desired_result" and _specific(parsed, "affected_item")
    ):
        return "explicit_service"
    if _immobile(parsed):
        return "immobile"
    if _specific(parsed, "main_symptom"):
        return "complaint"
    if (
        follow is None
        and "main_symptom" in asked
        and "vehicle" in asked
        and not _specific(parsed, "main_symptom")
        and not _specific(parsed, "vehicle")
    ):
        return "questions_exhausted"
    if follow is not None and follow.slot == "vehicle" and "main_symptom" in asked:
        return "missing_detail"
    if follow is not None and follow.reason == "unclear_request":
        return "unclear_request"
    if _value(parsed, "intent") in {"complaint", "desired_result"}:
        return "unclear_symptom"
    if follow is not None:
        return "missing_detail"
    return "ready"


def _assumption(parsed: _Parsed) -> bool:
    if _value(parsed, "previous_diagnosis") == "user_guess":
        return True
    return any(item.kind == "hypothesis" for item in parsed.evidence)


def _reported(parsed: _Parsed) -> bool:
    if _value(parsed, "previous_diagnosis") in {"reported_conclusion", "document_quote"}:
        return True
    return any(item.kind == "reported_diagnosis" for item in parsed.evidence)


def _service_request(parsed: _Parsed) -> bool:
    return any(item.kind == "service_request" for item in parsed.evidence)


def _situations(
    parsed: _Parsed,
    primary: str,
    follow: _FollowUp | None,
    changes: list[_Change],
) -> tuple[str, ...]:
    found: list[str] = [primary]
    if parsed.issues and "uncertain_output" not in found:
        found.append("uncertain_output")
    if changes and "correction" not in found:
        found.append("correction")
    if _assumption(parsed) and "assumption" not in found:
        found.append("assumption")
    if _reported(parsed) and "reported_conclusion" not in found:
        found.append("reported_conclusion")
    if follow is None and not parsed.issues and "ready" not in found and primary != "no_new_facts":
        found.append("ready")
    return tuple(found)


def _render(
    parsed: _Parsed,
    primary: str,
    changes: list[_Change],
    follow: _FollowUp | None,
) -> str:
    asking = follow is not None
    if primary == "uncertain_output":
        body = _uncertain_body(parsed)
    elif primary == "correction":
        body = _correction_body(parsed, changes)
    elif primary == "conflict":
        body = _conflict_body(follow)
    elif primary == "several_topics":
        body = _several_body(parsed)
    elif primary == "assumption":
        body = _assumption_body(parsed)
    elif primary == "reported_conclusion":
        body = _reported_body(parsed)
    elif primary == "symptom_resolved":
        body = _resolved_body(parsed)
    elif primary == "shop_search":
        body = _service_body(parsed, shop=True, asking=asking)
    elif primary == "explicit_service":
        body = _service_body(parsed, shop=False, asking=asking)
    elif primary == "immobile":
        body = _immobile_body(parsed)
    elif primary == "complaint":
        body = _complaint_body(parsed, asking)
    elif primary == "no_new_facts":
        body = _no_new_body(parsed)
    elif primary == "unclear_symptom":
        body = "Жалоба есть, а самого симптома пока нет."
    elif primary == "questions_exhausted":
        body = "Пока не буду повторять те же вопросы."
    elif primary == "missing_detail" and follow is not None and follow.slot == "vehicle":
        body = "По жалобе переспрашивать не буду."
    elif primary == "unclear_request":
        body = "Пока не уловил суть."
    elif primary == "ready":
        body = _ready_body(parsed)
    else:
        body = "Пока держу только то, что уже ясно."
    if parsed.issues and primary != "uncertain_output":
        body = f"Сообщение разобрано не полностью. {body}"
    if _access(parsed) and primary in {"explicit_service", "shop_search", "complaint", "immobile"}:
        body = f"{body} Право доступа проверит мастерская, документы здесь не спрашиваю."
    return body


def _uncertain_body(parsed: _Parsed) -> str:
    bits = _trusted_bits(parsed)
    if not bits:
        return "Не уверен, что правильно разобрал сообщение."
    shown = ", ".join(bits[:3])
    return f"Сообщение разобрано не полностью. Понял только: {shown}."


def _trusted_bits(parsed: _Parsed) -> list[str]:
    order = (
        "vehicle", "known_service", "main_symptom", "affected_item",
        "powertrain", "observed_context", "search_area",
    )
    bits: list[str] = []
    for name in order:
        spoken = _spoken(parsed, name)
        if spoken and spoken not in bits:
            bits.append(spoken)
    return bits


def _correction_body(parsed: _Parsed, changes: list[_Change]) -> str:
    by = {item.slot: item for item in changes}
    clauses: list[str] = []
    used: set[str] = set()
    vehicle = by.get("vehicle")
    powertrain = by.get("powertrain")
    if vehicle and powertrain:
        if vehicle.old and powertrain.old:
            clauses.append(
                f"машина не {vehicle.old}, а {vehicle.new}; теперь {powertrain.new}, не {powertrain.old}"
            )
        elif vehicle.old:
            clauses.append(f"машина не {vehicle.old}, а {vehicle.new}, {powertrain.new}")
        else:
            clauses.append(f"машина — {vehicle.new}, {powertrain.new}")
        used.update({"vehicle", "powertrain"})
    elif vehicle:
        clauses.append(
            f"машина не {vehicle.old}, а {vehicle.new}" if vehicle.old else f"машина — {vehicle.new}"
        )
        used.add("vehicle")
    context = by.get("observed_context")
    if context:
        clauses.append(
            f"уже не {context.old}, а {context.new}" if context.old else f"это {context.new}"
        )
        used.add("observed_context")
    for change in changes:
        if change.slot in used:
            continue
        noun = _SLOT_NOUN.get(change.slot, "сведение")
        if change.old:
            clauses.append(f"{noun} не {change.old}, а {change.new}")
        else:
            clauses.append(f"{noun} — {change.new}")
    text = "Поправил по вашим словам: " + ", ".join(clauses) + "."
    if "main_symptom" not in by:
        symptom = _spoken(parsed, "main_symptom")
        if symptom:
            text += f" Жалобу {symptom} оставляю."
    return text


def _conflict_body(follow: _FollowUp | None) -> str:
    slot = follow.slot if follow is not None else None
    topic = _CONFLICT_TOPIC.get(slot or "", "По этому пункту")
    return f"Сведения расходятся. {topic} не выбираю один вариант сам."


def _several_body(parsed: _Parsed) -> str:
    quotes: list[str] = []
    for item in parsed.evidence:
        quoted = _quote(item.raw_text)
        if quoted and quoted not in quotes:
            quotes.append(quoted)
    if len(quotes) >= 2:
        return f"Вижу больше одной темы: {quotes[0]} и {quotes[1]}."
    if quotes:
        return f"Вижу больше одной темы: {quotes[0]}."
    return "Вижу больше одной темы."


def _assumption_body(parsed: _Parsed) -> str:
    fact = ""
    for item in parsed.evidence:
        if item.kind == "observation" and item.slot in {"main_symptom", "current_state", "observed_context"}:
            fact = _quote(item.raw_text) or _speak(item.slot, item.interpretation, item.raw_text)
            break
    if not fact:
        fact = _spoken(parsed, "main_symptom")
    guess = ""
    for item in parsed.evidence:
        if item.kind == "hypothesis" or item.interpretation == "user_guess":
            guess = _quote(item.raw_text) or "это пока ваше предположение"
            break
    if fact and guess:
        head = f"Разделю факт и догадку: вы заметили {fact}, а {guess} — пока только предположение."
    elif guess:
        head = f"Разделю факт и догадку: {guess} — пока только предположение."
    else:
        head = "Разделю факт и догадку: причину по переписке не утверждаю."
    vehicle = _spoken(parsed, "vehicle")
    if vehicle:
        head += f" Машина: {vehicle}."
    tail = "Догадку не подтверждаю и ремонт не назначаю."
    if _immobile(parsed):
        tail = "Сама сейчас не едет. Догадку не подтверждаю и ремонт не назначаю."
    return f"{head} {tail}"


def _reported_body(parsed: _Parsed) -> str:
    claim = ""
    for item in parsed.evidence:
        if item.kind == "reported_diagnosis" or item.interpretation in {"reported_conclusion", "document_quote"}:
            claim = _quote(item.raw_text) or _spoken(parsed, "previous_diagnosis")
            break
    if not claim:
        claim = _spoken(parsed, "previous_diagnosis") or "заключение без цитаты"
    parts = [f"Вы передаёте чужое заключение: {claim}."]
    separate: list[str] = []
    symptom = _spoken(parsed, "main_symptom")
    if symptom and symptom != claim:
        separate.append(symptom)
    context = _spoken(parsed, "observed_context")
    if context:
        separate.append(context)
    vehicle = _spoken(parsed, "vehicle")
    if vehicle:
        separate.append(vehicle)
    if separate:
        parts.append("Отдельно вы сказали: " + ", ".join(separate) + ".")
    parts.append("Заключение не подтверждаю и ремонт по нему не назначаю.")
    return " ".join(parts)


def _resolved_body(parsed: _Parsed) -> str:
    bits = [bit for bit in (_spoken(parsed, "main_symptom"), _spoken(parsed, "vehicle")) if bit]
    if bits:
        return (
            "Сейчас, по вашим словам, этого уже нет: "
            + ", ".join(bits)
            + ". Причину не называю и выезд не предлагаю."
        )
    return "Сейчас, по вашим словам, этого уже нет. Причину не называю и выезд не предлагаю."


def _service_body(parsed: _Parsed, *, shop: bool, asking: bool) -> str:
    work = _spoken(parsed, "known_service") or _spoken(parsed, "affected_item")
    if not work:
        for item in parsed.evidence:
            if item.kind == "service_request":
                work = _quote(item.raw_text)
                break
    details = [bit for bit in (
        _spoken(parsed, "vehicle"),
        _spoken(parsed, "powertrain"),
        _spoken(parsed, "search_area"),
    ) if bit and bit != work]
    head = ", ".join(bit for bit in (work, *details) if bit)
    if shop:
        lead = f"Подбор сервиса пока без названия мастерской: {head}."
        if asking:
            return lead
        return lead + " Конкретную мастерскую, время и стоимость не называю."
    lead = f"Принял: {head}."
    if asking:
        return lead
    return lead + " Время и стоимость не подтверждаю."


def _immobile_body(parsed: _Parsed) -> str:
    bits = [bit for bit in (
        _spoken(parsed, "main_symptom"),
        _spoken(parsed, "event"),
        _spoken(parsed, "vehicle"),
        _spoken(parsed, "powertrain"),
    ) if bit]
    if bits:
        return "Понял, что сама машина сейчас не едет: " + ", ".join(bits) + ". Причину не называю."
    return "Понял, что сама машина сейчас не едет. Причину не называю."


def _complaint_body(parsed: _Parsed, asking: bool) -> str:
    bits = [bit for bit in (
        _spoken(parsed, "main_symptom"),
        _spoken(parsed, "event"),
        _spoken(parsed, "observed_context"),
        _spoken(parsed, "vehicle"),
    ) if bit]
    lead = "Понял вас: " + ", ".join(bits) + "." if bits else "Понял вас."
    if asking:
        return lead
    return lead + " Причину по описанию не ставлю."


def _no_new_body(parsed: _Parsed) -> str:
    bits = _trusted_bits(parsed)[:3]
    if bits:
        return "Новых сведений не вижу. Оставляю как есть: " + ", ".join(bits) + "."
    return "Новых сведений не вижу."


def _ready_body(parsed: _Parsed) -> str:
    if _specific(parsed, "main_symptom"):
        return _complaint_body(parsed, asking=False)
    if _specific(parsed, "known_service"):
        return _service_body(parsed, shop=_shop(parsed), asking=False)
    return "Этого достаточно, чтобы передать описание дальше. Причину и запись не назначаю."


def _attach(body: str, question: str | None) -> tuple[str, str]:
    reply = " ".join(body.split())
    if reply and reply[-1] not in ".!?":
        reply += "."
    if not question:
        return reply, reply
    customer = f"{reply} {question}" if reply else question
    return reply, customer


def _rephrase_result(parsed: _Parsed) -> PolicyResult:
    follow = _FollowUp(None, _QUESTIONS["rephrase"], "rephrase")
    reply, customer = _attach(_uncertain_body(parsed), follow.question)
    return PolicyResult(
        customer_text=customer,
        reply=reply,
        follow_up_question=follow.question,
        follow_up_slot=None,
        follow_up_reason=follow.reason,
        primary_situation="uncertain_output",
        situations=("uncertain_output",),
        uncertain=True,
        uncertainty_reasons=tuple(parsed.issues) or ("extraction could not be used",),
        acknowledged=(),
        skipped_questions=(),
    )


def _acknowledged(parsed: _Parsed) -> tuple[AcknowledgedItem, ...]:
    items: list[AcknowledgedItem] = []
    for name in sorted(parsed.slots):
        state = parsed.slots[name]
        if not state.trusted:
            continue
        if not state.specific and not state.conflicting:
            continue
        items.append(AcknowledgedItem(
            slot=name,
            value=state.value or "",
            spoken_as=_speak(name, state.value, state.raw_text) if state.specific else "",
            grounding=_grounding(state),
            raw_text=state.raw_text,
            message_id=state.message_id,
            supersedes=state.supersedes,
            from_current_evidence=state.from_current_evidence,
        ))
    return tuple(items)


def _grounding(state: _Slot) -> str:
    if state.conflicting:
        return "conflict"
    if not state.from_current_evidence:
        return "accumulated"
    if state.kind == "service_request":
        return "service_request"
    if state.kind == "hypothesis" or state.value == "user_guess":
        return "assumption"
    if state.kind == "reported_diagnosis" or state.value in {"reported_conclusion", "document_quote"}:
        return "reported_claim"
    return "reported_fact"


__all__ = [
    "AcknowledgedItem",
    "PolicyResult",
    "SkippedQuestion",
    "WITHHELD",
    "plan_reply",
]
