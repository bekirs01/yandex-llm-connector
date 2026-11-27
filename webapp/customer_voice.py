"""Compose a Russian reply from this customer's own facts.

The wording follows what the customer asked and what is already known.
At most one question is added. Prices, hours, and bookings come from verified
shop facts, or the reply says that those facts are not available. One clear
catalog match may name the job in ordinary words. A split match stays general.
A catalog row is not a tool, a price, or a free appointment.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from webapp.advisor import (
    acceptance_reply,
    capability_reply,
    idle_reply,
    inclusion_reply,
    is_detail_answer,
    price_limitation_offer,
    price_text,
    switch_reply,
    symptom_dropped,
)
from webapp.grounding import (
    GroundedTurn,
    _known_city_label,
    _place_from_token,
    ground_conversation,
    verified_business,
)
from webapp.retrieval import RetrievalResult, confident_service
from webapp.turn_reading import TurnReading


_GENERIC_CONTEXT = "при торможении, на ходу, при повороте или на месте"


def compose_reply(
    messages: list[dict[str, str]],
    reading: TurnReading,
    policy: Any | None,
    retrieved: RetrievalResult | None,
    grounded: GroundedTurn | None = None,
    business_facts: Any = None,
    facts_given: bool = False,
) -> str:
    grounded = grounded if grounded is not None else ground_conversation(messages, reading)
    facts = business_facts if facts_given else verified_business()
    accepted = acceptance_reply(messages, reading, grounded, retrieved, facts)
    if accepted:
        return _tidy_reply(accepted)
    if is_detail_answer(messages):
        priced = price_text(messages, grounded, retrieved, facts)
        if priced:
            return _tidy_reply(priced)
    substantive = bool(
        grounded.correction or grounded.unclear_referent or grounded.brand_raw
        or grounded.symptom or grounded.service or grounded.model or grounded.make
        or grounded.year or grounded.city or grounded.asks_hours
        or grounded.asks_equipment or grounded.urgent or grounded.stated_vehicle
        or grounded.stated_total is not None or reading.asks_contact
    )
    if reading.out_of_scope and not substantive and not grounded.urgent:
        lead = "Здравствуйте. " if reading.greeting else ""
        return _tidy_reply(
            lead + "Я отвечаю по автосервису: работа, цена, запись и наличие. С этим вопросом не помогу."
        )
    if reading.acknowledgment and not grounded.correction and not grounded.asks_advice and not grounded.urgent:
        return "Хорошо."
    if reading.social_only and not substantive:
        return _social(reading, len(messages) > 1)
    if grounded.asks_advice and not grounded.urgent and not _has_shop_question(reading, grounded):
        lead = "Здравствуйте. " if reading.greeting and not reading.social_only else ""
        fact = ""
        if grounded.symptom:
            fact = _cap(grounded.symptom).rstrip(".") + ". "
        car = grounded.vehicle_phrase()
        if car and car.casefold() not in fact.casefold():
            fact += f"{car}. "
        return _tidy_reply(lead + fact + "Отсюда не скажу, как поступить. Что ещё происходит?")
    if symptom_dropped(messages, grounded):
        switched = switch_reply(messages, reading, grounded, retrieved, facts)
        grounded = replace(grounded, symptom=None, fresh_symptom=False, detail=None)
        if switched:
            return _tidy_reply(switched)
    included = inclusion_reply(messages, reading, grounded, retrieved, facts)
    if included:
        return _tidy_reply(included)
    if not grounded.urgent:
        idle = idle_reply(messages, reading, grounded, facts)
        if idle:
            return _tidy_reply(idle)
    capable = capability_reply(messages, reading, grounded, retrieved, facts)
    if capable:
        return _tidy_reply(_lead_if(reading) + capable)
    parts: list[str] = []
    if reading.greeting and not reading.social_only:
        parts.append("Здравствуйте.")
    if grounded.urgent:
        parts.append(_safety(grounded.urgent))
    direct = _direct_answer(reading, grounded, messages, retrieved, facts)
    if direct:
        parts.append(direct)
    if not grounded.urgent and _context_still_needed(reading, grounded, messages, direct):
        statement = _statement(grounded, retrieved, _customer_locative(messages, grounded.city))
        blob = " ".join(parts).casefold()
        if statement and not _covered(statement, blob):
            parts.append(statement)
    if grounded.urgent:
        car = grounded.vehicle_phrase()
        if car and car.casefold() not in " ".join(parts).casefold():
            parts.append(f"Машина: {car}.")
    question = None if grounded.urgent else _follow_up(grounded, reading, policy)
    if question and direct and direct.count("?") >= 1:
        question = None
    elif question and direct and "составлю" in direct.casefold() and not grounded.open_extra:
        question = None
    if question:
        parts.append(question)
    text = " ".join(part.strip() for part in parts if part and part.strip())
    text = _tidy_reply(text)
    if not text:
        text = "Напишите, пожалуйста, что случилось или какую работу нужно сделать."
    return text


def _lead_if(reading: TurnReading) -> str:
    if reading.greeting and not reading.social_only:
        return "Здравствуйте. "
    return ""


def _social(reading: TurnReading, has_history: bool) -> str:
    if reading.farewell and reading.thanks:
        return "Пожалуйста. До свидания."
    if reading.farewell:
        return "До свидания."
    if reading.thanks and reading.greeting:
        return "Здравствуйте. Пожалуйста."
    if reading.thanks:
        if has_history:
            return "Пожалуйста. Если по этому же вопросу будет ещё что-то, напишите."
        return "Пожалуйста."
    if reading.smalltalk:
        return "Нормально, спасибо. Как у вас?"
    if reading.greeting:
        if has_history:
            return "Здравствуйте. Я здесь, продолжаем."
        return "Здравствуйте. Напишите, что нужно."
    if reading.acknowledgment:
        return "Хорошо."
    if reading.vague:
        return "Слушаю. О чём речь?"
    return "Я на связи. Напишите, пожалуйста, чуть конкретнее."


def _place_bits(grounded: GroundedTurn, job: str | None, locative: str | None) -> list[str]:
    haystack = f"{grounded.service or ''} {job or ''}".casefold()
    bits = []
    if grounded.city and grounded.city.casefold() not in haystack:
        if locative:
            bits.append(locative)
        elif _known_city_label(grounded.city):
            bits.append(grounded.city)
    if grounded.powertrain and grounded.powertrain.casefold() not in haystack:
        bits.append(grounded.powertrain)
    return bits


def _job_name(grounded: GroundedTurn, retrieved: RetrievalResult | None) -> str | None:
    strong = confident_service(retrieved)
    if strong is not None and strong.title.strip():
        title = strong.title.strip().rstrip(".")
        return title[:1].lower() + title[1:]
    return grounded.service


def _covered(statement: str, blob: str) -> bool:
    words = [
        word for word in re.findall(r"[0-9a-zа-яё]{5,}", statement.casefold())
        if word not in {"речь", "таком", "заказе", "машина", "такая", "такой"}
    ]
    if not words:
        return statement.casefold() in blob
    return all(word in blob for word in words[:4])


def _statement(
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None = None,
    locative: str | None = None,
) -> str:
    if grounded.unclear_referent:
        return ""
    if grounded.brand_raw and not grounded.model:
        year = f"{grounded.year} год записал. " if grounded.year else ""
        return f"{year}Из «{grounded.brand_raw}» марку уверенно не читаю."
    car = grounded.vehicle_phrase()
    if grounded.correction:
        return _correction_sentence(grounded, car)
    job = _job_name(grounded, retrieved)
    chunks: list[str] = []
    if job and grounded.symptom:
        named = grounded.make or grounded.model or grounded.stated_vehicle
        where = f" на {car}" if named and car else ""
        chunks.append(f"{_cap(grounded.symptom)}")
        chunks.append(f"{job}{where}")
        place = _place_bits(grounded, job, locative)
        if place:
            chunks.append(", ".join(place))
    elif job and not grounded.symptom:
        named = grounded.make or grounded.model or grounded.stated_vehicle
        where = f" на {car}" if named and car else ""
        chunks.append(f"{job}{where}")
        place = _place_bits(grounded, job, locative)
        if place:
            chunks.append(", ".join(place))
    elif grounded.symptom:
        place = _spoken_place(grounded, locative)
        vehicle = f" — {car}" if car else ""
        chunks.append(f"{_cap(grounded.symptom)}{vehicle}{place}")
    elif car or _spoken_place(grounded, locative):
        bits = [bit for bit in (car, _spoken_place(grounded, locative).lstrip(", ")) if bit]
        chunks.append(", ".join(bits))
    if grounded.powertrain and grounded.powertrain not in " ".join(chunks).casefold():
        chunks.append(grounded.powertrain)
    if grounded.detail and grounded.detail.casefold() not in " ".join(chunks).casefold():
        extra = _polish_customer(grounded.detail)
        if extra and extra.casefold() not in " ".join(chunks).casefold():
            if chunks and len(extra) <= 48:
                chunks[-1] = chunks[-1].rstrip(".") + ", " + extra[0].lower() + extra[1:]
            else:
                chunks.append(extra)
    if grounded.comes_to_shop is True:
        chunks.append("приедете в сервис")
    elif grounded.comes_to_shop is False:
        chunks.append("нужен выезд")
    if not chunks:
        return ""
    text = ". ".join(_cap(chunk.rstrip(".")) for chunk in chunks if chunk)
    if text[-1] not in ".!?":
        text += "."
    return text


def _correction_sentence(grounded: GroundedTurn, car: str) -> str:
    pieces: list[str] = []
    if car:
        if grounded.kept_year and grounded.year:
            pieces.append(f"Хорошо, {car}, год тот же")
        else:
            pieces.append(f"Хорошо, теперь {car}")
    if grounded.city and (not car or grounded.city not in car):
        pieces.append(grounded.city)
    if not pieces:
        head = "Хорошо, поправку принял."
    else:
        head = ", ".join(pieces)
        head = head if head.endswith(".") else head + "."
    extra: list[str] = []
    if grounded.symptom:
        extra.append(_cap(grounded.symptom).rstrip("."))
    elif grounded.service:
        extra.append(_cap(grounded.service).rstrip("."))
    if not extra:
        return head
    return head + " " + ". ".join(extra) + "."


def _has_shop_question(reading: TurnReading, grounded: GroundedTurn) -> bool:
    return bool(
        grounded.asks_equipment or grounded.price_asked or reading.asks_price
        or grounded.booking_asked or reading.asks_booking or reading.asks_availability
        or grounded.asks_hours or getattr(reading, "asks_hours", False)
    )


def _direct_answer(
    reading: TurnReading,
    grounded: GroundedTurn,
    messages: list[dict[str, str]],
    retrieved: RetrievalResult | None,
    facts: dict | None = None,
) -> str:
    """The latest question, before any reminder of the job."""

    local = _unverified_local_job(reading, grounded, messages, retrieved, facts)
    if local:
        lines = [local]
        if reading.asks_availability or reading.asks_booking or grounded.booking_asked:
            lines.append(_booking_line(reading, messages))
        return " ".join(lines)
    lines: list[str] = []
    if grounded.asks_equipment:
        lines.append(_equipment_line(grounded, retrieved, messages))
    if _fresh_complaint(grounded):
        lines.append(_complaint_step(grounded))
    if grounded.stated_total is not None:
        lines.append(_sum_line(grounded.stated_total))
    elif reading.asks_price or grounded.price_asked:
        lines.append(_price_line(grounded, messages, retrieved, facts))
    if reading.asks_availability or reading.asks_booking or grounded.booking_asked:
        lines.append(_booking_line(reading, messages))
    if reading.asks_contact:
        lines.append(_contact_line(messages))
    elif reading.asks_workshop and grounded.comes_to_shop is None:
        lines.append("Конкретную мастерскую без списка не выбираю.")
    if grounded.asks_hours or getattr(reading, "asks_hours", False):
        lines.append(_hours_line())
    return " ".join(lines)


def _price_line(
    grounded: GroundedTurn,
    messages: list[dict[str, str]],
    retrieved: RetrievalResult | None,
    facts: dict | None,
) -> str:
    facts = facts or {}
    decided = price_text(messages, grounded, retrieved, facts)
    if decided:
        return decided
    price = facts.get("prices") or facts.get("price")
    car = grounded.vehicle_phrase()
    known = bool(grounded.model or grounded.make or grounded.stated_vehicle)
    if isinstance(price, str) and price.strip():
        text = price.strip()
        if car and car.casefold() not in text.casefold():
            return text.rstrip(".") + f" Это для {car}."
        return text
    if car:
        limit = f"Точной цены для {car} здесь нет."
    else:
        limit = "Точной цены здесь нет."
    # A vague extra already needs its own question. That is the one next step.
    offer = "" if grounded.open_extra else price_limitation_offer(facts, known)
    if offer:
        return f"{limit} {offer}"
    return limit


def _booking_line(reading: TurnReading, messages: list[dict[str, str]]) -> str:
    facts = verified_business() or {}
    slot = facts.get("availability")
    if slot:
        return str(slot)
    if reading.asks_booking and _time_followup(messages):
        return "Время услышал, но свободного окна отсюда не видно, поэтому запись не подтверждаю."
    return "Свободное окно отсюда не видно, поэтому запись не подтверждаю."


def _hours_line() -> str:
    facts = verified_business() or {}
    hours = facts.get("hours")
    if hours:
        return str(hours)
    return "Графика работы, в том числе на воскресенье, у меня нет."


def _equipment_line(
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None,
    messages: list[dict[str, str]],
) -> str:
    """Stock is a verified fact. A catalog row only names the kind of work."""

    facts = verified_business() or {}
    inventory = facts.get("equipment")
    if inventory is None:
        inventory = facts.get("inventory")
    label = grounded.equipment_item or "это"
    if isinstance(inventory, str) and inventory.strip():
        return inventory.strip()
    if isinstance(inventory, dict):
        for key, value in inventory.items():
            if label.casefold()[:6] in f"{key} {value}".casefold():
                return f"{_cap(label)}: {value}."
    if isinstance(inventory, (list, tuple)):
        for entry in inventory:
            if label.casefold()[:6] in str(entry).casefold():
                return f"{_cap(label)} в наличии есть."
    locative = _customer_locative(messages, grounded.city)
    where = f" в сервисе {locative}" if locative else ""
    stock = f"{_cap(label)} в наличии{where} отсюда не подтверждается."
    named = confident_service(retrieved)
    if named is None:
        return stock
    haystack = f"{named.title} {grounded.service or ''}".casefold()
    kind = "проверка" if "провер" in haystack else "работа"
    return f"{stock} В каталоге есть такая {kind}."


def _sum_line(total: int) -> str:
    shown = f"{total:,}".replace(",", " ")
    return f"По названным суммам вместе выходит {shown}."


def _contact_line(messages: list[dict[str, str]]) -> str:
    """Use a verified number. Ask which workshop only when the answer picks one."""

    entries = _contact_entries(verified_business() or {})
    if not entries:
        return "Номера телефона у меня нет."
    if len(entries) == 1:
        return _phone_sentence(entries[0])
    named = [entry for entry in entries if entry.get("workshop")]
    if len(named) < 2 or len({entry["workshop"].casefold() for entry in named}) < 2:
        phones = ", ".join(entry["phone"] for entry in entries)
        return f"Телефоны: {phones}."
    blob = " ".join(item.get("text") or "" for item in messages if item.get("role") == "user").casefold()
    matched = [entry for entry in named if entry["workshop"].casefold() in blob]
    if len(matched) == 1:
        return _phone_sentence(matched[0])
    choices = " или ".join(entry["workshop"] for entry in named)
    return f"Телефон зависит от мастерской. Какая: {choices}?"


def _phone_sentence(entry: dict[str, str | None]) -> str:
    workshop = entry.get("workshop")
    phone = entry.get("phone") or ""
    if isinstance(workshop, str) and workshop.strip():
        return f"Телефон {workshop.strip()}: {phone}."
    return f"Телефон: {phone}."


def _contact_entries(facts: dict[str, Any]) -> list[dict[str, str | None]]:
    raw = facts.get("contacts")
    if raw is None:
        raw = facts.get("workshops")
    if raw is None:
        raw = facts.get("phones")
    entries = _coerce_contacts(raw)
    if entries:
        return entries
    phone = facts.get("phone") or facts.get("telephone")
    if isinstance(phone, str) and phone.strip():
        return [{"workshop": None, "phone": phone.strip()}]
    return []


def _coerce_contacts(raw: Any) -> list[dict[str, str | None]]:
    if isinstance(raw, str) and raw.strip():
        return [{"workshop": None, "phone": raw.strip()}]
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str | None]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            entries.append({"workshop": None, "phone": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        phone = item.get("phone") or item.get("telephone") or item.get("tel")
        if not isinstance(phone, str) or not phone.strip():
            continue
        name = item.get("workshop") or item.get("name") or item.get("title")
        workshop = name.strip() if isinstance(name, str) and name.strip() else None
        entries.append({"workshop": workshop, "phone": phone.strip()})
    return entries


def _spoken_place(grounded: GroundedTurn, locative: str | None) -> str:
    if locative:
        return f", {locative}"
    if grounded.city and _known_city_label(grounded.city):
        return f", {grounded.city}"
    return ""


def _customer_locative(messages: list[dict[str, str]], city: str | None) -> str | None:
    """Reuse the customer's own «в …» phrase. Do not invent an ending."""

    if not city:
        return None
    target = city.casefold().replace("ё", "е")
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        for match in re.finditer(r"(?iu)\bв\s+([а-яёa-z-]{4,})", message.get("text") or ""):
            word = match.group(1)
            folded = word.casefold().replace("ё", "е")
            if folded == target or _place_from_token(folded) == city:
                return f"в {word}"
    return None


