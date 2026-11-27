"""Facts a reply may state, taken from this customer's words.

Assistant replies and retrieved dialogues are not evidence. Extractor slots
fill a gap only when the customer's own words support them. A correction
replaces the slot it names. A year stays with a vehicle only when the
customer stated it for that vehicle or said the year is unchanged. The
service description does not carry the vehicle or the city.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any

from webapp.turn_reading import TurnReading, quoted_parts_labour_total


_TOKEN = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# "а" has to be its own word. Otherwise "когда" is split into "когд" + "а".
_PAIR = re.compile(
    r"не\s+([^,.!?;]{1,48}?)\s*,?\s+\bа\b\s+([^,.!?;]{1,48})",
    re.IGNORECASE,
)
_KEEP_YEAR = re.compile(
    r"год\w*\s+(?:тот\s+же|такой\s+же|не\s+меня\w*|прежний)|(?:тот\s+же|прежний)\s+год",
    re.IGNORECASE,
)
_VOWELS = set("aeiouyаеёиоуыэюя")
_PRONOUNS = {"он", "она", "оно", "они", "это"}
_AFFIRM = {"да", "нет", "ага", "угу", "неа", "ок", "ладно", "хорошо", "верно"}
_STOP = {
    "машина", "машину", "машине", "автомобиль", "автомобиля", "год", "года", "году",
    "это", "эта", "этот", "у", "меня", "мне", "мой", "моя", "про", "для", "или",
    "просто", "очень", "уже", "ещё", "еще", "только", "тоже", "когда", "если",
    "можно", "нужно", "надо", "хочу", "пожалуйста", "здравствуйте", "привет",
    "сколько", "стоит", "стоимость", "цена", "запись", "записаться", "приехать",
    "сервис", "работа", "работы", "ремонт", "замена", "поменять", "заменить",
    "снять", "поставить", "проверить", "диагностика", "сегодня", "завтра",
    "воскресенье", "суббота", "график", "масло", "масла", "маслу", "двигатель",
    "двигателя", "коробка", "коробки", "печка", "печки", "стартер", "стартера",
    "турбина", "турбину", "колодки", "колодок", "подвеска", "ходовка", "ходовку",
    "аккумулятор", "вентилятор", "вентилятора", "уровень", "норме", "холодным",
    "холодную", "постоянно", "утром", "колеса", "колес", "липучка", "передние",
    "задние", "сильно", "стрелка", "красной", "зоне", "греется", "стучит",
    "дымит", "крутит", "пинается", "орёт", "орет", "жрет", "жрёт", "подъедает",
    "постукивает", "не", "на", "по", "из", "от", "до", "же", "бы", "ли", "ну",
    "ой", "стоп", "ошибся", "перепутал", "другая", "другую", "другой",
    "бензин", "дизель", "гибрид", "автомат", "механика", "вариатор",
    "шиномонтаж", "развал", "город", "городе",
}
_SYMPTOM_CUES = (
    "жрет", "жрёт", "подъеда", "постуки", "стуч", "стук", "греет", "греется", "дым",
    "крутит", "не заводит", "не зовод", "пинает", "орёт", "орет", "дует",
    "пищит", "скрежет", "провалива", "плава", "мягк", "щелка", "щелкает", "шшёлка",
    "не работ", "не горит", "горит", "чек", "холодн", "перегре", "стучит",
    "гремит", "скрип", "течь", "течёт", "троит", "дерга", "вибри",
    "сдох", "разрядил", "не помога",
)
_PARTS = (
    "аккумулятор", "аккум", "стартер", "генератор", "печк", "вентилятор",
    "коробк", "двигател", "турбин", "колодк", "фар", "стекл", "кондицион",
    "подвеск", "ходовк", "радиатор", "свеч", "фильтр", "диск", "шина",
    "сцеплен", "глушител", "рул", "амортиз", "стойк", "ламп", "масл",
)
_ADVICE = ("ехать", "что делать", "опасно", "можно ли")
_PRICE_CUES = ("сколько", "стоим", "цена", "почем", "почём", "деньг", "выходит", "обойд")
_JOB_NOUNS = ("масл", "фильтр", "колодк", "шиномонтаж", "диагност")
_WORK_CUES = (
    "замен", "помен", "снять", "снят", "постав", "провер", "глян", "посмотр",
    "диагност", "ремонт", "перебор", "установ", "шиномонтаж", "развал",
    "балансир", "отрегул",
)
_CITIES = (
    ("великий новгород", "Великий Новгород"),
    ("нижний новгород", "Нижний Новгород"),
    ("санкт-петербург", "Санкт-Петербург"),
    ("петербург", "Санкт-Петербург"),
    ("екатеринбург", "Екатеринбург"),
    ("новосибирск", "Новосибирск"),
    ("нижневартовск", "Нижневартовск"),
    ("ростов", "Ростов-на-Дону"),
    ("красноярск", "Красноярск"),
    ("краснодар", "Краснодар"),
    ("калининград", "Калининград"),
    ("владивосток", "Владивосток"),
    ("челябинск", "Челябинск"),
    ("волгоград", "Волгоград"),
    ("казан", "Казань"),
    ("москв", "Москва"),
    ("псков", "Псков"),
    ("самар", "Самара"),
    ("уфа", "Уфа"),
    ("перм", "Пермь"),
    ("тюмен", "Тюмень"),
    ("омск", "Омск"),
    ("сочи", "Сочи"),
    ("воронеж", "Воронеж"),
    ("иркутск", "Иркутск"),
    ("барнаул", "Барнаул"),
    ("ижевск", "Ижевск"),
    ("хабаровск", "Хабаровск"),
    ("ярославл", "Ярославль"),
    ("владимир", "Владимир"),
    ("тольятти", "Тольятти"),
    ("рязан", "Рязань"),
    ("пенз", "Пенза"),
    ("киров", "Киров"),
    ("тула", "Тула"),
    ("курск", "Курск"),
    ("твер", "Тверь"),
    ("брянск", "Брянск"),
    ("иванов", "Иваново"),
    ("белгород", "Белгород"),
    ("сургут", "Сургут"),
    ("вологда", "Вологда"),
    ("мурманск", "Мурманск"),
    ("архангельск", "Архангельск"),
)

# Canonical make or model, the make it implies, and aliases.
# A model implies its make only when the customer actually said the model.
_NAMES: tuple[tuple[str, str | None, tuple[str, ...]], ...] = (
    ("Volkswagen", None, ("volkswagen", "фольксваген", "фольцваген", "vw")),
    ("Toyota", None, ("toyota", "тойота", "тойота")),
    ("Kia", None, ("kia", "киа")),
    ("Hyundai", None, ("hyundai", "хендай", "хёндай", "хундай")),
    ("Skoda", None, ("skoda", "шкода", "škoda")),
    ("Nissan", None, ("nissan", "ниссан", "нисан")),
    ("Mitsubishi", None, ("mitsubishi", "митсубиси", "митсубиши")),
    ("Volvo", None, ("volvo", "вольво")),
    ("Renault", None, ("renault", "рено")),
    ("BMW", None, ("bmw", "бмв")),
    ("Mercedes-Benz", None, ("mercedes", "мерседес")),
    ("Camry", "Toyota", ("camry", "камри")),
    ("Corolla", "Toyota", ("corolla", "королла", "корола")),
    ("RAV4", "Toyota", ("rav4", "рав4", "рав")),
    ("Rio", "Kia", ("rio", "рио")),
    ("Ceed", "Kia", ("ceed", "сид")),
    ("Sportage", "Kia", ("sportage", "спортейдж")),
    ("Solaris", "Hyundai", ("solaris", "солярис")),
    ("Creta", "Hyundai", ("creta", "крета")),
    ("Tiguan", "Volkswagen", ("tiguan", "тигуан")),
    ("Polo", "Volkswagen", ("polo", "поло")),
    ("Golf", "Volkswagen", ("golf", "гольф")),
    ("Passat", "Volkswagen", ("passat", "пассат")),
    ("Octavia", "Skoda", ("octavia", "октавия", "октавии")),
    ("Rapid", "Skoda", ("rapid", "рапид")),
    ("Qashqai", "Nissan", ("qashqai", "кашкай", "кашкай")),
    ("X-Trail", "Nissan", ("xtrail", "x-trail", "икстрейл")),
    ("Leaf", "Nissan", ("leaf", "лиф")),
    ("Lancer", "Mitsubishi", ("lancer", "лансер")),
    ("Outlander", "Mitsubishi", ("outlander", "аутлендер")),
    ("XC60", "Volvo", ("xc60", "хс60")),
    ("XC90", "Volvo", ("xc90", "хс90")),
    ("Logan", "Renault", ("logan", "логан")),
    ("Duster", "Renault", ("duster", "дастер")),
    ("Focus", "Ford", ("focus", "фокус")),
    ("Ford", None, ("ford", "форд")),
)


@dataclass(frozen=True)
class GroundedTurn:
    """What this conversation supports, and how the latest turn should be handled."""

    make: str | None = None
    model: str | None = None
    year: str | None = None
    city: str | None = None
    symptom: str | None = None
    service: str | None = None
    detail: str | None = None
    powertrain: str | None = None
    comes_to_shop: bool | None = None
    brand_raw: str | None = None
    stated_vehicle: str | None = None
    price_asked: bool = False
    booking_asked: bool = False
    correction: bool = False
    correction_reliable: bool = False
    short_followup: bool = False
    unclear_referent: bool = False
    asks_hours: bool = False
    asks_advice: bool = False
    kept_year: bool = False
    asks_equipment: bool = False
    equipment_item: str | None = None
    urgent: str | None = None
    open_extra: str | None = None
    fresh_symptom: bool = False
    stated_total: int | None = None
    skip_model: bool = False
    should_retrieve: bool = False

    def vehicle_phrase(self) -> str:
        name = " ".join(part for part in (self.make, self.model) if part) or self.stated_vehicle
        if name and self.year:
            return f"{name}, {self.year}"
        if name:
            return name
        if self.year:
            return f"{self.year} год"
        return ""


def ground_conversation(messages: list[dict[str, str]], reading: TurnReading | None = None) -> GroundedTurn:
    """Walk customer turns in order. Later corrections replace one slot."""

    state = _Mutable()
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        previous = ""
        if index > 0 and messages[index - 1].get("role") == "assistant":
            previous = messages[index - 1].get("text") or ""
        _apply(state, message.get("text") or "", previous, latest=index == len(messages) - 1)
    if reading is not None and reading.asks_price and not state.service and state.symptom is None:
        pass
    return state.finish(messages, reading)


class _Mutable:
    def __init__(self) -> None:
        self.make: str | None = None
        self.model: str | None = None
        self.year: str | None = None
        self.city: str | None = None
        self.symptom: str | None = None
        self.service: str | None = None
        self.detail: str | None = None
        self.powertrain: str | None = None
        self.comes_to_shop: bool | None = None
        self.brand_raw: str | None = None
        self.stated_vehicle: str | None = None
        self.price_asked = False
        self.booking_asked = False
        self.correction = False
        self.correction_reliable = False
        self.short_followup = False
        self.unclear_referent = False
        self.asks_hours = False
        self.asks_advice = False
        self.kept_year = False
        self.asks_equipment = False
        self.equipment_item: str | None = None
        self.urgent: str | None = None
        self.open_extra: str | None = None
        self.stated_total: int | None = None
        self.latest_requests_work = False
        self.latest_is_hours = False
        self.latest_has_symptom = False
        self.part_mentions: list[str] = []

    def finish(self, messages: list[dict[str, str]], reading: TurnReading | None) -> GroundedTurn:
        business = bool(reading and (
            reading.asks_price or reading.asks_availability or reading.asks_booking or reading.asks_workshop
        ))
        hours = self.latest_is_hours or bool(reading and getattr(reading, "asks_hours", False))
        # Only the latest customer sentence can force the slow model. A symptom
        # already established is context, not a new ambiguous complaint.
        open_complaint = self.latest_has_symptom and not self.correction_reliable and not self.short_followup and not hours
        named_vehicle = bool(self.model or self.make)
        skip = False
        if self.unclear_referent:
            skip = True
        elif self.correction_reliable:
            skip = True
        elif self.short_followup:
            skip = True
        elif self.brand_raw and not self.model:
            skip = True
        elif named_vehicle and not self.model and not open_complaint:
            skip = True
        elif hours and not self.latest_requests_work:
            skip = True
        elif business and not open_complaint:
            skip = True
        if self.asks_advice:
            skip = True
        if open_complaint and not self.unclear_referent and not self.brand_raw and not self.asks_advice:
            skip = False
        if self.model and not self.short_followup and not self.correction_reliable and not business and not hours and not self.brand_raw and not self.asks_advice:
            if not self.latest_has_symptom and not self.latest_requests_work:
                # "Nissan Leaf 2019" is a new vehicle fact. Keep the capable path.
                skip = False
        # The job is already named and nothing new is ambiguous. The reply does
        # not need another model pass. A new symptom, a new vehicle, or a vague
        # extra clause still has to be read in full.
        new_vehicle = (
            bool(self.model) and not self.short_followup and not self.correction_reliable
            and not business and not hours and not self.brand_raw and not self.asks_advice
            and not self.latest_has_symptom and not self.latest_requests_work
        )
        if (
            self.service and not open_complaint and not self.open_extra and not new_vehicle
            and not self.unclear_referent and not self.brand_raw
            and not self.correction and not self.asks_advice
        ):
            skip = True
        if self.open_extra:
            skip = False
        # Stage timings show Mica and Qwen running one after the other, and Mica
        # is the slow stage. A named stock question plus a symptom already read
        # from this message does not need that serial pass. A vague extra does.
        if (
            self.asks_equipment and self.equipment_item and self.latest_has_symptom and self.symptom
            and not self.open_extra and not self.unclear_referent and not self.brand_raw
            and not self.correction
        ):
            skip = True
        if self.stated_total is not None and not open_complaint and not self.open_extra:
            skip = True
        if reading is not None and reading.out_of_scope and not open_complaint and not self.open_extra:
            skip = True
        if (
            reading is not None and reading.asks_contact and not open_complaint
            and not self.open_extra and not self.latest_requests_work
        ):
            skip = True
        # Safety text is already fixed by the message. Waiting on serial inference
        # would hold the guidance back.
        if self.urgent:
            skip = True
        retrieve = self.latest_requests_work and not hours and not self.unclear_referent and not self.asks_advice
        if self.short_followup and not self.latest_requests_work:
            retrieve = False
        if self.open_extra:
            retrieve = False
        return GroundedTurn(
            make=self.make,
            model=self.model,
            year=self.year,
            city=self.city,
            symptom=self.symptom,
            service=self.service,
            detail=self.detail,
            powertrain=self.powertrain,
            comes_to_shop=self.comes_to_shop,
            brand_raw=self.brand_raw,
            stated_vehicle=self.stated_vehicle,
            price_asked=self.price_asked,
            booking_asked=self.booking_asked,
            correction=self.correction,
            correction_reliable=self.correction_reliable,
            short_followup=self.short_followup,
            unclear_referent=self.unclear_referent,
            asks_hours=hours,
            asks_advice=self.asks_advice,
            kept_year=self.kept_year,
            asks_equipment=self.asks_equipment,
            equipment_item=self.equipment_item,
            urgent=self.urgent,
            open_extra=self.open_extra,
            fresh_symptom=bool(self.latest_has_symptom and self.symptom),
            stated_total=self.stated_total,
            skip_model=skip,
            should_retrieve=retrieve,
        )


def _apply(state: _Mutable, text: str, previous_assistant: str, latest: bool) -> None:
    folded = _fold(text)
    tokens = _TOKEN.findall(folded)
    topic = _question_topic(previous_assistant)
    hours = _is_hours(folded)
    already = bool(state.model or state.make or state.year or state.city or state.symptom or state.service)
    correction = _is_correction(folded, already)
    keep_year = bool(_KEEP_YEAR.search(folded))
    pairs = [( _fold(left), _fold(right)) for left, right in _PAIR.findall(text)]
    short = _is_short(tokens, folded)
    if latest:
        state.price_asked = any(cue in folded for cue in _PRICE_CUES)
        state.booking_asked = "запис" in folded or "когда можно" in folded
        equipment = _equipment_request(text, folded)
        state.asks_equipment = equipment is not None
        state.equipment_item = equipment or None
        state.urgent = _urgent_kind(folded)
        state.latest_is_hours = hours
        state.asks_hours = hours
        state.correction = correction
        state.kept_year = keep_year
        state.short_followup = bool(previous_assistant) and short and not correction
        state.latest_requests_work = _requests_work(folded) and not hours
        state.latest_has_symptom = _has_symptom(folded) and not correction
        state.asks_advice = _asks_advice(text, folded) and not hours
        state.stated_total = quoted_parts_labour_total(text)

    if latest and _is_hours_follow(text) and re.search(r"воскрес|график", _fold(previous_assistant)):
        state.latest_is_hours = True
        state.asks_hours = True
        state.short_followup = True
        state.latest_has_symptom = False
        state.latest_requests_work = False
        state.correction = False
        state.correction_reliable = False
        state.asks_advice = False
        return

    if latest and previous_assistant and already and set(tokens) <= _AFFIRM and not correction and topic not in {
        "shop", "city", "year", "vehicle", "referent",
    }:
        state.short_followup = True
        state.latest_has_symptom = False
        state.latest_requests_work = False
        state.correction = False
        state.correction_reliable = False
        return

    if hours and _negated_repair(folded) and not _requests_work(_without_negation(folded)):
        if latest:
            state.latest_requests_work = False
            state.correction = False
            state.correction_reliable = False
        return

    if _unclear_pronoun(tokens, folded, state):
        if latest:
            state.unclear_referent = True
            state.short_followup = False
        return

    if (
        short and topic and topic != "vehicle" and not correction
        and not _requests_work(folded) and not _has_symptom(folded)
        and not _is_meta(folded)
    ):
        _bind_short(state, text, tokens, topic)
        if latest:
            state.short_followup = True
            state.correction_reliable = False
        return

    named = _scan_names(tokens)
    year = _year_in(folded, pairs)
    city = _city_in(folded, pairs, topic, text, short)
    if correction:
        _apply_correction(state, folded, pairs, named, year, city, keep_year, text)
        if latest:
            state.correction_reliable = True
        return

    if year and not _year_is_negated(folded, year):
        state.year = year
    if named.make and named.make_confident:
        state.make = named.make
    if named.model and named.model_confident:
        state.model = named.model
        if named.model_make:
            state.make = named.model_make
    elif named.stated_model:
        state.model = named.stated_model
    if named.brand_raw and not named.make_confident and not named.model_confident:
        state.brand_raw = named.brand_raw
        state.make = None if state.make == named.rejected_make else state.make
    if city:
        state.city = city
    stated = _customer_vehicle(tokens, folded)
    if stated and not named.model_confident:
        state.stated_vehicle = stated
    elif named.model_confident:
        state.stated_vehicle = None
    powertrain = _powertrain(folded)
    if powertrain:
        state.powertrain = powertrain
    priced = _priced_job(text, folded)
    if priced and not state.service and not _has_symptom(folded):
        state.service = priced
        if latest:
            state.latest_requests_work = True
    if _requests_work(folded):
        phrase = _service_phrase(text)
        if phrase and not _vague_job(phrase):
            state.service = phrase
        elif phrase and (state.service or state.symptom) and latest:
            # "сколько стоит? и посмотрите там ещё" keeps the known job.
            state.open_extra = phrase
            state.latest_requests_work = False
    elif _has_symptom(folded):
        phrase = _symptom_phrase(text)
        if phrase:
            if state.symptom and not correction:
                if phrase.casefold() not in state.symptom.casefold():
                    state.detail = phrase
                if latest and previous_assistant:
                    state.short_followup = True
                    state.latest_has_symptom = False
            else:
                state.symptom = phrase
    elif (
        (state.symptom or state.service) and previous_assistant and not named.model and not named.make
        and not _customer_vehicle(tokens, folded) and _elaborates(tokens, folded) and not _is_meta(folded)
        and not state.asks_equipment and not state.price_asked and not state.booking_asked
    ):
        extra = _polish_phrase(text)
        if state.service and not state.symptom and extra and re.search(r"\b(?:диск|фильтр|колодк|масл)\w*", folded):
            if extra.casefold() not in state.service.casefold():
                state.service = f"{state.service} и {extra}"
            if latest:
                state.latest_requests_work = True
        elif extra and extra.casefold() not in f"{state.symptom or ''} {state.service or ''}".casefold():
            state.detail = extra
        if latest:
            state.short_followup = True
            state.latest_has_symptom = False
            if not re.search(r"\b(?:диск|фильтр|колодк|масл)\w*", folded):
                state.latest_requests_work = False
    shop = _shop_choice(folded)
    if shop is not None:
        state.comes_to_shop = shop
        if latest and previous_assistant and not _has_symptom(folded) and not correction:
            state.short_followup = True
            state.latest_has_symptom = False
    if _coolant_ok(folded):
        state.detail = "уровень в норме"
        if latest and previous_assistant:
            state.short_followup = True
            state.latest_has_symptom = False
    if (
        latest and topic == "vehicle" and not correction and not _has_symptom(folded)
        and not _requests_work(folded)
        and (named.model_confident or named.make_confident or named.stated_model)
    ):
        state.short_followup = True
        state.latest_requests_work = False
        state.latest_has_symptom = False
    for part in _PARTS:
        if part in folded and part not in state.part_mentions:
            state.part_mentions.append(part)


def _apply_correction(
    state: _Mutable,
    folded: str,
    pairs: list[tuple[str, str]],
    named: "_Names",
    year: str | None,
    city: str | None,
    keep_year: bool,
    raw: str,
) -> None:
    replaced_model = False
    replaced_city = False
    replaced_year = False
    replaced_symptom = False
    for left, right in pairs:
        left_name = _scan_names(_TOKEN.findall(left))
        right_name = _scan_names(_TOKEN.findall(right))
        if _YEAR.fullmatch(left.strip()) or _YEAR.search(left):
            found = _YEAR.search(right)
            if found:
                state.year = found.group(0)
                replaced_year = True
            continue
        left_is_vehicle = bool(
            left_name.model or left_name.make
            or (state.model and _soft_contains(left, state.model))
            or (state.make and _soft_contains(left, state.make))
            or (state.stated_vehicle and _soft_contains(left, state.stated_vehicle))
        )
        if left_is_vehicle:
            if right_name.model:
                state.model = right_name.model
                if right_name.model_make:
                    state.make = right_name.model_make
                state.stated_vehicle = None
                state.brand_raw = None
                replaced_model = True
            else:
                stated = _display_parts(_name_tokens(_TOKEN.findall(right)))
                if stated:
                    state.model = None
                    state.make = right_name.make if right_name.make_confident else None
                    state.stated_vehicle = stated
                    state.brand_raw = None
                    replaced_model = True
            continue
        if _city_in(left, [], None, left, False) or (state.city and _soft_contains(left, state.city)):
            chosen = _city_in(right, [], "city", right, True) or _clean_phrase(right)
            if chosen:
                state.city = chosen
                replaced_city = True
            continue
        if state.symptom and any(stem in left for stem in _SYMPTOM_CUES):
            replaced_symptom = True
    if named.model and named.model_confident and not replaced_model:
        # "не камри, королла" without the word "а".
        negated = _negated_model(folded, state.model)
        if negated and named.model.casefold() != (state.model or "").casefold():
            state.model = named.model
            if named.model_make:
                state.make = named.model_make
            replaced_model = True
    if year and not keep_year and not replaced_year and _year_is_replacement(folded, year):
        state.year = year
        replaced_year = True
    if city and not replaced_city and ("город" in folded or pairs):
        state.city = city
        replaced_city = True
    if _symptom_retracted(folded, state.symptom):
        replacement = _new_symptom_clause(raw)
        state.symptom = replacement or state.symptom
        state.detail = None
        replaced_symptom = True
    elif _has_symptom(folded) and not replaced_symptom and not replaced_model and not replaced_city:
        phrase = _symptom_phrase(raw)
        if phrase:
            state.symptom = phrase
            replaced_symptom = True
    if _requests_work(folded):
        phrase = _service_phrase(raw)
        if phrase:
            state.service = phrase
    if replaced_model and state.model:
        state.stated_vehicle = None
        state.brand_raw = None
    if replaced_model and not keep_year:
        state.year = _year_on_replacement(pairs, folded)
        state.kept_year = False
    elif keep_year:
        state.kept_year = True
    state.service = _strip_places(state.service or "") or None
    state.symptom = _strip_places(state.symptom or "") or None
    state.correction = True
    state.correction_reliable = bool(
        replaced_model or replaced_city or replaced_year or replaced_symptom or keep_year
    )
    if keep_year:
        state.kept_year = True


@dataclass
class _Names:
    make: str | None = None
    make_confident: bool = False
    model: str | None = None
    model_confident: bool = False
    model_make: str | None = None
    stated_model: str | None = None
    brand_raw: str | None = None
    rejected_make: str | None = None


def _scan_names(tokens: list[str]) -> _Names:
    found = _Names()
    consumed: set[int] = set()
    matches: list[tuple[float, int, str, str | None]] = []
    for index, token in enumerate(tokens):
        if token.isdigit() or token in _STOP or len(token) < 3:
            continue
        best: tuple[float, str, str | None] | None = None
        second = 0.0
        for canonical, implied, aliases in _NAMES:
            score = max(_match_score(token, alias) for alias in aliases)
            if best is None or score > best[0]:
                second = best[0] if best else 0.0
                best = (score, canonical, implied)
            elif score > second:
                second = score
        if best and best[0] >= 0.78 and best[0] - second >= 0.08:
            matches.append((best[0], index, best[1], best[2]))
            consumed.add(index)
        elif best and 0.55 <= best[0] < 0.78 and _latin(token):
            found.brand_raw = token
            found.rejected_make = best[1] if best[2] is None else best[2]
        for _score, _index, canonical, implied in sorted(matches, key=lambda item: item[1]):
            if implied:
                found.model = canonical
                found.model_confident = True
                found.model_make = implied
            elif not found.make:
                found.make = canonical
                found.make_confident = True
    if found.model and not found.make and found.model_make:
        found.make = found.model_make
        found.make_confident = True
    leftovers = []
    for index, token in enumerate(tokens):
        if index in consumed or token.isdigit() or token in _STOP or len(token) < 4:
            continue
        if _YEAR.fullmatch(token) or _is_city_token(token):
            continue
        if any(token.startswith(stem) for stem in _SYMPTOM_CUES + _PARTS + _WORK_CUES):
            continue
        leftovers.append(token)
    if not found.model and len(leftovers) == 1 and not _latin(leftovers[0]) and _near_year(tokens, leftovers[0]):
        found.stated_model = leftovers[0][:1].upper() + leftovers[0][1:]
    if found.brand_raw and (found.make_confident or found.model_confident):
        found.brand_raw = None
    return found


def _match_score(token: str, alias: str) -> float:
    left, right = _fold(token), _fold(alias)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) <= 3 or len(right) <= 3:
        return 0.0
    if left in right or right in left:
        if abs(len(left) - len(right)) <= 2:
            return 0.9
    distance = _distance(left, right)
    if distance <= 1 and min(len(left), len(right)) >= 5:
        return 0.88
    if distance <= 2 and min(len(left), len(right)) >= 7:
        return 0.82
    skeleton_gap = _distance(_skeleton(left), _skeleton(right))
    if skeleton_gap <= 1 and min(len(_skeleton(left)), len(_skeleton(right))) >= 4 and abs(len(left) - len(right)) <= 3:
        return 0.8
    return 0.0


def _bind_short(state: _Mutable, text: str, tokens: list[str], topic: str) -> None:
    folded = _fold(text)
    if set(tokens) <= _AFFIRM:
        if topic == "shop":
            state.comes_to_shop = "нет" not in tokens
        return
    if topic == "city":
        city = _city_in(folded, [], "city", text, True) or _clean_phrase(text)
        if city:
            state.city = city
        return
    if topic == "year":
        found = _YEAR.search(folded)
        if found:
            state.year = found.group(0)
        return
    if topic == "hours":
        state.asks_hours = True
        state.latest_is_hours = True
        return
    if topic in {"symptom", "open", "vehicle"}:
        extra = _clean_phrase(text)
        if extra and state.symptom and extra.casefold() not in state.symptom.casefold():
            state.detail = extra
        elif extra and not state.symptom and _has_symptom(folded):
            state.symptom = extra
        elif extra and state.service and not _requests_work(folded):
            state.detail = extra


def _question_topic(text: str) -> str | None:
    if not text or "?" not in text:
        return None
    folded = _fold(text)
    if "воскрес" in folded or "график" in folded or "часы работ" in folded:
        return "hours"
    if "город" in folded or "где искать" in folded or "каком районе" in folded:
        return "city"
    if "какой год" in folded or "какого года" in folded or "год выпуска" in folded:
        return "year"
    if any(cue in folded for cue in ("какая машина", "какую машину", "марка", "модель", "на какую машину")):
        return "vehicle"
    if "выезд" in folded or "в сервис" in folded or "приедете" in folded:
        return "shop"
    if "что именно" in folded and ("работ" in folded or "перестал" in folded):
        return "referent"
    if any(cue in folded for cue in ("когда", "холодн", "тормож", "что происходит", "что с машиной")):
        return "symptom"
    return "open"


def _unclear_pronoun(tokens: list[str], folded: str, state: _Mutable) -> bool:
    if not tokens or tokens[0] not in _PRONOUNS and "он" not in tokens[:3]:
        return False
    if "не работ" not in folded and "не заводит" not in folded and "слом" not in folded:
        return False
    if len(tokens) > 8:
        return False
    parts_here = [part for part in _PARTS if part in folded]
    if parts_here:
        return False
    if len(state.part_mentions) == 1:
        return False
    return True


def _is_correction(folded: str, already: bool) -> bool:
    if _PAIR.search(folded) or _KEEP_YEAR.search(folded) or folded.startswith("стоп") or "не гре" in folded:
        return True
    if not already:
        return False
    cues = ("ошибся", "ошиблась", "перепута", "на самом деле", "имею в виду", "не так")
    return any(cue in folded for cue in cues)


def _is_hours(folded: str) -> bool:
    return any(stem in folded for stem in (
        "воскрес", "график работ", "часы работ", "до скольки", "работаете ли", "вы работаете", "выходн",
    ))


def _negated_repair(folded: str) -> bool:
    return bool(re.search(r"не\s+про\s+(?:ремонт|работ)", folded))


def _without_negation(folded: str) -> str:
    return re.sub(r"не\s+про\s+\w+", " ", folded)


def _vague_job(phrase: str) -> bool:
    """A look-at-it clause with no part or job noun."""

    folded = _fold(phrase)
    if any(noun in folded for noun in _JOB_NOUNS):
        return False
    if any(part in folded for part in _PARTS if len(part) >= 4):
        return False
    tokens = _TOKEN.findall(folded)
    content = [
        token for token in tokens
        if len(token) >= 5 and token not in _STOP
        and token not in {"нибудь", "чтонибудь", "какнибудь", "вообще", "просто", "там"}
        and not token.startswith(("посмотр", "провер", "глян", "нужн", "хочу", "можн"))
    ]
    return not content


def _requests_work(folded: str) -> bool:
    text = _without_negation(folded) if _negated_repair(folded) else folded
    if _is_hours(text) and not any(cue in text for cue in ("шиномонтаж", "замен", "помен", "диагност")):
        return False
    if any(cue in text for cue in _WORK_CUES):
        return True
    if re.search(r"нужн", text):
        named = [
            token for token in _TOKEN.findall(text)
            if len(token) >= 5 and not token.startswith("нужн") and token not in _STOP
            and token not in {"запись", "записи", "цену", "цена", "скидку", "скидка"}
        ]
        return bool(named)
    return False


def _has_symptom(folded: str) -> bool:
    # A tool name such as "дымогенератор" contains "дым" but is not smoke.
    masked = re.sub(
        r"[a-zа-яё]*(?:генератор|сканер|тестер|стенд)[a-zа-яё]*",
        " ",
        folded,
    )
    return any(cue in masked for cue in _SYMPTOM_CUES)


def _symptom_retracted(folded: str, symptom: str | None) -> bool:
    if re.search(r"не\s+гре", folded):
        return True
    if symptom and re.search(r"\bне\b", folded):
        stems = [stem for stem in _SYMPTOM_CUES if stem in _fold(symptom)]
        return any(re.search(rf"не\s+\w*{re.escape(stem[:4])}", folded) for stem in stems if len(stem) >= 4)
    return False


def _new_symptom_clause(raw: str) -> str | None:
    parts = re.split(r"[.!?]", raw)
    for part in reversed(parts):
        folded = _fold(part)
        if _has_symptom(folded) and not re.search(r"\bне\s+гре", folded):
            return re.sub(r"(?i)^(?:у\s+этой\s+)?просто\s+", "", _clean_phrase(part))
    return None


def _year_in(folded: str, pairs: list[tuple[str, str]]) -> str | None:
    for left, right in pairs:
        found = _YEAR.search(right)
        if found and (_YEAR.search(left) or "год" in left):
            return found.group(0)
    found = _YEAR.search(folded)
    return found.group(0) if found else None


def _year_is_negated(folded: str, year: str) -> bool:
    return bool(re.search(rf"не\s+{year}", folded))


def _year_is_replacement(folded: str, year: str) -> bool:
    return bool(re.search(rf"а\s+{year}", folded)) or "год" in folded


def _year_on_replacement(pairs: list[tuple[str, str]], folded: str) -> str | None:
    """A year on the rejected car does not move to the replacement."""

    for _left, right in pairs:
        found = _YEAR.search(right)
        if found:
            return found.group(0)
    for match in _YEAR.finditer(folded):
        window = folded[max(0, match.start() - 24):match.start()]
        if re.search(r"\bне\b", window):
            continue
        return match.group(0)
    return None


def _city_in(folded: str, pairs: list[tuple[str, str]], topic: str | None, raw: str, short: bool) -> str | None:
    for left, right in pairs:
        if _city_name(left) or "город" in left:
            named = _city_name(right)
            if named:
                return named
            if topic == "city" or short:
                return _clean_phrase(right)
    named = _city_name(folded)
    if named:
        return named
    free = _free_city(folded)
    if free:
        return free
    if topic == "city" and short:
        return _clean_phrase(raw)
    match = re.search(r"город\s*[:—-]\s*([^\.,]{2,40})", folded)
    if match:
        return _city_name(match.group(1)) or _clean_phrase(match.group(1))
    return None


def _known_city_label(city: str) -> bool:
    return any(city == canonical for _stem, canonical in _CITIES)


def _city_name(text: str) -> str | None:
    folded = _fold(text)
    for stem, canonical in _CITIES:
        if stem in folded:
            return canonical
    return None


def _is_city_token(token: str) -> bool:
    return any(token.startswith(stem[:5]) for stem, _canonical in _CITIES if len(stem) >= 5)


def _powertrain(folded: str) -> str | None:
    if "дизел" in folded:
        return "дизель"
    if "бензин" in folded:
        return "бензин"
    if "гибрид" in folded:
        return "гибрид"
    if "электро" in folded:
        return "электро"
    if re.search(r"\bгаз\b", folded):
        return "газ"
    return None


def _shop_choice(folded: str) -> bool | None:
    if "сам приед" in folded or "в сервис" in folded or "приеду" in folded:
        return True
    if "выезд" in folded:
        return False
    return None


def _coolant_ok(folded: str) -> bool:
    return "уров" in folded and "норм" in folded


def _clause(text: str, predicate) -> str:
    parts = [part for part in re.split(r"[.!?]", text) if part.strip()]
    for part in parts:
        if predicate(_fold(part)):
            return part
    return parts[0] if parts else text


def _strip_names(text: str) -> str:
    cleaned = text
    for canonical, _implied, aliases in _NAMES:
        pieces = (canonical, *aliases)
        for alias in pieces:
            if len(alias) < 3:
                continue
            cleaned = re.sub(rf"(?i)\b{re.escape(alias)}\b", " ", cleaned)
    cleaned = _YEAR.sub(" ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}\b", " ", cleaned)
    return cleaned


def _service_phrase(text: str) -> str:
    clause = _strip_vehicle_span(_clause(text, _requests_work))
    cleaned = _strip_names(_clean_phrase(clause))
    cleaned = re.sub(
        r"(?i)^(?:привет|здравствуйте|здрасте|привте|добрый\s+\w+|доброе\s+\w+|хочу|надо|нужн\w*|можно|просто|скажите|скажи|ну\s+в\s+смысле|то\s+есть)\s*,?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?i)^а\s+", "", cleaned)
    cleaned = re.sub(
        r"(?i)^(?:сколько\s+стоит|поч[её]м(?:\s+нынче|\s+сейчас)?|а\s+если(?:\s+ещё|\s+еще)?|по\s+деньгам|как\s+выходят)\s+",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\b(?:по\s+деньгам.*|как\s+выходят.*)$", "", cleaned)
    cleaned = re.split(r"(?i)\s+и\s+когда|\s+когда\s+можно|\s+сколько\s+", cleaned)[0]
    cleaned = re.sub(
        r"(?i)\b(?:у меня|машина|автомобиль|года|год)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"(?i)\s+\bна\b\s*$", "", cleaned)
    cleaned = _strip_places(cleaned)
    cleaned = " ".join(cleaned.split()).strip(" .,")
    cleaned = re.sub(r"(?i)^у\s+вас\s+", "", cleaned)
    cleaned = re.sub(r"(?i)\s+и$", "", cleaned).strip(" .,")
    # "проверить это дымогенератором" points at the tool. It is not a job title.
    if re.search(r"(?i)^(?:можно\s+)?провер\w*\s+это\b", cleaned):
        return ""
    return cleaned[:180]


def _symptom_phrase(text: str) -> str:
    clause = _strip_names(_clean_phrase(_clause(text, _has_symptom)))
    clause = _strip_places(clause)
    clause = re.sub(
        r"(?i)\b(?:у меня|машина|машына|автомобиль|года|год|дизель|бензин|привет|здрасте|здравствуйте|привте)\b",
        " ",
        clause,
    )
    clause = clause.strip(" ,")
    previous_lead = None
    while clause and clause != previous_lead:
        previous_lead = clause
        clause = re.sub(r"(?i)^(?:у|на|в|во|с|со|от|по|из|для)\s+", "", clause).strip(" ,")
    previous = None
    while clause and clause != previous:
        previous = clause
        clause = re.sub(r"(?i)^(?:а\s+если|это|ну|и\s+ещ[её]|ещ[её]|также)\s+", "", clause).strip(" ,")
    clause = re.split(r"(?i)\s+это\s+прям|\s+сразу\s+ехать|\s+можно\s+ли\s+ехать", clause)[0]
    clause = re.sub(r"(?:\s*,\s*)+", ", ", clause)
    return " ".join(clause.split()).strip(" ,.-")[:180]


def _negated_model(folded: str, current: str | None) -> bool:
    if re.search(r"не\s+[a-zа-я0-9-]{3,}", folded):
        return True
    return bool(current and f"не {current.casefold()}" in folded)


def _soft_contains(text: str, value: str) -> bool:
    return value.casefold()[:5] in _fold(text)


def _is_short(tokens: list[str], folded: str) -> bool:
    return len(tokens) <= 6 and len(folded) <= 48


def _customer_vehicle(tokens: list[str], folded: str) -> str | None:
    """Repeat a car written next to its year when it is not in the known list.

    The words stay theirs. Nothing is mapped onto a different make or model.
    """

    del folded
    span = _vehicle_span(tokens)
    if not span:
        return None
    return _display_parts(span)


def _is_meta(folded: str) -> bool:
    return bool(re.search(r"^(?:ну\s+)?(?:и\s+)?что\s+(?:теперь|дальше)\b", folded))


def _elaborates(tokens: list[str], folded: str) -> bool:
    """A follow-up that adds a condition, not a new job or a new complaint."""

    if not tokens or _requests_work(folded) or _has_symptom(folded):
        return False
    return len(tokens) <= 12 and len(folded) <= 90


def _asks_advice(raw: str, folded: str) -> bool:
    """A yes/no about what to do, not a price, booking, or 'приехать'."""

    if "?" not in raw and not folded.startswith("а если"):
        return False
    if re.search(r"(?:^|\s)ехать\b", folded):
        return True
    return any(cue in folded for cue in ("что делать", "опасно ли", "можно ли ехать"))


def _priced_job(text: str, folded: str) -> str | None:
    if not any(cue in folded for cue in _PRICE_CUES):
        return None
    if not any(noun in folded for noun in _JOB_NOUNS):
        return None
    if _has_symptom(folded):
        return None
    phrase = _service_phrase(text)
    return phrase or None


def _polish_phrase(text: str) -> str:
    cleaned = _clean_phrase(text)
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = re.sub(r"(?i)^(?:ну|а|если|ещё|еще|просто|в\s+смысле|то\s+есть)\s+", "", cleaned).strip()
    return " ".join(cleaned.split()).strip(" .,?")


def _near_year(tokens: list[str], token: str) -> bool:
    if token not in tokens:
        return False
    return any(_YEAR.fullmatch(item) for item in tokens)


def _latin(token: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9-]+", token))


def _is_hours_follow(text: str) -> bool:
    return _fold(text) in {"это", "про это", "именно это"}


def _clean_phrase(text: str) -> str:
    return " ".join(text.replace("ё", "е").split()).strip(" .,!?:;—-")


def _fold(text: str) -> str:
    lowered = text.casefold().replace("ё", "е")
    return re.sub(r"(.)\1{2,}", r"\1\1", lowered)


def _skeleton(text: str) -> str:
    return "".join(char for char in text if char not in _VOWELS and char.isalnum())


def _distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for column, other in enumerate(right, 1):
            current.append(min(
                previous[column] + 1,
                current[-1] + 1,
                previous[column - 1] + (char != other),
            ))
        previous = current
    return previous[-1]


_PLACE_BLOCK = {
    "сервисе", "сервис", "баке", "бака", "норме", "зоне", "ходу", "месте",
    "машине", "впуске", "выпуске", "гараже", "дороге", "дворе", "боксе",
    "наличии", "порядке", "двигателе", "коробке", "салоне", "городе",
    "воскресенье", "воскресенья", "понедельник", "субботу", "суббота",
    "красной", "горячую", "холодную", "точно", "вообще",
}
_SLOT_EMPTY = {"", "unknown", "ambiguous_candidates", "none", "null", "conflicting"}


def _vehicle_span(tokens: list[str]) -> list[str] | None:
    """Name tokens written immediately before a year, not the whole sentence."""

    for index, token in enumerate(tokens):
        if not _YEAR.fullmatch(token):
            continue
        picked: list[str] = []
        cursor = index - 1
        while cursor >= 0 and len(picked) < 3:
            current = tokens[cursor]
            if current in _STOP or current in _PLACE_BLOCK or _city_name(current) or _is_city_token(current):
                break
            if _YEAR.fullmatch(current):
                break
            if any(current.startswith(stem) for stem in _SYMPTOM_CUES + _PARTS + _WORK_CUES + _JOB_NOUNS if len(stem) >= 4):
                break
            if current.isdigit():
                picked.append(current)
                cursor -= 1
                continue
            if len(current) < 2 or (not _latin(current) and len(current) < 4):
                break
            picked.append(current)
            cursor -= 1
        if not picked or not any(not part.isdigit() for part in picked):
            continue
        picked.reverse()
        return picked
    return None


def _display_parts(parts: list[str]) -> str:
    shown: list[str] = []
    for part in parts:
        if part.isdigit():
            if shown and shown[-1].isascii() and shown[-1].isupper() and len(shown[-1]) <= 3:
                shown[-1] = f"{shown[-1]}-{part}"
            else:
                shown.append(part)
            continue
        if part.isascii() and len(part) <= 3:
            shown.append(part.upper())
        else:
            shown.append(part[:1].upper() + part[1:])
    return " ".join(shown)


def _name_tokens(tokens: list[str]) -> list[str]:
    picked: list[str] = []
    for token in tokens:
        if token in _STOP or token in _PLACE_BLOCK or _YEAR.fullmatch(token) or _city_name(token):
            continue
        if len(token) < 2:
            continue
        picked.append(token)
    return picked[:3]


def _strip_vehicle_span(text: str) -> str:
    span = _vehicle_span(_TOKEN.findall(_fold(text)))
    if not span:
        return text
    pattern = r"(?i)\b" + r"\W+".join(re.escape(part) for part in span) + r"\b"
    return re.sub(pattern, " ", text)


def _place_from_token(token: str) -> str | None:
    token = _fold(token).strip(".,")
    if not token or token in _PLACE_BLOCK or token in _STOP:
        return None
    if any(token.endswith(suffix) for suffix in ("ой", "ый", "ая", "ое", "ые", "ий", "его", "ому", "ыми")):
        return None
    if any(token.startswith(stem) for stem in _PARTS + _SYMPTOM_CUES + _WORK_CUES if len(stem) >= 4):
        return None
    known = _city_name(token)
    if known:
        return known
    # Drop a final "е" only when that stem is a known city. An unknown
    # locative keeps the customer's spelling: "Саратове" is not "Саратов".
    if token.endswith("е") and len(token) >= 6:
        known = _city_name(token[:-1])
        if known:
            return known
    if token in _PLACE_BLOCK or len(token) < 4 or token.isdigit():
        return None
    return token[:1].upper() + token[1:]


def _free_city(folded: str) -> str | None:
    patterns = (
        r"(?:я|мы)\s+(?:сейчас\s+)?(?:нахожусь\s+)?в\s+([а-яё-]{4,})",
        r"в\s+городе\s+([а-яё-]{4,})",
        r"у\s+вас\s+в\s+([а-яё-]{4,})",
        r"(?:провер\w+|сдела\w+|посмотр\w+|выполн\w+|провест\w+)(?:\s+[а-яёa-z-]{2,}){0,3}\s+в\s+([а-яё-]{4,})",
        r"\bв\s+([а-яё-]{4,})\s+(?:провер\w+|сдела\w+|посмотр\w+|выполн\w+|провест\w+|смож\w+|мож\w+)",
        r"(?:^|[,.!;]\s+)в\s+([а-яё-]{4,})",
    )
    for pattern in patterns:
        match = re.search(pattern, folded)
        if not match:
            continue
        place = _place_from_token(match.group(1))
        if place:
            return place
    return None


def _strip_places(text: str) -> str:
    cleaned = text
    for stem, canonical in _CITIES:
        cleaned = re.sub(rf"(?i)\bв\s+{re.escape(stem)}\w*", " ", cleaned)
        cleaned = re.sub(rf"(?i)\b{re.escape(canonical)}\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bв\s+городе\s+[а-яё-]{4,}", " ", cleaned)

    def drop_free(match: re.Match[str]) -> str:
        return " " if _place_from_token(match.group(1)) else match.group(0)

    cleaned = re.sub(r"(?i)\bв\s+([а-яё-]{4,})", drop_free, cleaned)
    return " ".join(cleaned.split()).strip(" .,")


def _equipment_request(raw: str, folded: str) -> str | None:
    """The tool the customer asked about, or '' when the item has no name.

    None means the turn is not an equipment question. A booking window is not stock.
    """

    if re.search(r"окн|запис|приеха|свободн|\bместо\b", folded):
        return None
    if not re.search(
        r"у\s+вас\s+(?:точно\s+)?(?:есть|имеется)|есть\s+у\s+вас|есть\s+ли\s+у\s+вас|в\s+наличии",
        folded,
    ):
        return None
    match = re.search(r"(?i)(?:^|[.!?]\s*|а\s+)([а-яёa-z-]{4,})\s+у\s+вас", raw)
    if not match:
        match = re.search(r"(?i)есть\s+ли\s+(?:у\s+вас\s+)?([а-яёa-z-]{4,})", raw)
    if not match:
        match = re.search(r"(?i)в\s+наличии\s+([а-яёa-z-]{4,})", raw)
    if not match:
        match = re.search(r"(?i)([а-яёa-z-]{4,})\s+в\s+наличии", raw)
    if not match:
        match = re.search(r"(?i)([а-яёa-z-]{4,})\s+есть\s+у\s+вас", raw)
    if not match:
        return ""
    word = match.group(1)
    if _fold(word) in _STOP or _fold(word) in _PLACE_BLOCK:
        return ""
    return word


def _urgent_kind(folded: str) -> str | None:
    """A situation where the next sentence has to be immediate safety guidance."""

    poured = "залил" in folded or "заправи" in folded or "налил" in folded
    fuel = "бак" in folded or "топлив" in folded or "бензин" in folded or "дизел" in folded
    wrong = "не то" in folded or "не тот" in folded or "не та" in folded or "вместо" in folded
    if poured and fuel and wrong:
        return "misfuel"
    if ("красн" in folded and ("зон" in folded or "стрелк" in folded)) or "перегре" in folded:
        return "overheat"
    if re.search(r"тормоз\w*\s+не\s+(?:работ|держ)|нет\s+тормоз|отказал\w*\s+тормоз|тормоз\w*\s+пропал", folded):
        return "brakes"
    return None


def _slot_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip(" ,.;")
    if cleaned.casefold() in _SLOT_EMPTY:
        return None
    return cleaned


def _customer_blob(messages: list[dict[str, str]], latest_only: bool) -> str:
    texts = [item.get("text") or "" for item in messages if item.get("role") == "user"]
    if not texts:
        return ""
    return texts[-1] if latest_only else " ".join(texts)


def _mentions(value: str, text: str) -> bool:
    tokens = [
        token for token in _TOKEN.findall(_fold(value))
        if len(token) >= 3 and not _YEAR.fullmatch(token)
    ]
    if not tokens:
        return False
    customer = _TOKEN.findall(_fold(text))
    for token in tokens:
        if any(
            token == item or (len(token) >= 5 and len(item) >= 5 and token[:5] == item[:5])
            for item in customer
        ):
            continue
        return False
    return True


def _slot_vehicle(value: str) -> tuple[str, str | None]:
    found = _YEAR.search(value)
    year = found.group(0) if found else None
    name = re.sub(r"[,;/]", " ", _YEAR.sub(" ", value))
    return " ".join(name.split()).strip(), year


def apply_extractor_facts(
    grounded: GroundedTurn,
    extraction: dict[str, Any] | None,
    messages: list[dict[str, str]],
) -> GroundedTurn:
    """Fill gaps from extractor slots when the customer's words support them.

    A correction is checked against the latest customer message, so a stale
    vehicle, year, or city in the model output does not come back.
    """

    slots = extraction.get("slots_after_message") if isinstance(extraction, dict) else None
    if not isinstance(slots, dict):
        return grounded
    # A correction is judged only by the latest customer message.
    scope = _customer_blob(messages, latest_only=grounded.correction)
    updates: dict[str, Any] = {}
    vehicle_raw = _slot_text(slots.get("vehicle"))
    if vehicle_raw:
        name, year = _slot_vehicle(vehicle_raw)
        if name and _mentions(name, scope):
            if not (grounded.model or grounded.make or grounded.stated_vehicle):
                updates["stated_vehicle"] = name
            if year and not grounded.year and year in _TOKEN.findall(_fold(scope)):
                updates["year"] = year
    city_raw = _slot_text(slots.get("search_area"))
    if city_raw and not grounded.city and _mentions(city_raw, scope):
        updates["city"] = _place_from_token(city_raw) or city_raw.strip()
    if not updates:
        return grounded
    return replace(grounded, **updates)


def verified_business(env: dict | None = None) -> dict | None:
    """Return explicit shop facts only when this app was given a facts file.

    There is no hosted price list. An unset path means the reply must say the
    figure is unavailable instead of inventing one.
    """

    import json
    import os
    from pathlib import Path

    source = env if env is not None else os.environ
    raw = (source.get("AUTOSERVICE_BUSINESS_FACTS") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


__all__ = ["GroundedTurn", "apply_extractor_facts", "ground_conversation", "verified_business"]
