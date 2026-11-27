"""Have the local language model write the customer-facing Russian reply.

One generation call per turn. The model sees a compact context: customer
facts, the current task, the assistant's pending offer or question, a few
catalog rows and recent turns. Its text is checked for business claims that
the context does not support; a rejected or missing answer is replaced by the
caller's grounded fallback, and the origin is reported.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

from webapp.retrieval import _catalog

DEFAULT_URL = "http://127.0.0.1:8768/v1/chat/completions"
TIMEOUT_S = 25.0
MAX_TOKENS = 170
RECENT_MESSAGES = 4
TURN_CHARS = 300

SYSTEM_PROMPT = (
    "Ты — опытный консультант по автосервису в чате. Отвечаешь клиенту по-русски, "
    "как живой мастер-приёмщик: 2–3 коротких предложения, без списков.\n"
    "Как отвечать:\n"
    "- Сначала по существу ответь на последнее сообщение клиента.\n"
    "- Если клиент описал неисправность, назови подходящую работу из каталога и простыми словами "
    "скажи, что при ней проверяют. Причину не утверждай.\n"
    "- Цены, телефоны, адрес, наличие и свободное время называй только из проверенных данных. "
    "Если цены нет, скажи это коротко и предложи одно: проверенный телефон или готовое сообщение "
    "с просьбой полной сметы.\n"
    "- На «что входит в стоимость» назови состав. Для замены масла это масло, фильтр и работа, "
    "и отдельно — какие строки подтверждены. Не подменяй это фразой, что цены нет.\n"
    "- Звонить, искать сервисы и записывать ты не можешь. «Да» без явного предложения — не запись. "
    "Если клиент согласился, чтобы ты составил сообщение или назвал адрес, сделай это сразу: "
    "готовый текст в кавычках «» либо только проверенный адрес.\n"
    "- «У нас» и «к нам» пиши только когда в фактах названа одна мастерская и эта работа там "
    "подтверждена. Иначе не выдумывай адрес и не отправляй клиента узнавать, делают ли услугу. "
    "Приглашение подъехать — не запись и не обещание принять сразу, если окно неизвестно.\n"
    "- Если клиент просит несколько работ, коротко отзовись о каждой.\n"
    "- Не говори, что проверка или работа уже сделана, и не придумывай её результаты. "
    "Причину неисправности не утверждай.\n"
    "- Сменилась тема — не упоминай прежний симптом. Не задавай вопрос, если ответ уже полный.\n\n"
    "Пример стиля (другая тема):\n"
    "Клиент: Стучит что-то спереди на кочках, Kia Rio. Сколько стоит посмотреть?\n"
    "Консультант: Под это подходит диагностика подвески: на подъёмнике проверяют стойки, "
    "сайлентблоки, шаровые и рулевые наконечники. Точную цену назовёт сервис — прайсов у меня нет. "
    "Если хотите, составлю короткое сообщение для сервиса с описанием стука."
)

_UNSUPPORTED = (
    (re.compile(r"\d[\d\s]*(?:руб|₽|р\.|тыс)", re.I), "price"),
    (re.compile(r"(?:стоит|стоимость|цена)[^.?!]{0,25}\d", re.I), "price"),
    (re.compile(r"(?:\+7|\b8)[\s(-]*\d{3}[\s)-]*\d{3}"), "phone"),
    (re.compile(r"\b\d{1,2}:\d{2}\b"), "time"),
    (re.compile(r"записал[аи]?\s+вас|запишем|записываем вас|вы записаны|запись подтвержд|забронирова|оформил[аи]? заявк", re.I), "booking"),
    (re.compile(r"перезвоним|позвоним вам|свяжемся с вами|свяжусь с|найду (?:вам|для вас)|я запишу|запишу вас", re.I), "action"),
    (re.compile(r"\bу нас\b|\bк нам\b|\bмы (?:делаем|меняем|проверяем|можем|посмотрим)", re.I), "own_shop"),
    (re.compile(r"есть в наличии|на складе", re.I), "stock"),
    (re.compile(r"(?:хотите|интересует|могу)[^.?!]{0,40}запис|(?:подтвердить|оформить) запис|записаться на", re.I),
     "booking_offer"),
    (re.compile(r"(?:проверк|диагностик|работ|замен|тест)[^.!?]{0,40}(?:завершен|выполнен|проведен|сделан|показал)|"
                r"уже (?:проверил|провер[её]н|сделал|замен)|"
                r"результат\w* (?:теста|проверки|диагностики) (?:показал|готов)|мы проверили", re.I), "completed_work"),
    (re.compile(r"причина (?:точно|именно) в|это точно|однозначно (?:из-за|в)", re.I), "diagnosis"),
)


@dataclass
class WriterContext:
    latest: str
    recent: list[dict[str, str]]
    vehicle: str = ""
    city: str = ""
    candidates: list[tuple[str, str]] = field(default_factory=list)
    current_task: tuple[str, str] | None = None
    earlier_tasks: list[tuple[str, str]] = field(default_factory=list)
    customer_need: str = ""
    pending: str = ""
    business_facts: dict | None = None
    safety_note: str = ""
    turn_note: str = ""
    mixed: tuple[tuple[str, str], ...] = ()
    opening: str = "Начни с прямого ответа на него."
    back_reference: bool = False
    dropped_symptom: str = ""
    switched_to: tuple[str, str] | None = None
    represents_shop: bool = False
    required_groups: tuple[tuple[str, ...], ...] = ()
    forbid_fragments: tuple[str, ...] = ()
    advisor_note: str = ""


@dataclass
class WriterResult:
    text: str | None
    service_id: str | None
    origin: str
    reason: str | None
    elapsed_ms: float
    tokens: int | None = None
    timings: dict | None = None


class _CatalogIndex:
    def __init__(self, rows: list[dict]) -> None:
        self.titles = {row["service_id"]: row["source_title"].strip().rstrip(".") for row in rows}
        self.terms = {
            row["service_id"]: _grams(row["source_title"] + " " + " ".join(row.get("aliases") or []))
            for row in rows
        }
        counts = Counter(term for terms in self.terms.values() for term in terms)
        self.weights = {term: 1 + math.log(len(rows) / count) for term, count in counts.items()}

    def search(self, text: str, limit: int) -> list[tuple[str, str]]:
        query = _grams(text)
        if not query:
            return []
        scored = []
        for service_id, terms in self.terms.items():
            shared = terms & query
            if not shared:
                continue
            score = sum(self.weights[term] for term in shared) / math.sqrt(len(terms))
            scored.append((score, service_id))
        scored.sort(reverse=True)
        if not scored:
            return []
        best = scored[0][0]
        return [(sid, self.titles[sid]) for score, sid in scored[:limit] if score >= max(2.0, best * 0.5)]


_INDEX: _CatalogIndex | None = None
# Work verbs and filler say that a job is wanted, not which one.
_GENERIC_STEMS = (
    "замен", "меня", "помен", "провер", "диагно", "ремон", "обслу", "устан", "снят", "нужн",
    "услуг", "здрав", "добры", "можно", "может", "сколь", "будет", "стои", "пожал", "подск",
    "скажи", "спаси", "приве", "котор", "како", "также", "если", "требу", "сборе", "компле",
    "систе", "работ", "делае", "серви", "описа", "напис", "врем", "завтр", "сегод", "свобод", "после", "посмо", "глянь", "хочу", "очист", "года", "город",
)
# Everyday customer wording mapped onto catalog vocabulary.
_COLLOQUIAL = (
    ("подсос", "герметичность впуска дымогенератором патрубки уплотнения впуска"),
    ("масло в двигател", "моторного масла"),
    ("масло в мотор", "моторного масла"),
    ("моторное масло", "моторного масла"),
    ("плавают оборот", "холостой ход дроссельного узла"),
    ("троит", "свечей зажигания катушки"),
    ("кондей", "кондиционера хладагентом"),
    ("кондиционер", "хладагентом"),
    ("при тормож", "диагностика тормозов измерение износа"),
    ("развал", "углов установки колёс"),
    ("переобу", "шин на диски шиномонтаж"),
    ("акб", "аккумулятора"),
    ("скрип", "тормозных колодок"),
    ("грм", "ремня грм"),
)


def _stems(text: str, expand: bool = True) -> list[str]:
    folded = text.casefold().replace("ё", "е")
    for phrase, expansion in _COLLOQUIAL if expand else ():
        if phrase in folded:
            folded += " " + expansion
    if expand and re.search(r"замен\w*\s+масл", folded) and not re.search(
        r"давлен|расход|мкпп|акпп|редуктор|коробк", folded
    ):
        folded += " моторного масла масляного фильтра"
    stems = []
    for word in re.findall(r"[а-яa-z0-9]{3,}", folded):
        if len(word) == 3 and word not in {"грм", "акб", "абс", "дпф", "egr", "abs", "дмрв"}:
            continue
        stem = word[:max(4, min(6, len(word) - 2))] if len(word) > 4 else word
        if any(stem.startswith(g) or g.startswith(stem) for g in _GENERIC_STEMS):
            continue
        stems.append(stem)
    return stems


def _grams(text: str) -> set[str]:
    return set(_stems(text))


def catalog_index() -> _CatalogIndex | None:
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = _CatalogIndex(_catalog())
        except Exception:
            return None
    return _INDEX


def clause_tasks(text: str) -> list[tuple[str, str]]:
    """The best catalog row of each clause that names a job; two or more means a mixed request."""

    index = catalog_index()
    if index is None:
        return []
    found: list[tuple[str, str]] = []
    for clause in re.split(r"\s(?:и|а также|ещё|еще|плюс|заодно)\s", text):
        own = set(_stems(clause, expand=False))
        top = index.search(clause, 1)
        if not top or sum(index.weights[term] for term in own & index.terms[top[0][0]]) < 5.0:
            continue
        if top[0] not in found:
            found.append(top[0])
    return found


def catalog_candidates(text: str, limit: int = 3) -> list[tuple[str, str]]:
    index = catalog_index()
    if index is None:
        return []
    found = index.search(text, limit)
    clauses = [part for part in re.split(r"[.;!?]|,\s|\s(?:и|а также|ещё|еще|плюс)\s", text) if _stems(part)]
    if len(clauses) > 1:
        for clause in clauses:
            for item in index.search(clause, 2):
                if item not in found:
                    found.append(item)
    return found[:limit + 1]


def service_title(service_id: str | None) -> str | None:
    index = catalog_index()
    if index is None or not service_id:
        return None
    return index.titles.get(service_id)


def pending_action(messages: list[dict[str, str]]) -> str:
    """The assistant's last concrete offer or question, if its last turn had one."""

    from webapp.advisor import pending_sentence

    return pending_sentence(messages)