def _unverified_local_job(
    reading: TurnReading,
    grounded: GroundedTurn,
    messages: list[dict[str, str]],
    retrieved: RetrievalResult | None,
    facts: dict | None = None,
) -> str | None:
    """A catalog job is not proof that this workshop can do it or what it costs."""

    if grounded.urgent or not _asks_local_capability(messages, grounded):
        return None
    price = bool(reading.asks_price or grounded.price_asked)
    if not price:
        return None
    facts = facts or {}
    if facts.get("prices") or facts.get("price"):
        return None
    named = confident_service(retrieved)
    locative = _customer_locative(messages, grounded.city)
    if locative:
        place = f" {locative}"
    elif grounded.city:
        place = f" в {grounded.city}"
    else:
        place = ""
    if named is None or not named.title.strip():
        return (
            f"Смогут ли сделать эту работу{place} и сколько она будет стоить, "
            "в данных нет. Если хотите, составлю сообщение с просьбой полной сметы."
        )
    title = named.title.strip().rstrip(".")
    title = title[:1].lower() + title[1:]
    accusative, nominative = _job_pronoun(title)
    return (
        f"В каталоге есть {title}. "
        f"Смогут ли {accusative} сделать{place} и сколько {nominative} будет стоить, "
        "в данных нет. Если хотите, составлю сообщение с просьбой полной сметы."
    )


