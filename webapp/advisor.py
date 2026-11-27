"""One next step for a Russian service-advisor reply.

The latest question is answered first. A workshop is "ours" only when the
configured facts name one shop and the requested work is listed there.
A catalog row is not that list. An invitation is not an appointment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from webapp.grounding import GroundedTurn, _requests_work
from webapp.retrieval import RetrievalResult, confident_service
from webapp.turn_reading import TurnReading


_FOLD_FIX = re.compile(r"(.)\1{2,}")
_TOKEN = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
_OFFER_CUES = ("могу", "хотите", "давайте", "составить", "составлю", "подготов", "написать за вас", "нужно ли")
_ACCEPT_HEAD = {"да", "давайте", "давай", "хорошо", "ага", "ладно", "ок", "угу"}
_IDLE_IDS = frozenset({"throttle-cleaning-change", "throttle-adaptation", "intake-smoke-test"})
_DISPLACEMENT = re.compile(r"\b(\d)[,.](\d)\b")
_INCLUSION = re.compile(
    r"что входит|входит в|что включ|из чего состо|в стоимость входит|входит в стоимость"
)
_CAPABILITY = re.compile(
    r"делаете|меняете|выполняете|сможете|можете ли|у вас есть|есть ли у вас"
)
_PRICE = re.compile(r"сколько|стоим|цен|прайс|почем|почём")


def _fold(text: str) -> str:
    return _FOLD_FIX.sub(r"\1\1", (text or "").casefold().replace("ё", "е"))


def _latest(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("text") or ""
    return ""


def pending_sentence(messages: list[dict[str, str]]) -> str:
    """The assistant's last offer or question, from the message the customer saw."""

    if len(messages) < 2 or messages[-2].get("role") != "assistant":
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", (messages[-2].get("text") or "").strip())
    for sentence in reversed(sentences):
        folded = re.sub(r"\bне\s+(?:могу|можем|нужно ли)\b", " ", _fold(sentence))
        if sentence.endswith("?") or any(cue in folded for cue in _OFFER_CUES):
            return sentence.strip()[:300]
    return ""


def offer_kind(sentence: str) -> str:
    """draft, address, visit, question, other, or empty."""

    if not sentence:
        return ""
    folded = _fold(sentence)
    if any(word in folded for word in ("составлю", "составить", "сообщен")):
        return "draft"
    if "адрес" in folded and any(
        word in folded for word in ("напиш", "скаж", "дам", "назов", "присл", "хотите", "могу", "давайте")
    ):
        return "address"
    if any(word in folded for word in ("подъехать", "приезжайте", "приехать к нам", "к нам")):
        return "visit"
    if sentence.strip().endswith("?"):
        return "question"
    if any(word in folded for word in ("могу", "хотите", "давайте")):
        return "other"
    return ""


def is_acceptance(text: str) -> bool:
    tokens = _TOKEN.findall(_fold(text))
    if not tokens or len(tokens) > 4 or tokens[0] not in _ACCEPT_HEAD:
        return False
    rest = [token for token in tokens[1:] if token not in {"пожалуйста", "давайте", "давай"}]
    if not rest:
        return True
    return all(token.startswith(("состав", "напиш")) or token == "адрес" for token in rest)


def is_inclusion(text: str) -> bool:
    return bool(_INCLUSION.search(_fold(text)))


def is_idle(text: str) -> bool:
    folded = _fold(text)
    return "плава" in folded and "оборот" in folded


def is_detail_answer(messages: list[dict[str, str]]) -> bool:
    if not _DISPLACEMENT.search(_latest(messages)):
        return False
    previous = ""
    for message in reversed(messages[:-1]):
        if message.get("role") == "assistant":
            previous = message.get("text") or ""
            break
    folded = _fold(previous)
    return "объем" in folded or "двигател" in folded


@dataclass(frozen=True)
class Shop:
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    hours: str | None = None
    service_ids: frozenset[str] = frozenset()
    service_titles: frozenset[str] = frozenset()
    represents: bool = False
    walk_in: bool | None = None

    def verified(self, service_id: str | None, title: str | None = None) -> bool:
        if not self.represents:
            return False
        if service_id and service_id in self.service_ids:
            return True
        folded = _fold(title or "")
        if folded and any(folded in item or item in folded for item in self.service_titles if item):
            return True
        return False