def topic_service(messages: list[dict[str, str]]) -> str | None:
    """Catalog id named by the customer's current job, not by an older complaint."""

    from webapp.advisor import topic_service as _topic

    return _topic(messages)


_BUSINESS_QUESTION = re.compile(
    r"сколько|цен[аеуы]|стоим|стоит|прайс|телефон|номер|адрес|наличи|запис|свободн|когда можно|"
    r"работаете|часы работы|есть ли у вас|у вас есть", re.I)
_CONTACT_INTENT = re.compile(
    r"куда (?:с этим )?(?:обращ|ехать|поехать)|обратиться в сервис|написать в сервис|поеду в сервис|"
    r"как (?:это )?(?:описать|объяснить) (?:мастеру|в сервисе|сервису)", re.I)
_ADDITIVE = re.compile(r"\b(?:и ещё|и еще|ещё|еще|также|заодно|кроме того|плюс)\b", re.I)
_BACK_REFERENCE = re.compile(
    r"\b(?:вернёмся|вернемся|возвращаясь|по первому|по прошлому|по тому|про то|тот самый|"
    r"то, что (?:я )?(?:писал|спрашивал)|в начале|раньше)\b", re.I)


def plan_turn(ctx: WriterContext, short_reply: bool) -> WriterContext:
    """Decide how the latest line relates to the conversation and say it in one note."""

    current = ctx.current_task
    new_ids = [sid for sid, _ in ctx.candidates]
    if short_reply and len(ctx.latest) <= 20:
        if ctx.pending:
            ctx.turn_note = (f"Клиент коротко ответил «{ctx.latest}» на реплику консультанта «{ctx.pending}».")
            ctx.opening = ("Если это было предложение — выполни его прямо сейчас (если предлагалось составить "
                           "сообщение, напиши сам текст в кавычках). Если это был вопрос — прими ответ и продолжи.")
        else:
            ctx.turn_note = (f"Клиент написал «{ctx.latest}», но консультант ничего не предлагал и не спрашивал, "
                             "поэтому неясно, на что это ответ. Ничего не проверено, не сделано и не согласовано.")
            ctx.opening = ("Коротко уточни, что клиент имеет в виду, и предложи один конкретный полезный шаг "
                           "по его задаче (например, что уточнить в сервисе или составить для сервиса сообщение).")
        return ctx
    tasks = clause_tasks(ctx.latest)
    if len(tasks) >= 2:
        ctx.mixed = tuple(tasks)
        ctx.turn_note = "Клиент просит несколько работ: " + "; ".join(title for _, title in tasks) + "."
        ctx.opening = "Начни с того, что это разные работы, и назови каждую. Потом ответь на остальные вопросы."
        return ctx
    if _CONTACT_INTENT.search(ctx.latest):
        ctx.opening += (" Клиент собирается обратиться в сервис: последним предложением предложи от первого лица "
                        "составить для сервиса короткое сообщение (например, «Если хотите, составлю…»).")
    if _BACK_REFERENCE.search(ctx.latest) and ctx.earlier_tasks:
        ctx.back_reference = True
        ctx.candidates = [item for item in ctx.candidates if item in ctx.earlier_tasks]
        ctx.turn_note = "Клиент возвращается к теме, которую обсуждали раньше; определи её по списку «Ранее в разговоре»."
        return ctx
    if current and new_ids and current[0] not in new_ids[:2]:
        if _ADDITIVE.search(ctx.latest):
            ctx.turn_note = (f"Клиент добавил ещё одну потребность: {ctx.candidates[0][1]}. "
                             f"Прежняя задача ({current[1]}) остаётся; ответь про новую.")
        else:
            ctx.dropped_symptom = ctx.customer_need
            ctx.switched_to = ctx.candidates[0] if ctx.candidates else None
            ctx.turn_note = (f"Клиент сменил тему: теперь речь о «{ctx.candidates[0][1]}». "
                             "Прежнюю задачу не упоминай.")
            ctx.earlier_tasks = [task for task in ctx.earlier_tasks if task != current] + [current]
            ctx.current_task = None
            ctx.customer_need = ""
            ctx.recent = []
    return ctx


