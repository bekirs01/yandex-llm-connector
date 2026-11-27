"""Retrieve catalog rows and dialogue-flow hints for one customer turn.

The connection uses the restricted runtime role and the retrieval views.
Those views hide the development holdout and the final test split.
Retrieved dialogue text is not returned to the reply composer: other
customers' vehicles, symptoms, and cities must not be copied. The composer
receives service titles and a count of how the similar replies were shaped.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PSQL = os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")
SOCKET_DIR = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", "/tmp/autoservice-pg")
PORT = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", "54332")
DATABASE = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", "autoservice_assistant")
ROLE = "autoservice_runtime"
_TOKEN = re.compile(r"[0-9a-zа-я]{4,}", re.IGNORECASE)
_GENERIC = {
    "замен", "замена", "помен", "провер", "проверка", "ремонт", "нужно", "нужен",
    "сделать", "хочу", "можно", "машина", "машину", "автомобиль", "просто",
    "сейчас", "очень", "этот", "этого", "как", "что", "для", "при", "уже",
    "только", "тоже", "меня", "мне", "есть", "будет", "было", "сколько",
    "стоит", "стоимость", "когда", "приехать", "сервис", "работы", "работа",
    "спасибо", "поменять", "заменить", "проверить", "сделать",
    "после", "перед", "потом", "такая", "такой", "крутит", "смотреть",
    "заводится", "проблема", "обратно", "отдать", "отдельно", "планирую",
    "воскресенье", "работаете", "сегодня", "влезть", "нынче", "прям",
}
_GENERIC_TITLE_WORDS = {
    "работа", "работы", "работ", "автомобиль", "автомобиля", "машина", "машины",
    "услуга", "услуги", "нужна", "нужен", "нужно",
}
_GENERIC_PREFIXES = (
    "помен", "замен", "провер", "ремон", "сдела", "нужн", "хочу", "можн",
    "снять", "снят", "постав", "устан", "диагн", "спаси", "сколь", "стоит",
)
_CATALOG: list[dict] | None = None


@dataclass(frozen=True)
class RetrievedService:
    service_id: str
    title: str
    score: int = 0


@dataclass(frozen=True)
class RetrievalResult:
    services: tuple[RetrievedService, ...]
    dialogue_ids: tuple[str, ...]
    example_count: int
    single_question_replies: int
    backend: str
    elapsed_ms: float
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "service_ids": [item.service_id for item in self.services],
            "dialogue_ids": list(self.dialogue_ids),
            "example_count": self.example_count,
            "single_question_replies": self.single_question_replies,
            "backend": self.backend,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


def retrieve(messages: list[dict[str, str]]) -> RetrievalResult:
    """Search the local retrieval views. Failure leaves the reply ungrounded."""

    started = time.perf_counter()
    query = " ".join(item["text"] for item in messages if item["role"] == "user")[-2000:]
    try:
        catalog = _catalog()
        services = rank_services(catalog, query, limit=2)
        dialogue_ids, examples, single = _dialogue_flow(_distinctive_tokens(query))
        backend = "local-postgres"
        error = None
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        services = ()
        dialogue_ids, examples, single = (), 0, 0
        backend = "unavailable"
        error = type(exc).__name__
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    return RetrievalResult(services, dialogue_ids, examples, single, backend, elapsed, error)


def rank_services(catalog: list[dict], query: str, limit: int = 3) -> tuple[RetrievedService, ...]:
    """Rank catalog rows by distinctive words shared with the customer.

    A symptom that merely names a part, or a question about opening hours,
    is allowed to match nothing. A short prefix of an unrelated word does
    not count.
    """

    if not _worth_ranking(query):
        return ()
    tokens = _distinctive_tokens(query)
    if not tokens:
        return ()
    scored: list[tuple[int, int, RetrievedService]] = []
    long_hits: dict[str, set[str]] = {}
    for row in catalog:
        haystack = _fold(row["source_title"] + " " + " ".join(row.get("aliases") or []))
        matched = [token for token in tokens if _title_hit(token, haystack)]
        if not matched:
            continue
        for token in matched:
            # A long tool name such as "дымогенератором" belongs to one row.
            # A short word such as "воздух" must not tie that row.
            if len(token) >= 12:
                long_hits.setdefault(token, set()).add(row["service_id"])
        whole = sum(1 for token in matched if re.search(rf"(?<![0-9a-zа-я]){re.escape(token[:4])}", haystack))
        service = RetrievedService(
            row["service_id"],
            row["source_title"].strip().rstrip("."),
            len(set(matched)) + whole,
        )
        scored.append((service.score, -len(service.title), service))
    unique_ids = {next(iter(ids)) for ids in long_hits.values() if len(ids) == 1}
    if len(unique_ids) == 1:
        winner = next(iter(unique_ids))
        adjusted: list[tuple[int, int, RetrievedService]] = []
        for score, length, service in scored:
            if service.service_id == winner:
                service = RetrievedService(service.service_id, service.title, score + 4)
                score = service.score
            adjusted.append((score, length, service))
        scored = adjusted
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen: list[RetrievedService] = []
    seen: set[str] = set()
    for _score, _length, service in scored:
        if service.service_id in seen:
            continue
        seen.add(service.service_id)
        chosen.append(service)
        if len(chosen) >= limit:
            break
    return tuple(chosen)


def confident_service(result: RetrievalResult | None) -> RetrievedService | None:
    """One catalog row clear enough to name the job.

    A tie, or a lead of a single point, stays unnamed. The title is a work
    name only: it does not prove a tool, a price, or an open appointment.
    """

    if result is None or result.error or not result.services:
        return None
    top = result.services[0]
    if top.score < 3:
        return None
    others = [item.score for item in result.services[1:]]
    if others and top.score - max(others) < 2:
        return None
    return top


def thin_service_query(text: str) -> bool:
    """True when the latest line is a job request without its own nouns.

    A short follow-up such as "эту проверку" needs the service already named
    in the conversation. A new job brings its own words and must be searched alone.
    """

    if not _worth_ranking(text):
        return False
    return not _distinctive_tokens(text)


def _catalog() -> list[dict]:
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    raw = _sql(
        "select coalesce(json_agg(json_build_object("
        "'service_id', service_id, 'source_title', source_title, 'aliases', aliases"
        ")), '[]'::json)::text from autoservice_api.services;"
    )
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("service catalog was not a list")
    _CATALOG = parsed
    return _CATALOG


def _dialogue_flow(tokens: list[str]) -> tuple[tuple[str, ...], int, int]:
    distinctive = [token for token in tokens if token not in _GENERIC and not token.isdigit() and len(token) >= 5]
    if not distinctive:
        return (), 0, 0
    needle = max(distinctive, key=len)
    literal = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("'", "''")
    raw = _sql(
        "select coalesce(json_agg(row_to_json(rows)), '[]'::json)::text from ("
        "select dialogue_id, turn_index, role, body from autoservice_api.turns "
        "where dialogue_id in ("
        "select dialogue_id from autoservice_api.turns "
        f"where role = 'user' and body ilike '%{literal}%' escape '\\' "
        "limit 6) "
        "order by dialogue_id, turn_index"
        ") rows;"
    )
    rows = json.loads(raw)
    hidden = _hidden_ids()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        dialogue_id = row.get("dialogue_id")
        if not isinstance(dialogue_id, str) or dialogue_id in hidden or dialogue_id.startswith("test_"):
            continue
        grouped.setdefault(dialogue_id, []).append(row)
    ids: list[str] = []
    single = 0
    examples = 0
    for dialogue_id, turns in grouped.items():
        turns.sort(key=lambda item: item.get("turn_index") or 0)
        for index, turn in enumerate(turns):
            body = turn.get("body") or ""
            if turn.get("role") != "user" or needle not in _fold(body):
                continue
            following = next((item for item in turns[index + 1:] if item.get("role") == "assistant"), None)
            if following is None:
                continue
            examples += 1
            reply = following.get("body") or ""
            if reply.count("?") == 1:
                single += 1
            if dialogue_id not in ids:
                ids.append(dialogue_id)
            break
        if len(ids) >= 4:
            break
    return tuple(ids), examples, single


def _hidden_ids() -> set[str]:
    path = ROOT / "benchmark" / "dev_dialogue_ids.json"
    if not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return set(payload.get("dialogue_ids") or [])


def _content_tokens(text: str) -> list[str]:
    return _TOKEN.findall(_fold(text))


def _title_hit(token: str, haystack: str) -> bool:
    """True when token and a title word share a real stem, not a 4-letter accident."""

    if len(token) < 5:
        return False
    for match in re.finditer(r"[0-9a-zа-я-]{5,}", haystack):
        word = match.group(0)
        if word in _GENERIC_TITLE_WORDS:
            continue
        shared = 0
        for left, right in zip(token, word):
            if left != right:
                break
            shared += 1
        if shared < 5:
            continue
        longest = max(len(token), len(word))
        if abs(len(token) - len(word)) > 2:
            continue
        if shared / longest < 0.75:
            continue
        return True
    return False


_WORK_CUES = (
    "замен", "помен", "снять", "снят", "постав", "провер", "глян", "посмотр",
    "диагност", "ремонт", "перебор", "установ", "шиномонтаж", "развал",
    "балансир", "отрегул",
)
_SYMPTOM_ONLY = (
    "крутит", "стучит", "греет", "дымит", "пищит", "пинает", "орёт", "орет",
    "дует", "жрет", "жрёт", "скрежет", "не заводится", "не работает",
)


def _worth_ranking(query: str) -> bool:
    folded = _fold(query)
    if any(stem in folded for stem in ("воскрес", "график работ", "работаете ли", "вы работаете")):
        if not any(cue in folded for cue in ("шиномонтаж", "замен", "помен", "диагност")):
            return False
    folded = re.sub(r"не\s+про\s+\w+", " ", folded)
    if any(cue in folded for cue in _WORK_CUES):
        return True
    # "нужна эндоскопия цилиндров" names a catalog job without a work verb.
    if re.search(r"нужн", folded) and _distinctive_tokens(folded):
        return True
    # Naming a part while describing what it does is not a request to repair it.
    if any(stem in folded for stem in _SYMPTOM_ONLY):
        return False
    return False


def _distinctive_tokens(text: str) -> list[str]:
    tokens = []
    for token in _content_tokens(text):
        if token in _GENERIC or token.isdigit():
            continue
        if any(token.startswith(prefix) for prefix in _GENERIC_PREFIXES):
            continue
        tokens.append(token)
    return tokens


def _fold(text: str) -> str:
    return text.casefold().replace("ё", "е")


def _sql(statement: str) -> str:
    if "autoservice_api" not in statement:
        raise ValueError("retrieval must read the runtime views")
    completed = subprocess.run(
        [
            PSQL, "-h", SOCKET_DIR, "-p", PORT, "-U", ROLE, "-d", DATABASE,
            "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A", "-c", statement,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=4,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        raise subprocess.SubprocessError(message or f"psql exited {completed.returncode}")
    line = next((item.strip() for item in completed.stdout.splitlines() if item.strip()), "[]")
    return line