def read_shop(facts: dict | None) -> Shop:
    """One named workshop from the facts file. A phone list is not a shop we represent."""

    if not isinstance(facts, dict):
        return Shop()
    name = facts.get("workshop") if isinstance(facts.get("workshop"), str) else None
    if not name and isinstance(facts.get("name"), str):
        name = facts.get("name")
    shop_blob = facts.get("shop") if isinstance(facts.get("shop"), dict) else {}
    if not name and isinstance(shop_blob.get("name"), str):
        name = shop_blob.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else None
    address = _text(facts.get("address") or shop_blob.get("address"))
    phone = _text(facts.get("phone") or facts.get("telephone") or shop_blob.get("phone"))
    hours = _text(facts.get("hours") or shop_blob.get("hours"))
    walk = facts.get("walk_in", shop_blob.get("walk_in"))
    ids, titles = _listed_services(facts, shop_blob)
    prices = facts.get("prices")
    if isinstance(prices, dict):
        ids = ids | {key for key in prices if isinstance(key, str)}
    return Shop(
        name=name,
        address=address,
        phone=phone,
        hours=hours,
        service_ids=frozenset(ids),
        service_titles=frozenset(titles),
        represents=bool(name),
        walk_in=walk if isinstance(walk, bool) else None,
    )


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _listed_services(facts: dict, shop_blob: dict) -> tuple[set[str], set[str]]:
    raw = facts.get("services")
    if raw is None:
        raw = facts.get("service_ids") or shop_blob.get("services")
    ids: set[str] = set()
    titles: set[str] = set()
    if isinstance(raw, str) and raw.strip():
        raw = [raw]
    if not isinstance(raw, list):
        return ids, titles
    for item in raw:
        if isinstance(item, str) and item.strip():
            token = item.strip()
            if " " in token or any("а" <= char <= "я" for char in token.casefold()):
                titles.add(_fold(token))
            else:
                ids.add(token)
    return ids, titles


def _candidates(text: str) -> list[tuple[str, str]]:
    from webapp.reply_writer import catalog_candidates

    return catalog_candidates(text, limit=2)


def _job(messages: list[dict[str, str]], grounded: GroundedTurn, retrieved: RetrievalResult | None) -> tuple[str | None, str]:
    strong = confident_service(retrieved)
    if strong is not None and strong.title.strip():
        return strong.service_id, _lower_title(strong.title)
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        text = message.get("text") or ""
        if is_acceptance(text) or _detail_only(text):
            continue
        found = _candidates(text)
        if found:
            return found[0][0], _lower_title(found[0][1])
    if grounded.service:
        return None, grounded.service
    return None, "работа по автомобилю"


def _detail_only(text: str) -> bool:
    tokens = _TOKEN.findall(_fold(text))
    return bool(_displacement(text) and len(tokens) <= 4)


def _lower_title(title: str) -> str:
    cleaned = title.strip().rstrip(".")
    if not cleaned:
        return "работа по автомобилю"
    return cleaned[:1].lower() + cleaned[1:]


def _usual_parts(blob: str) -> list[str]:
    folded = _fold(blob)
    if "масл" in folded:
        return ["масло", "фильтр", "работа"]
    if "колод" in folded:
        return ["колодки", "работа"]
    return ["запчасти", "работа"]


def _price_entry(facts: dict, service_id: str | None) -> dict | None:
    prices = facts.get("prices")
    if isinstance(prices, dict) and service_id and isinstance(prices.get(service_id), dict):
        return prices[service_id]
    if isinstance(prices, str) and prices.strip():
        includes = facts.get("includes")
        return {"amount": prices.strip(), "includes": includes if isinstance(includes, list) else []}
    price = facts.get("price")
    if isinstance(price, str) and price.strip():
        includes = facts.get("includes")
        return {"amount": price.strip(), "includes": includes if isinstance(includes, list) else []}
    return None


def _displacement(text: str) -> str | None:
    found = _DISPLACEMENT.search(text or "")
    if not found:
        return None
    return f"{found.group(1)}.{found.group(2)}"


def _quote_name(job: str) -> str:
    folded = _fold(job)
    if "масл" in folded:
        return "замену масла"
    if "колод" in folded:
        return "замену колодок"
    return "эту работу"