def build_prompt(ctx: WriterContext) -> str:
    lines = []
    if ctx.recent:
        lines.append("НЕДАВНИЙ ДИАЛОГ:")
        for item in ctx.recent:
            who = "Клиент" if item["role"] == "user" else "Консультант"
            lines.append(f"{who}: {item['text'][:TURN_CHARS]}")
        lines.append("")
    lines.append("ФАКТЫ:")
    lines.append(f"Автомобиль клиента: {ctx.vehicle or 'не назван'}. Город: {ctx.city or 'не назван'}.")
    if ctx.customer_need:
        lines.append(f"Что клиент описал ранее: {ctx.customer_need}")
    if ctx.current_task:
        lines.append(f"Текущая задача до этого сообщения: {ctx.current_task[1]}")
    if ctx.earlier_tasks:
        lines.append("Ранее в разговоре: " + "; ".join(title for _, title in ctx.earlier_tasks))
    if ctx.candidates:
        lines.append("Работы из каталога, похожие на последнее сообщение: "
                     + "; ".join(title for _, title in ctx.candidates))
    elif not ctx.current_task:
        lines.append("Работы из каталога, похожие на последнее сообщение: не найдены.")
    if ctx.business_facts:
        lines.append(f"Проверенные данные сервисов: {_compact(ctx.business_facts)}")
    elif _BUSINESS_QUESTION.search(ctx.latest):
        lines.append("Прайсов, телефонов, наличия и записи конкретных сервисов у тебя нет — скажи это одной фразой.")
    else:
        lines.append("Про цены и наличие клиент сейчас не спрашивает — не упоминай их.")
    if ctx.safety_note:
        lines.append(f"Срочно: {ctx.safety_note}")
    lines.append("")
    if ctx.pending and not ctx.turn_note:
        lines.append(f"Последний вопрос или предложение консультанта: «{ctx.pending}»")
    if ctx.turn_note:
        lines.append(f"КАК ПОНЯТЬ ПОСЛЕДНЕЕ СООБЩЕНИЕ: {ctx.turn_note}")
    lines.append(f"ПОСЛЕДНЕЕ СООБЩЕНИЕ КЛИЕНТА: {ctx.latest[:TURN_CHARS * 2]}")
    lines.append(ctx.opening)
    if ctx.advisor_note:
        lines.append(f"ЧТО СДЕЛАТЬ В ЭТОМ ОТВЕТЕ: {ctx.advisor_note}")
    return "\n".join(lines)