def _asks_local_capability(messages: list[dict[str, str]], grounded: GroundedTurn) -> bool:
    latest = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            latest = message.get("text") or ""
            break
    folded = latest.casefold().replace("ё", "е")
    if not re.search(r"можно|сможете|можете|сумеете|получится|выполнит|сделаете|возможность", folded):
        return False
    if not re.search(r"провер|сдела|посмотр|диагност", folded):
        return False
    return bool(grounded.city or re.search(r"у\s+вас", folded))


def _job_pronoun(title: str) -> tuple[str, str]:
    folded = title.casefold()
    if folded.startswith(("провер", "замен", "диагност", "эндоскоп", "регулир", "установ")):
        return "её", "она"
    return "это", "это"


def _fresh_complaint(grounded: GroundedTurn) -> bool:
    return bool(
        grounded.asks_equipment and grounded.equipment_item and grounded.fresh_symptom and grounded.symptom
    )


def _complaint_step(grounded: GroundedTurn) -> str:
    """Name the new complaint's next step. Do not paste the customer's sentence."""

    symptom = (grounded.symptom or "").casefold().replace("ё", "е")
    car = grounded.vehicle_phrase()
    side = ""
    if "слева" in symptom:
        side = " слева"
    elif "справа" in symptom:
        side = " справа"
    knock = "стуч" in symptom or "стук" in symptom
    if knock and ("подвеск" in symptom or "ходовк" in symptom):
        if car:
            head = f"На {car} новый стук в подвеске{side} лучше послушать на месте."
        else:
            head = f"Новый стук в подвеске{side} лучше послушать на месте."
        return head + " Это на ходу или когда машина стоит?"
    if knock:
        if car:
            head = f"На {car} новый стук{side} лучше послушать на месте."
        else:
            head = f"Новый стук{side} лучше послушать на месте."
        return head + " Это на ходу или когда машина стоит?"
    where = f" на {car}" if car else ""
    return f"Это отдельная неисправность{where}. Когда она проявляется?"