def _topic_name(job: str) -> str:
    """Dative, for «переходим к …»."""

    folded = _fold(job)
    if "масл" in folded:
        return "замене масла"
    if "колод" in folded:
        return "замене колодок"
    return "этой работе"


_GENITIVE = {
    "масло": "масла",
    "фильтр": "фильтра",
    "работа": "работы",
    "колодки": "колодок",
    "запчасти": "запчастей",
}


def _includes_text(parts: list[str], genitive: bool = False) -> str:
    shown = [_GENITIVE.get(part, part) if genitive else part for part in parts]
    if len(shown) == 1:
        return shown[0]
    if not shown:
        return ""
    return ", ".join(shown[:-1]) + " и " + shown[-1]


def _confirmed(parts: list[str], entry: dict | None) -> tuple[list[str], list[str]]:
    raw = entry.get("includes") if isinstance(entry, dict) else None
    if not isinstance(raw, list) or not raw:
        return [], parts
    blob = " ".join(str(item) for item in raw).casefold()
    yes = [part for part in parts if part[:4] in blob or part in blob]
    no = [part for part in parts if part not in yes]
    return yes, no


def _offer_draft() -> str:
    return "Если хотите, составлю сообщение с просьбой полной сметы."


def _offer_phone(shop: Shop) -> str | None:
    if shop.phone:
        return f"Уточнить полную смету можно по телефону {shop.phone}."
    return None


def _one_price_offer(shop: Shop) -> str:
    return _offer_phone(shop) or _offer_draft()


def _lead(reading: TurnReading) -> str:
    if reading.greeting and not reading.social_only:
        return "Здравствуйте. "
    return ""


def _car_city(grounded: GroundedTurn) -> str:
    return ", ".join(part for part in (grounded.vehicle_phrase(), grounded.city) if part)


def switch_reply(
    messages: list[dict[str, str]],
    reading: TurnReading,
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None,
    facts: dict | None,
) -> str | None:
    """The new job after a symptom, with the car kept and one next step."""

    if not symptom_dropped(messages, grounded):
        return None
    latest = _latest(messages)
    folded = _fold(latest)
    if is_inclusion(latest) or _PRICE.search(folded) or is_idle(latest):
        return None
    service_id, job = _job(messages, grounded, retrieved)
    where = _car_city(grounded)
    name = _quote_name(job)
    head = f"Переходим к {_topic_name(job)}"
    if where:
        head += f" ({where})"
    head += "."
    shop = read_shop(facts)
    priced = price_text(messages, grounded, retrieved, facts)
    if priced:
        return _lead(reading) + head + " " + priced
    parts = _usual_parts(f"{latest} {job}")
    entry = _price_entry(facts or {}, service_id)
    if shop.represents and shop.verified(service_id, job) and not entry:
        invite = f" Можете подъехать к нам на {name}."
        if shop.address:
            invite += f" Адрес: {shop.address}."
        if shop.walk_in is not True:
            invite += (
                " Это приглашение, не запись; свободное окно отсюда не видно, "
                "поэтому не обещаю, что вас примут сразу."
            )
        return _lead(reading) + head + invite
    body = f" Смета обычно состоит из {_includes_text(parts, genitive=True)}."
    confirmed, missing = _confirmed(parts, entry if shop.represents else None)
    if shop.represents and confirmed and not missing:
        body += f" Для {shop.name} это подтверждено: {_includes_text(confirmed)}."
        return _lead(reading) + head + body
    if shop.represents and confirmed:
        body += (
            f" Для {shop.name} подтверждено: {_includes_text(confirmed)}. "
            f"Не подтверждено: {_includes_text(missing)}."
        )
    elif shop.represents:
        body += f" Для {shop.name} состав строк не подтверждён."
    else:
        body += " Какие из этих строк подтверждены для конкретной мастерской, отсюда не видно."
    return _lead(reading) + head + body + " " + _offer_draft()


def symptom_dropped(messages: list[dict[str, str]], grounded: GroundedTurn) -> bool:
    """The latest line asks for a new job and does not repeat the old complaint."""

    symptom = grounded.symptom or ""
    if not symptom:
        return False
    latest = _fold(_latest(messages))
    stems = [token for token in _TOKEN.findall(_fold(symptom)) if len(token) >= 4]
    if any(stem[:5] in latest for stem in stems):
        return False
    return bool(_requests_work(latest))