def write_reply(ctx: WriterContext, url: str = DEFAULT_URL, timeout: float = TIMEOUT_S) -> WriterResult:
    from webapp.advisor import annotate

    annotate(ctx)
    started = time.perf_counter()

    timings: dict = {}

    def done(text, service_id, origin, reason, tokens=None):
        return WriterResult(text, service_id, origin, reason,
                            round((time.perf_counter() - started) * 1000, 1), tokens, timings or None)

    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        return done(None, None, "fallback", "writer_url_not_local")
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(ctx)},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.2,
        "lora": [{"id": 0, "scale": 0.0}],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    problem = None
    service_id = None
    tokens = None
    for attempt in range(2):
        remaining = timeout - (time.perf_counter() - started)
        if remaining < 3:
            break
        try:
            response = httpx.post(url, json=body, timeout=remaining)
            response.raise_for_status()
            payload = response.json()
            raw = payload["choices"][0]["message"]["content"]
            tokens = (payload.get("usage") or {}).get("completion_tokens")
            raw_timings = payload.get("timings") or {}
            timings.update({key: round(float(raw_timings[key]), 1) for key in
                            ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms") if key in raw_timings})
        except httpx.TimeoutException:
            return done(None, None, "fallback", "timeout")
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            return done(None, None, "fallback", f"model_error:{type(exc).__name__}")
        if not isinstance(raw, str):
            return done(None, None, "fallback", "invalid_output")
        service_id, text = _split_output(raw, ctx)
        problem = check_reply(text, ctx)
        if not problem:
            timings["attempts"] = attempt + 1
            return done(text, service_id, "model", None, tokens)
        body["messages"] = body["messages"][:2] + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": _REWRITE_NOTE.get(problem.split(":")[-1], _REWRITE_NOTE["default"])},
        ]
    timings["attempts"] = 2
    return done(None, service_id, "fallback", problem or "timeout", tokens)


_REWRITE_NOTE = {
    "booking_offer": "Перепиши ответ: записывать ты не можешь, не предлагай запись.",
    "booking": "Перепиши ответ: записи нет и ты не можешь записать клиента.",
    "old_topic": "Перепиши ответ только про новую тему. Прежний симптом не упоминай.",
    "missing_answer": (
        "Перепиши ответ: сначала прямой ответ на последний вопрос. "
        "Если чего-то не хватает, добавь один полезный шаг, который ты реально можешь сделать."
    ),
    "action": "Перепиши ответ: звонить, искать сервисы и записывать ты не можешь.",
    "completed_work": "Перепиши ответ: ничего ещё не проверено и не сделано.",
    "own_shop": "Перепиши ответ без «у нас» и «мы»: ты не мастерская.",
    "default": "Перепиши ответ: только по-русски, коротко, без цен, телефонов, сроков и выдуманных фактов.",
}


def _split_output(raw: str, ctx: WriterContext) -> tuple[str | None, str]:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    raw = re.sub(r"^\s*\**РАБОТА\**\s*:[^\n]*\n?", "", raw, flags=re.I)
    text = re.sub(r"^\s*(?:Консультант|Ответ|ОТВЕТ)\s*:\s*", "", raw.strip())
    text = re.sub(r"\n{2,}", "\n", text).strip().strip('"').strip()
    if text.startswith("«") and text.count("«") == 1 and text.endswith("»"):
        text = text[1:-1].strip()
    if text.count("«") > text.count("»"):
        text += "»"
    return discussed_service(text, ctx), text


def discussed_service(text: str, ctx: WriterContext) -> str | None:
    """The catalog task this turn is about: the one the reply and the customer both touch."""

    if ctx.mixed:
        return None
    reply = set(_stems(text)) | set(_stems(ctx.latest))
    best, best_score = None, 0
    remembered = list(ctx.earlier_tasks) + ([ctx.current_task] if ctx.current_task else [])
    options = remembered + list(ctx.candidates) if ctx.back_reference else list(ctx.candidates) + remembered
    for service_id, title in options:
        score = len(reply & set(_stems(title)))
        if score > best_score:
            best, best_score = service_id, score
    return best


def check_reply(text: str, ctx: WriterContext) -> str | None:
    if not text or len(text) < 4:
        return "empty_output"
    if len(text) > 900:
        return "too_long"
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    cyrillic = re.findall(r"[А-Яа-яЁё]", text)
    if not letters or len(cyrillic) / len(letters) < 0.8:
        return "not_russian"
    if re.search(r"РАБОТА\s*:|ФАКТЫ|ПОСЛЕДНЕЕ СООБЩЕНИЕ|\b[a-z]+-[a-z]+", text):
        return "leaked_context"
    allowed_numbers = set(re.findall(r"\d+", " ".join(
        [ctx.latest, ctx.vehicle, _compact(ctx.business_facts) if ctx.business_facts else ""]
        + [item["text"] for item in ctx.recent if item["role"] == "user"])))
    for pattern, label in _UNSUPPORTED:
        found = pattern.search(text)
        if not found:
            continue
        if label in {"price", "phone", "time"} and ctx.business_facts:
            if set(re.findall(r"\d+", found.group(0))) <= allowed_numbers:
                continue
        if label == "own_shop" and ctx.represents_shop:
            continue
        return f"unsupported_claim:{label}"
    from webapp.advisor import advisor_problem

    extra = advisor_problem(text, ctx)
    if extra == "old_topic":
        return "unsupported_claim:old_topic"
    if extra:
        return extra
    return None


def _compact(facts: dict | None) -> str:
    if not facts:
        return ""
    import json
    return json.dumps(facts, ensure_ascii=False)[:600]


__all__ = [
    "WriterContext", "WriterResult", "catalog_candidates", "pending_action",
    "service_title", "topic_service", "write_reply", "check_reply", "build_prompt",
]