def _context_still_needed(
    reading: TurnReading,
    grounded: GroundedTurn,
    messages: list[dict[str, str]],
    direct: str,
) -> bool:
    """Keep a fact that the latest answer does not already say."""

    folded_direct = direct.casefold()
    if "в каталоге есть" in folded_direct or "уточнить в сервисе" in folded_direct:
        return False
    if _fresh_complaint(grounded):
        return False
    if not direct or grounded.correction or grounded.unclear_referent or grounded.brand_raw or grounded.open_extra:
        return True
    if grounded.symptom and not _covered(grounded.symptom, direct.casefold()):
        return True
    if grounded.detail and not _covered(grounded.detail, direct.casefold()):
        return True
    if grounded.asks_equipment:
        return False
    service = grounded.service or ""
    if not service:
        return False
    latest = messages[-1].get("text") or ""
    if _covered(service, latest.casefold()) or _covered(service, direct.casefold()):
        return False
    return bool(reading.asks_price or grounded.price_asked or reading.asks_booking or grounded.booking_asked)


def _safety(kind: str) -> str:
    if kind == "misfuel":
        return "Не заводите двигатель и не крутите стартер. Нужна эвакуация: топливо из бака сливают в сервисе."
    if kind == "overheat":
        return "Остановитесь и заглушите двигатель. Крышку системы охлаждения на горячую не открывайте."
    if kind == "brakes":
        return "Не продолжайте поездку. Остановитесь в безопасном месте и вызывайте эвакуатор."
    return "Сначала остановитесь в безопасном месте."