def acceptance_reply(
    messages: list[dict[str, str]],
    reading: TurnReading,
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None,
    facts: dict | None,
) -> str | None:
    latest = _latest(messages)
    if not is_acceptance(latest):
        return None
    kind = offer_kind(pending_sentence(messages))
    shop = read_shop(facts)
    if kind == "draft":
        return _draft_reply(messages, grounded, retrieved)
    if kind == "address":
        if shop.address:
            return f"Адрес: {shop.address}."
        return "Проверенного адреса нет, поэтому я его не называю."
    if kind == "visit":
        lines = [
            "Хорошо. Приехать можно, но это не запись: свободное окно отсюда не видно, "
            "поэтому не обещаю, что вас примут сразу."
        ]
        if shop.address:
            lines.append(f"Адрес: {shop.address}.")
        return " ".join(lines)
    if kind == "question":
        return "Это не ответ на вопрос. Напишите, пожалуйста, чуть конкретнее."
    if kind == "other":
        return "Хорошо. Запись этим не подтверждаю. Напишите, что именно сделать."
    if grounded.service or grounded.symptom or grounded.vehicle_phrase() or grounded.city:
        return "Хорошо. Запись этим не подтверждаю. Напишите, что сделать дальше."
    del reading
    return None


def _draft_reply(
    messages: list[dict[str, str]],
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None,
) -> str:
    _service_id, job = _job(messages, grounded, retrieved)
    who = _car_city(grounded)
    bits = ["Здравствуйте."]
    if who:
        bits.append(who + ".")
    symptom = grounded.symptom or ""
    latest_job = ""
    for message in reversed(messages):
        if message.get("role") == "user" and not is_acceptance(message.get("text") or ""):
            latest_job = message.get("text") or ""
            break
    if symptom and not _requests_work(_fold(latest_job)) and "масл" not in _fold(job):
        bits.append(symptom[:1].upper() + symptom[1:].rstrip(".") + ".")
        bits.append("Прошу посмотреть это на месте и сообщить, сколько это будет стоить.")
    else:
        bits.append(f"Нужна {job}.")
        bits.append("Прошу сообщить полную смету: что входит и сколько это будет стоить.")
    return "Готово, можно скопировать и отправить: «" + " ".join(bits) + "»"


def inclusion_reply(
    messages: list[dict[str, str]],
    reading: TurnReading,
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None,
    facts: dict | None,
) -> str | None:
    latest = _latest(messages)
    if not is_inclusion(latest):
        return None
    service_id, job = _job(messages, grounded, retrieved)
    blob = f"{latest} {job}"
    parts = _usual_parts(blob)
    shop = read_shop(facts)
    entry = _price_entry(facts or {}, service_id)
    confirmed, missing = _confirmed(parts, entry if shop.represents else None)
    where = _car_city(grounded)
    head = f"Смета на {_quote_name(job)}"
    if where:
        head += f" ({where})"
    head += f" обычно состоит из {_includes_text(parts, genitive=True)}."
    if shop.represents and confirmed and not missing:
        middle = f"Для {shop.name} это подтверждено: {_includes_text(confirmed)}."
        tail = ""
    elif shop.represents and confirmed:
        middle = (
            f"Для {shop.name} подтверждено: {_includes_text(confirmed)}. "
            f"Не подтверждено: {_includes_text(missing)}."
        )
        tail = " " + _offer_draft()
    elif shop.represents:
        middle = f"Для {shop.name} состав строк не подтверждён."
        tail = " " + _offer_draft()
    else:
        middle = "Какие из этих строк подтверждены для конкретной мастерской, отсюда не видно."
        tail = " " + _offer_draft()
    return _lead(reading) + head + " " + middle + tail


