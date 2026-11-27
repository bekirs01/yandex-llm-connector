"""Read a customer turn as a whole, using recent history.

This is a router for what the reply has to do. It does not map a phrase to a
canned answer. Typos and short slang are recognized as communicative acts;
a greeting that also asks something stays a real request.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_TOKEN = re.compile(r"[0-9a-zа-я]+", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_LATIN = re.compile(r"\b[a-z]{3,}\b")
# A negation is a correction only when it replaces something ("не X, а Y")
# or the customer talks about the year. "не помогает" and "не когда" are not corrections.
_CORRECTION = re.compile(r"\bне\b.{0,60}\bа\b|\bгод\w*\s+(?:тот\s+же|не\s+меня)")

# Act cues. Matching a cue only classifies the turn; the reply is composed later.
_GREET = ("привет", "здравств", "здаров", "хай", "добры", "приветств")
_THANKS = ("спасиб", "благодар", "пасиб", "мерси")
_BYE = ("пока", "свидан", "спокойной ночи", "доскор")
_SMALL = ("как дела", "как жизнь", "как ты", "как сам", "что нового", "как настроен", "погод", "че как")
_VAGUE = ("алло", "помог", "подскаж", "есть вопрос", "с чего нач")
_PRICE = ("сколько", "стоим", "цен", "прайс", "почем", "деньг", "выходит", "обойд")
_AVAIL = ("когда можно", "когда приеха", "свободн", "есть окно", "есть место", "во сколько", "на завтра")
_BOOK = ("запис", "заброн", "брон")
_SHOP = ("мастерск", "куда отдать", "подбер", "где сделать", "ищу сервис", "какой сервис", "ближайш")
_CAUSE = ("почему", "причин", "что делать", "что с этим", "что случил", "диагноз")
_AUTO = (
    "машин", "автомоб", "двигат", "мотор", "масл", "тормоз", "стук", "шум", "скрип",
    "коробк", "шин", "колес", "фильтр", "печк", "турб", "аккумул", "свеч", "подвеск",
    "рул", "фар", "стекл", "кондиц", "антифриз", "развал", "сцеплен", "глушит",
    "бензин", "дизел", "гибрид", "электр", "колод", "амортиз", "грм", "салон",
    "акпп", "вариатор", "радиатор", "стартер", "генератор", "чек", "ламп", "стойк",
)
_WORK = ("замен", "помен", "снять", "снят", "постав", "отрегул", "провер", "диагност", "ремонт", "перебор", "установ")
_FIX = ("ошиб", "на самом деле", "имею в виду", "поправ", "я перепута", "тот же", "не меня")
_AFFIRM = {"да", "нет", "ага", "угу", "неа", "ок", "okay", "ладно", "верно"}
_NEAR = (
    "привет", "здравствуйте", "здравствуй", "здарова", "спасибо", "благодарю",
    "пока", "хай", "мерси", "алло",
)


@dataclass(frozen=True)
class TurnReading:
    """What the latest customer message is doing in this conversation."""

    greeting: bool
    thanks: bool
    farewell: bool
    smalltalk: bool
    vague: bool
    acknowledgment: bool
    correction: bool
    asks_price: bool
    asks_availability: bool
    asks_booking: bool
    asks_workshop: bool
    asks_diagnosis: bool
    asks_hours: bool
    asks_contact: bool
    out_of_scope: bool
    automotive: bool
    answers_open_question: bool
    needs_extraction: bool
    needs_retrieval: bool

    @property
    def social_only(self) -> bool:
        return not self.out_of_scope and not self.needs_extraction and not self.needs_retrieval and not (
            self.asks_price or self.asks_availability or self.asks_booking
            or self.asks_workshop or self.asks_diagnosis or self.asks_hours
            or self.asks_contact
        )


def read_turn(messages: list[dict[str, str]]) -> TurnReading:
    """Classify the latest user message together with the turns before it."""

    latest = messages[-1]["text"]
    folded = _fold(latest)
    tokens = _TOKEN.findall(folded)
    previous = messages[-2]["text"] if len(messages) > 1 else ""
    open_question = bool(previous) and messages[-2]["role"] == "assistant" and "?" in previous
    history_folded = " ".join(_fold(item["text"]) for item in messages[:-1])

    greeting = _has_any(folded, _GREET) or _near_any(tokens, _NEAR[:4]) or _is_exact(tokens, {"хай", "ку", "йоу"})
    thanks = _has_any(folded, _THANKS) or _near_any(tokens, ("спасибо", "благодарю", "мерси")) or _is_exact(tokens, {"спс", "пасиб", "спасибо"})
    farewell = _is_farewell(folded, tokens)
    smalltalk = _has_any(folded, _SMALL) and not _has_any(folded, _AUTO)
    vague = _has_any(folded, _VAGUE)
    asks_price = _has_any(folded, _PRICE)
    asks_availability = _has_any(folded, _AVAIL) or ("когда" in tokens and "приеха" in folded)
    asks_booking = _has_any(folded, _BOOK)
    asks_workshop = _has_any(folded, _SHOP)
    if asks_workshop and asks_booking and "ближайш" in folded:
        shop_choice = _has_any(folded, ("мастерск", "куда отдать", "подбер", "где сделать", "ищу сервис", "какой сервис"))
        if not shop_choice:
            asks_workshop = False
    asks_diagnosis = _has_any(folded, _CAUSE)
    asks_hours = _has_any(folded, ("воскрес", "график работ", "часы работ", "до скольки", "работаете ли", "вы работаете", "выходн"))
    asks_contact = _asks_phone(folded)
    quoted_total = quoted_parts_labour_total(latest)
    out_of_scope = _unrelated_standalone(folded) and not smalltalk
    if out_of_scope:
        asks_price = False
        asks_availability = False
        asks_booking = False
        asks_workshop = False
        asks_diagnosis = False
        asks_hours = False
        asks_contact = False
    work_text = re.sub(r"не\s+про\s+\w+", " ", folded)
    automotive = bool(
        _YEAR.search(work_text) or _LATIN.search(work_text)
        or _has_any(work_text, _AUTO) or _has_any(work_text, _WORK)
    )
    if asks_hours and not (_YEAR.search(work_text) or _LATIN.search(work_text) or _has_any(work_text, _AUTO)):
        automotive = False
    if not automotive and re.search(r"нужн", folded):
        named = [token for token in tokens if len(token) >= 5 and not token.startswith("нужн")]
        if named and not asks_hours:
            automotive = True
    previous_folded = _fold(previous) if previous and messages[-2]["role"] == "assistant" else ""
    if not asks_booking and re.search(r"запис|не подтверждаю", previous_folded):
        if re.search(r"\bчас|\bутр|\bвечер|\bна\s+\d{1,2}\b", folded) and "запис" not in folded:
            asks_booking = True
    if not asks_hours and folded in {"это", "про это", "именно это"} and re.search(r"воскрес|график", previous_folded):
        asks_hours = True
    if (
        not automotive and not asks_hours and len(tokens) <= 4
        and _has_any(history_folded, _AUTO + _WORK)
        and re.search(r"передн|задн|лев|прав", folded)
    ):
        automotive = True
    correction = bool(_CORRECTION.search(folded) or _has_any(folded, _FIX))
    acknowledgment = bool(tokens) and set(tokens) <= (_AFFIRM | {"хорошо", "понял", "ясно", "угу"})
    business = (
        asks_price or asks_availability or asks_booking or asks_workshop
        or asks_diagnosis or asks_hours or asks_contact or quoted_total is not None
    )
    contentful = automotive or business or correction
    pure_social = (greeting or thanks or farewell or smalltalk) and not contentful and not correction
    answers = False
    if open_question and acknowledgment and not correction:
        answers = True
    elif open_question and not pure_social and not (business and not automotive and not correction):
        answers = True
    if correction and len(messages) > 1:
        answers = True

    needs_extraction = automotive or correction or answers
    if asks_hours and not automotive:
        needs_extraction = False
    topic_known = _has_any(history_folded, _AUTO) or _has_any(history_folded, _WORK) or bool(_YEAR.search(history_folded) or _LATIN.search(history_folded))
    needs_retrieval = (
        not asks_hours
        and (automotive or asks_workshop or asks_diagnosis or ((asks_price or asks_availability or asks_booking) and (automotive or topic_known)))
    )
    if smalltalk and not contentful:
        needs_extraction = False
        needs_retrieval = False
    if (greeting or thanks or farewell or acknowledgment or vague) and not contentful and not answers:
        needs_extraction = False
        needs_retrieval = False
    if not contentful and not answers and not business:
        vague = vague or (not greeting and not thanks and not farewell and not smalltalk and not acknowledgment and len(tokens) <= 3)
        needs_extraction = False
        needs_retrieval = False
    if out_of_scope or (asks_contact and not automotive and not correction and not answers):
        needs_extraction = False
        needs_retrieval = False
    if quoted_total is not None and not _has_any(folded, ("стуч", "скрип", "течь", "греет", "дымит", "чек", "троит")):
        needs_extraction = False
        needs_retrieval = False

    return TurnReading(
        greeting=greeting,
        thanks=thanks,
        farewell=farewell,
        smalltalk=smalltalk and not contentful,
        vague=vague and not contentful and not answers,
        acknowledgment=acknowledgment and not contentful and not answers,
        correction=correction,
        asks_price=asks_price,
        asks_availability=asks_availability,
        asks_booking=asks_booking,
        asks_workshop=asks_workshop,
        asks_diagnosis=asks_diagnosis,
        asks_hours=asks_hours,
        asks_contact=asks_contact,
        out_of_scope=out_of_scope,
        automotive=automotive,
        answers_open_question=answers,
        needs_extraction=needs_extraction,
        needs_retrieval=needs_retrieval,
    )


_LABELLED_AMOUNT = re.compile(
    r"(?P<label>запчаст\w*|(?<![а-я])работ\w*|(?<![а-я])услуг\w*)"
    r"[^0-9]{0,24}"
    r"(?P<amount>\d{1,3}(?:[ \u00a0]\d{3})+|\d{2,7})"
    r"(?:[.,](?P<frac>\d{1,2}))?"
    r"\s*(?:₽|руб(?:л(?:ей|я|ь))?|р\b)?"
)
_OFF_TOPIC = (
    "столиц", "рецепт", "чемпионат", "президент", "квант", "анекдот", "фильм", "сериал",
)


def quoted_parts_labour_total(text: str) -> int | None:
    """Sum two explicit amounts, one for parts and one for labour.

    A bare arithmetic expression is not a parts quote. The amounts are the
    numbers the customer wrote, not a shop price.
    """

    # Do not use _fold here: it collapses a run of zeros, so "2 000" becomes "2 00".
    folded = text.casefold().replace("ё", "е")
    if not re.search(r"сколько|итого|вместе|выйдет|выходит|в\s+сумме|\bплюс\b|\+", folded):
        return None
    parts = None
    labour = None
    for match in _LABELLED_AMOUNT.finditer(folded):
        fraction = match.group("frac")
        if fraction and int(fraction) != 0:
            continue
        if re.match(r"\s*год", folded[match.end():match.end() + 6]):
            continue
        digits = match.group("amount").replace(" ", "").replace("\u00a0", "")
        value = int(digits)
        if value < 1 or value > 10_000_000:
            continue
        if match.group("label").startswith("запчаст"):
            if parts is None:
                parts = value
        elif labour is None:
            labour = value
    if parts is None or labour is None:
        return None
    return parts + labour


def _asks_phone(folded: str) -> bool:
    if re.search(r"номер\s+запис", folded) and "телефон" not in folded:
        return False
    if "телефон" in folded or "позвон" in folded:
        return True
    if re.search(r"номер\s+(?:мастерск|сервис|филиал)", folded):
        return True
    return bool(re.search(r"(?:как|куда)\s+(?:вам\s+)?(?:позвонить|связаться)", folded))


def _is_standalone_arithmetic(folded: str) -> bool:
    if re.search(
        r"запчаст|машин|авто|сервис|масл|колод|двигат|тормоз|запис|телефон|ремонт|замен|шино",
        folded,
    ):
        return False
    stripped = re.sub(
        r"(сколько\s+будет|посчитай(?:те)?|чему\s+равно|сколько\s+это|скажи\s+сколько)",
        " ",
        folded,
    )
    stripped = " ".join(re.sub(r"[?!.,]", " ", stripped).split())
    if not re.search(r"\d", stripped) or not re.search(r"[+\-*/×xх]", stripped):
        return False
    return re.fullmatch(r"[\d\s+\-*/×xх().]+", stripped) is not None


def _unrelated_standalone(folded: str) -> bool:
    """A question that is not about the workshop, the car, or a quoted job total."""

    if quoted_parts_labour_total(folded) is not None:
        return False
    if _is_standalone_arithmetic(folded):
        return True
    if _has_any(folded, _AUTO + _WORK + _PRICE + _BOOK + _AVAIL) or _asks_phone(folded):
        return False
    if any(stem in folded for stem in ("стук", "стуч", "скрип", "течь", "дымит", "греет", "чек")):
        return False
    if _has_any(folded, _OFF_TOPIC):
        return True
    return bool(re.match(r"^(?:кто|что такое|зачем|где находится|какой город|какая столица)\b", folded))


def _is_farewell(folded: str, tokens: list[str]) -> bool:
    """'пока' is goodbye only as a sign-off. 'смотрю пока' means 'for now'."""

    if _has_any(folded, ("свидан", "спокойной ночи", "доскор")) or _is_exact(tokens, {"пока", "бай"}):
        return True
    if "пока" not in tokens:
        return False
    if any(block in folded for block in ("смотр", "пока не", "пока что", "пока просто")):
        return False
    return tokens[-1] == "пока" and len(tokens) <= 4


def _fold(text: str) -> str:
    lowered = text.casefold().replace("ё", "е")
    lowered = re.sub(r"(.)\1{2,}", r"\1\1", lowered)
    return lowered


def _has_any(text: str, stems: tuple[str, ...]) -> bool:
    return any(stem in text for stem in stems)


def _is_exact(tokens: list[str], words: set[str]) -> bool:
    return bool(tokens) and all(token in words for token in tokens)


def _near_any(tokens: list[str], targets: tuple[str, ...]) -> bool:
    for token in tokens:
        if not 3 <= len(token) <= 14:
            continue
        for target in targets:
            if abs(len(token) - len(target)) > 1:
                continue
            if _distance(token, target) <= 1:
                return True
    return False


def _distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (char != other)))
        previous = current
    return previous[-1]