def _follow_up(grounded: GroundedTurn, reading: TurnReading, policy: Any | None) -> str | None:
    if grounded.open_extra:
        return "Что именно ещё посмотреть?"
    if (
        grounded.asks_equipment or grounded.asks_hours or getattr(reading, "asks_hours", False)
        or reading.asks_contact or reading.out_of_scope or grounded.stated_total is not None
    ):
        return None
    price = reading.asks_price or grounded.price_asked
    booking = reading.asks_availability or reading.asks_booking or grounded.booking_asked
    known = bool(grounded.model or grounded.make or grounded.stated_vehicle)
    if price or booking:
        if price and not known:
            return "На какую машину это считать?"
        return None
    return _one_question(grounded, reading, policy)


def _time_followup(messages: list[dict[str, str]]) -> bool:
    if len(messages) < 3:
        return False
    latest = (messages[-1].get("text") or "").casefold().replace("ё", "е")
    if "запис" in latest:
        return False
    return bool(re.search(r"час|утр|вечер|\bна\s+\d", latest))


def _one_question(grounded: GroundedTurn, reading: TurnReading, policy: Any | None) -> str | None:
    if grounded.unclear_referent:
        return "Что именно уже не работает?"
    if grounded.brand_raw and not grounded.model:
        return "Напишите марку ещё раз и, если знаете, модель."
    if grounded.asks_hours:
        return None
    known_car = grounded.model or grounded.make or grounded.stated_vehicle
    if (grounded.service or reading.asks_price or grounded.price_asked) and not known_car:
        return "На какую машину это считать?"
    if (
        not grounded.model and not grounded.stated_vehicle
        and (grounded.make or grounded.year) and not grounded.symptom and not grounded.service
    ):
        return "Какая модель?"
    if grounded.make and not grounded.model and not grounded.stated_vehicle and (grounded.service or grounded.symptom):
        return "Какая модель?"
    if (
        grounded.symptom and not grounded.service and not grounded.make and not grounded.model
        and not grounded.stated_vehicle and not grounded.asks_advice
    ):
        return "Какая машина?"
    symptom = (grounded.symptom or "").casefold()
    if "стартер" in symptom and "крутит" in symptom and not grounded.service:
        return "Машина при этом заводится?"
    follow = getattr(policy, "follow_up_question", None) if policy is not None else None
    if not isinstance(follow, str) or follow.count("?") != 1:
        return None
    folded = follow.casefold()
    if any(label in folded for label in ("сведение", "complaint", "жалоба «")):
        return None
    if _GENERIC_CONTEXT in folded:
        return None
    if grounded.vehicle_phrase() and "какая машина" in folded:
        return None
    if grounded.city and "город" in folded:
        return None
    if grounded.symptom and "что именно происходит" in folded:
        return None
    return follow


def _polish_customer(text: str) -> str:
    cleaned = " ".join(text.replace("ё", "е").split()).strip(" .,!?:;—-")
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = re.sub(r"(?i)^(?:ну|а|если|ещё|еще|просто|в\s+смысле|то\s+есть)\s+", "", cleaned).strip()
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _cap(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return cleaned
    return cleaned[0].upper() + cleaned[1:]


def _tidy_reply(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = cleaned.replace(" ,", ",").replace(" .", ".")
    cleaned = re.sub(r"\.\.+", ".", cleaned)
    cleaned = re.sub(r"\s+([,.])", r"\1", cleaned)
    return cleaned.strip()