def idle_reply(
    messages: list[dict[str, str]],
    reading: TurnReading,
    grounded: GroundedTurn,
    facts: dict | None,
) -> str | None:
    latest = _latest(messages)
    if not is_idle(latest) or grounded.urgent:
        return None
    if _requests_work(_fold(latest)) and re.search(r"масл|колод", _fold(latest)):
        return None
    who = _car_city(grounded)
    head = "На холостых плавают обороты"
    if who:
        head += f" — {who}"
    head += ". По переписке причину не назову."
    shop = read_shop(facts)
    if shop.represents and _idle_verified(shop):
        visit = (
            " Можете подъехать к нам на диагностику: на месте смотрят обороты, подсос и дроссельный узел."
        )
        if shop.address:
            visit += f" Адрес: {shop.address}."
        if shop.phone:
            visit += f" Телефон: {shop.phone}."
        if shop.hours:
            visit += f" График: {shop.hours}."
        if shop.walk_in is True:
            visit += " Это приглашение, не запись."
        else:
            visit += (
                " Это приглашение, не запись; свободное окно отсюда не видно, "
                "поэтому не обещаю, что вас примут сразу."
            )
        return _lead(reading) + head + visit
    return _lead(reading) + head + " Если хотите, составлю сообщение в сервис с этим симптомом."


def _idle_verified(shop: Shop) -> bool:
    if shop.service_ids & _IDLE_IDS:
        return True
    blob = " ".join(shop.service_titles)
    return "дроссел" in blob or "холост" in blob


def capability_reply(
    messages: list[dict[str, str]],
    reading: TurnReading,
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None,
    facts: dict | None,
) -> str | None:
    latest = _latest(messages)
    folded = _fold(latest)
    if is_inclusion(latest) or _PRICE.search(folded) or is_idle(latest):
        return None
    if not _asks_capability(folded):
        return None
    shop = read_shop(facts)
    service_id, job = _job(messages, grounded, retrieved)
    if not shop.verified(service_id, job):
        return None
    del reading
    shown = job[:1].upper() + job[1:]
    return f"Да, делаем: {shown}."


def price_text(
    messages: list[dict[str, str]],
    grounded: GroundedTurn,
    retrieved: RetrievalResult | None,
    facts: dict | None,
) -> str | None:
    """A verified price, the one missing engine detail, or None to keep the old line."""

    facts = facts or {}
    service_id, job = _job(messages, grounded, retrieved)
    entry = _price_entry(facts, service_id)
    if not isinstance(entry, dict):
        return None
    shop = read_shop(facts)
    includes = entry.get("includes") if isinstance(entry.get("includes"), list) else []
    cover = _includes_text([str(item) for item in includes]) if includes else ""
    amounts = entry.get("amounts") if isinstance(entry.get("amounts"), dict) else None
    if entry.get("depends_on") and isinstance(amounts, dict):
        detail = _displacement(_latest(messages)) or _displacement(
            " ".join(item.get("text") or "" for item in messages if item.get("role") == "user")
        )
        if not detail:
            return f"Цена на {_quote_name(job)} зависит от объёма двигателя. Какой объём?"
        amount = amounts.get(detail)
        if not amount:
            limit = f"Для объёма {detail} цены на {job} в данных нет."
            return limit + " " + _one_price_offer(shop)
        text = f"Для объёма {detail} {job} — {amount}."
        if cover:
            text += f" В эту сумму входят {cover}."
        return text
    amount = entry.get("amount")
    if isinstance(amount, str) and amount.strip():
        text = f"{job[:1].upper() + job[1:]} — {amount.strip()}."
        if cover:
            text += f" В эту сумму входят {cover}."
        else:
            text += " Что именно входит в эту сумму, в данных не сказано."
        return text
    return None


def price_limitation_offer(facts: dict | None, car_known: bool) -> str:
    """One useful step after saying the price is not on file. Empty if the car is still unknown."""

    if not car_known:
        return ""
    return _one_price_offer(read_shop(facts))


def topic_service(messages: list[dict[str, str]]) -> str | None:
    """Catalog id of the current job, taken from the customer's own latest job words."""

    from webapp.reply_writer import _stems

    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        text = message.get("text") or ""
        if is_acceptance(text):
            continue
        found = _candidates(text)
        if not found:
            continue
        service_id, title = found[0]
        if set(_stems(text, expand=False)) & set(_stems(title, expand=False)):
            return service_id
    return None


def annotate(ctx: Any) -> Any:
    """Tell the writer the same rule the fallback will enforce."""

    facts = ctx.business_facts if isinstance(ctx.business_facts, dict) else None
    shop = read_shop(facts)
    latest = ctx.latest or ""
    if ctx.customer_need and not ctx.dropped_symptom and _need_left_behind(latest, ctx.customer_need):
        ctx.dropped_symptom = ctx.customer_need
        ctx.customer_need = ""
        if ctx.candidates and not ctx.switched_to:
            ctx.switched_to = ctx.candidates[0]
    folded = _fold(latest)
    notes: list[str] = []
    ctx.represents_shop = False
    ctx.required_groups = ()
    ctx.forbid_fragments = ()
    if is_inclusion(latest):
        if "масл" in folded:
            ctx.required_groups = (("масл",), ("фильтр",), ("работ",))
        elif "колод" in folded:
            ctx.required_groups = (("колод",), ("работ",))
        else:
            ctx.required_groups = (("запчаст", "работ"),)
        ctx.forbid_fragments = (
            "точн", "уточнить в сервисе", "уточните в сервисе", "у сервиса",
        )
        if not shop.represents:
            ctx.required_groups = tuple(ctx.required_groups) + (("составлю", "составить"),)
        notes.append(
            "Сначала назови, из чего состоит смета, и какие строки подтверждены фактами. "
            "Не подменяй ответ фразой, что цены нет. Если строки не подтверждены, в конце "
            "одно предложение: предложи составить сообщение с просьбой полной сметы."
        )
    elif is_idle(latest) and not getattr(ctx, "dropped_symptom", ""):
        ctx.required_groups = (("плава", "оборот"), ("причин",))
        ctx.forbid_fragments = (
            "причина точно", "однозначно", "уточнить в сервисе", "нужно очист", "нужно заменить",
        )
        if shop.represents and _idle_verified(shop):
            ctx.represents_shop = True
            notes.append(
                "Причину не утверждай. Можно пригласить: «подъехать к нам на диагностику», "
                "и объяснить, что смотрят на месте. Это не запись. "
                "Если приём без записи неизвестен, не обещай, что клиента примут сразу."
            )
            if shop.address:
                notes.append(f"Адрес можно назвать только так: {shop.address}.")
        else:
            ctx.required_groups = tuple(ctx.required_groups) + (("составлю", "составить"),)
            notes.append(
                "Причину не утверждай. Не пиши «к нам» и не отправляй клиента в путь. "
                "Предложи составить сообщение в сервис с этим симптомом."
            )
    elif is_acceptance(latest):
        kind = offer_kind(ctx.pending)
        if kind == "draft":
            ctx.required_groups = (("«", "здравствуйте"),)
            notes.append(
                "Клиент согласился на текст. Сразу напиши готовое сообщение в кавычках «»: "
                "машина, город и работа. Не обещай сделать это потом и не записывай."
            )
        elif kind == "address":
            notes.append("Клиент попросил адрес. Назови только проверенный адрес. Не записывай.")
        elif kind == "visit":
            notes.append("«Да» не подтверждает запись. Скажи, что это приглашение и окно не подтверждено.")
        else:
            notes.append("Предложения записать клиента не было. «Да» не означает запись.")
    elif _PRICE.search(folded):
        service_id = ctx.candidates[0][0] if ctx.candidates else None
        entry = _price_entry(facts or {}, service_id)
        if isinstance(entry, dict) and entry.get("depends_on") and not _displacement(latest):
            ctx.required_groups = (("объем", "объём"),)
            amounts = entry.get("amounts") if isinstance(entry.get("amounts"), dict) else {}
            banned = []
            for amount in amounts.values():
                banned.extend(re.findall(r"\d+", str(amount)))
            ctx.forbid_fragments = tuple(dict.fromkeys(banned))
            notes.append(
                "Цена зависит от объёма двигателя. Спроси только объём. "
                "Суммы не называй, пока объём не известен."
            )
        elif isinstance(entry, dict) and isinstance(entry.get("amount"), str):
            digits = "".join(re.findall(r"\d+", entry["amount"]))
            if digits:
                ctx.required_groups = ((digits,),)
            notes.append(f"Назови цену {entry['amount']} и что в неё входит. Не предлагай запись.")
        else:
            ctx.required_groups = (("составлю", "телефон"),)
            notes.append(
                "Точной цены в данных нет. Скажи это коротко и предложи одно: "
                "проверенный телефон или готовое сообщение с просьбой полной сметы."
            )
    elif _pure_capability(latest) and shop.represents:
        service_id = ctx.candidates[0][0] if ctx.candidates else None
        title = ctx.candidates[0][1] if ctx.candidates else ""
        if shop.verified(service_id, title):
            ctx.represents_shop = True
            ctx.required_groups = (("да",),)
            ctx.forbid_fragments = ("составлю", "составить", "подъехать", "?", "какой", "цен")
            notes.append("Ответь прямо, делаете ли эту работу, и закончи. Не добавляй вопрос, приглашение и черновик.")
    if getattr(ctx, "dropped_symptom", ""):
        kept = []
        car = (ctx.vehicle or "").split(",")[0].strip().split(" ")
        if car and car[0]:
            kept.append((car[0].casefold(),))
        city = _fold(ctx.city or "")
        if len(city) >= 4:
            kept.append((city[:5],))
        covered = is_inclusion(latest) or bool(_PRICE.search(folded)) or is_idle(latest)
        if not covered:
            if "масл" in folded:
                kept.append(("масл",))
            elif "колод" in folded:
                kept.append(("колод",))
            chosen = ctx.switched_to or (ctx.candidates[0] if ctx.candidates else None)
            service_id = chosen[0] if chosen else None
            title = chosen[1] if chosen else ""
            entry = _price_entry(facts or {}, service_id)
            if isinstance(entry, dict) and entry.get("depends_on") and not _displacement(latest):
                kept.append(("объем", "объём"))
            elif isinstance(entry, dict) and isinstance(entry.get("amount"), str):
                digits = "".join(re.findall(r"\d+", entry["amount"]))
                if digits:
                    kept.append((digits,))
            elif shop.represents and shop.verified(service_id, title):
                ctx.represents_shop = True
                kept.append(("подъехать", "к нам"))
            else:
                kept.append(("составлю", "составить"))
        if kept:
            ctx.required_groups = tuple(ctx.required_groups) + tuple(kept)
        notes.append(
            "Тема сменилась. Прежний симптом не упоминай. Машину и город сохрани. "
            "По новой работе дай один следующий шаг: объём, цену, приглашение или черновик."
        )
    if not notes:
        if shop.represents:
            notes.append(
                f"Ты представляешь «{shop.name}» только по услугам из фактов. "
                "Невыдуманные данные: "
                f"адрес {shop.address or 'нет'}, телефон {shop.phone or 'нет'}, часы {shop.hours or 'нет'}."
            )
        else:
            notes.append(
                "Конкретная мастерская не настроена. Не пиши «у нас» и «к нам», "
                "не выдумывай адрес и не отправляй клиента узнавать, делают ли услугу."
            )
    ctx.advisor_note = " ".join(notes)[:700]
    return ctx


def _need_left_behind(latest: str, need: str) -> bool:
    folded = _fold(latest)
    stems = [token for token in _TOKEN.findall(_fold(need)) if len(token) >= 4]
    if any(stem[:5] in folded for stem in stems):
        return False
    return bool(_requests_work(folded))


def _asks_capability(folded: str) -> bool:
    if not _CAPABILITY.search(folded) or _PRICE.search(folded):
        return False
    if _requests_work(folded):
        return True
    return bool(re.search(r"масл|колод|фильтр|шиномонтаж|грм|диагност", folded))


def _pure_capability(text: str) -> bool:
    return bool(_asks_capability(_fold(text)) and not is_inclusion(text))


def advisor_problem(text: str, ctx: Any) -> str | None:
    folded = _fold(text)
    dropped = getattr(ctx, "dropped_symptom", "") or ""
    if dropped:
        stems = [token for token in _TOKEN.findall(_fold(dropped)) if len(token) >= 5]
        if any(stem[:5] in folded for stem in stems):
            return "old_topic"
    for group in getattr(ctx, "required_groups", ()) or ():
        if not any(part in folded or part in text for part in group):
            return "missing_answer"
    for fragment in getattr(ctx, "forbid_fragments", ()) or ():
        if _fold(fragment) in folded:
            return "missing_answer"
    return None
