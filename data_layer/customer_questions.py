"""Persist and read the live customer question tree.

Completed exchanges stay out of the synthetic dialogue tables. Grouping uses
the service, category, and question types supplied by the caller. A service
id that exists in the catalog takes that catalog category. Uncertain or
unresolved turns stay in the review view and are not merged into another
service's price, equipment, or booking leaf.

Wave 3 can call ``record_exchange`` after the customer has been shown the
final reply, then ``read_question_tree`` for the browser. This module does
not call a model and does not serve HTTP.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PSQL = os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")
SOCKET_DIR = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", "/tmp/autoservice-pg")
PORT = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", "54332")
DATABASE = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", "autoservice_assistant")
ROLE = "autoservice_runtime"

QUESTION_TYPES = (
    "price",
    "equipment",
    "booking",
    "availability",
    "hours",
    "diagnosis",
    "workshop",
)
_QUESTION_LABELS = {
    "price": "Цена",
    "equipment": "Наличие оборудования",
    "booking": "Запись",
    "availability": "Свободное окно",
    "hours": "Часы работы",
    "diagnosis": "Диагностика",
    "workshop": "Мастерская",
}
_TYPE_ALIASES = {
    "equipment-availability": "equipment",
    "equipment_availability": "equipment",
}
_VIEWS = {"tree", "frequent", "review"}
_ROOT_LABELS = {
    "tree": "Вопросы клиентов",
    "frequent": "Частые вопросы",
    "review": "Нужна проверка",
}
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TYPE_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
_NODE_ID_RE = re.compile(
    r"^(?:root"
    r"|category:[a-z0-9]+(?:-[a-z0-9]+)*"
    r"|service:[a-z0-9]+(?:-[a-z0-9]+)*"
    r"|leaf:[a-z0-9]+(?:-[a-z0-9]+)*:[a-z][a-z0-9-]{0,40}"
    r"|review:service:[a-z0-9]+(?:-[a-z0-9]+)*:[a-z][a-z0-9-]{0,40}"
    r"|review:supplied:[a-z0-9]+(?:-[a-z0-9]+)*:[a-z][a-z0-9-]{0,40}"
    r"|review:exchange:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r":[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)
_READ_SQL = (
    "select coalesce(json_agg(row_to_json(rows)), '[]'::json)::text "
    "from ("
    "select conversation_id, request_id, customer_message, assistant_reply, "
    "exchanged_at, service_id, service_title, category_id, "
    "supplied_service_id, supplied_category_id, resolution, question_types, "
    "stars, resolved "
    "from autoservice_api.customer_exchanges"
    ") rows;"
)
_CATEGORY_LABELS: dict[str, str] | None = None


class CustomerQuestionError(Exception):
    """A question-tree read or write could not be completed."""


def record_exchange(
    conversation_id: str,
    request_id: str,
    customer_message: str,
    assistant_reply: str,
    exchanged_at: datetime | str,
    service_id: str | None = None,
    category_id: str | None = None,
    question_types: Sequence[str] | None = None,
    uncertain: bool = False,
) -> dict[str, Any]:
    """Store one completed exchange.

    The identity is the conversation id plus the request id. A second call
    with that pair returns the first record and does not add a transcript
    or a question-type membership. ``membership_count`` is the number of
    question types on this exchange, not the leaf total.
    """

    statement = _record_statement(
        conversation_id,
        request_id,
        customer_message,
        assistant_reply,
        exchanged_at,
        service_id,
        category_id,
        question_types,
        uncertain,
    )
    payload = _query_json(statement)
    if not isinstance(payload, dict):
        raise CustomerQuestionError("question tree database call failed")
    return _public_record(payload)


def conversation_exchanges(conversation_id: str) -> list[dict[str, Any]]:
    """Return this conversation's stored exchanges, oldest first."""

    conversation = _uuid(conversation_id, "invalid conversation_id")
    loaded = _query_json(
        "select coalesce(json_agg(row_to_json(rows) order by rows.exchanged_at), '[]'::json)::text "
        "from (select request_id, customer_message, assistant_reply, exchanged_at, service_id "
        "from autoservice_api.customer_exchanges "
        f"where conversation_id = {_dollar(conversation)}) rows;"
    )
    if not isinstance(loaded, list):
        raise CustomerQuestionError("question tree database call failed")
    return [item for item in loaded if isinstance(item, dict)]


def read_question_tree(
    node_id: str | None = None,
    *,
    view: str = "tree",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Return one question-tree node, its children, and a page of history.

    ``view`` is ``tree`` (category, service, question type), ``frequent``
    (the same resolved nodes, with leaves first by exchange count), or
    ``review`` (uncertain placements). ``exchange_count`` is distinct
    exchanges. ``membership_count`` counts question-type placements, so one
    price-and-booking exchange contributes 1 and 2. ``rating_count`` and
    ``average_stars`` use that same full node scope, not the history page.
    """

    if view not in _VIEWS:
        raise CustomerQuestionError("invalid view")
    _check_page(limit, offset)
    if node_id is not None and (not isinstance(node_id, str) or _NODE_ID_RE.fullmatch(node_id) is None):
        raise CustomerQuestionError("unknown node")
    return _assemble(load_exchange_rows(), node_id or "root", view, limit, offset, _category_labels())


def load_exchange_rows() -> list[dict[str, Any]]:
    """Return every stored exchange, including saved feedback when it exists."""

    loaded = _query_json(_READ_SQL)
    if not isinstance(loaded, list):
        raise CustomerQuestionError("question tree database call failed")
    return [_normalize_row(item) for item in loaded if isinstance(item, dict)]


def read_panel_revision() -> str:
    """Return one token that changes when the tree, feedback, or a review decision changes."""

    loaded = _query_json("select json_build_object('revision', autoservice_api.panel_revision())::text;")
    if not isinstance(loaded, dict):
        raise CustomerQuestionError("question tree database call failed")
    revision = loaded.get("revision")
    if not isinstance(revision, str) or not revision.strip():
        raise CustomerQuestionError("question tree database call failed")
    return revision


def locate_exchange(
    conversation_id: str,
    request_id: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Find the view, branch, and history page for one stored exchange.

    A resolved exchange opens on its service node, so a price-and-booking
    turn has one location. Review-only and older rows use the stored
    placement. The offset is computed from the full branch, not by walking
    pages in the browser.
    """

    conversation = _uuid(conversation_id, "invalid conversation_id")
    request = _uuid(request_id, "invalid request_id")
    _check_page(limit, 0)
    rows = load_exchange_rows()
    match = next(
        (
            row for row in rows
            if row["conversation_id"] == conversation and row["request_id"] == request
        ),
        None,
    )
    if match is None:
        raise CustomerQuestionError("unknown exchange")
    view, node_id = _locate_target(match)
    population = [
        row for row in rows
        if (row["resolution"] != "resolved") == (view == "review")
    ]
    grouped = _index(population)
    focus = population if node_id == "root" else grouped.get(node_id, [])
    history = _ordered_unique(focus)
    index = next(
        (
            position for position, row in enumerate(history)
            if row["conversation_id"] == conversation and row["request_id"] == request
        ),
        None,
    )
    if index is None:
        raise CustomerQuestionError("unknown exchange")
    offset = (index // limit) * limit
    return {
        "conversation_id": conversation,
        "request_id": request,
        "view": view,
        "node_id": node_id,
        "category_id": match.get("category_id"),
        "service_id": match.get("service_id"),
        "offset": offset,
        "limit": limit,
        "index": index,
    }


def _check_page(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 100:
        raise CustomerQuestionError("invalid limit")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise CustomerQuestionError("invalid offset")


def _locate_target(row: dict[str, Any]) -> tuple[str, str]:
    if (
        row.get("resolution") == "resolved"
        and row.get("service_id")
        and row.get("category_id")
        and row.get("question_types")
    ):
        return "tree", f"service:{row['service_id']}"
    nodes = _result_node_ids(row)
    return "review", nodes[0]


def _record_statement(
    conversation_id: str,
    request_id: str,
    customer_message: str,
    assistant_reply: str,
    exchanged_at: datetime | str,
    service_id: str | None,
    category_id: str | None,
    question_types: Sequence[str] | None,
    uncertain: bool,
) -> str:
    conversation = _uuid(conversation_id, "invalid conversation_id")
    request = _uuid(request_id, "invalid request_id")
    message = _exact_text(customer_message, "invalid customer_message", 4000)
    reply = _exact_text(assistant_reply, "invalid assistant_reply", 8000)
    timestamp = _timestamp(exchanged_at)
    service = _optional_slug(service_id, "invalid service_id")
    category = _optional_slug(category_id, "invalid category_id")
    types = _question_types(question_types)
    if not isinstance(uncertain, bool):
        raise CustomerQuestionError("invalid uncertain")
    encoded_types = json.dumps(types, ensure_ascii=False, separators=(",", ":"))
    uncertain_sql = "true" if uncertain else "false"
    return (
        "select autoservice_api.record_customer_exchange("
        f"{_dollar(conversation)}, {_dollar(request)}, {_dollar(message)}, "
        f"{_dollar(reply)}, {_dollar(timestamp)}::timestamptz, "
        f"{_sql_text(service)}, {_sql_text(category)}, "
        f"{_dollar(encoded_types)}::jsonb, {uncertain_sql});"
    )


def _public_record(payload: dict[str, Any]) -> dict[str, Any]:
    question_types = _string_list(payload.get("question_types"))
    row = {
        "conversation_id": payload.get("conversation_id"),
        "request_id": payload.get("request_id"),
        "resolution": payload.get("resolution"),
        "service_id": payload.get("service_id"),
        "category_id": payload.get("category_id"),
        "supplied_service_id": payload.get("supplied_service_id"),
        "supplied_category_id": payload.get("supplied_category_id"),
        "question_types": question_types,
    }
    return {
        "recorded": bool(payload.get("recorded")),
        "conversation_id": row["conversation_id"],
        "request_id": row["request_id"],
        "resolution": row["resolution"],
        "needs_review": row["resolution"] != "resolved",
        "category_id": row["category_id"],
        "service_id": row["service_id"],
        "supplied_service_id": row["supplied_service_id"],
        "supplied_category_id": row["supplied_category_id"],
        "question_types": question_types,
        "membership_count": _placements(row),
        "nodes": _result_node_ids(row),
    }


def _assemble(
    rows: list[dict[str, Any]],
    selected: str,
    view: str,
    limit: int,
    offset: int,
    labels: dict[str, str],
) -> dict[str, Any]:
    if _NODE_ID_RE.fullmatch(selected) is None:
        raise CustomerQuestionError("unknown node")
    population = [
        row for row in rows
        if (row["resolution"] != "resolved") == (view == "review")
    ]
    grouped = _index(population)
    if selected != "root" and selected not in grouped:
        raise CustomerQuestionError("unknown node")
    focus = population if selected == "root" else grouped[selected]
    history = _ordered_unique(focus)
    return {
        "view": view,
        "node": _make_node(selected, view, focus, labels),
        "children": _children(selected, view, population, grouped, labels),
        "history": {
            "total": len(history),
            "limit": limit,
            "offset": offset,
            "exchanges": [
            _history_item(row, labels) for row in history[offset:offset + limit]
        ],
        },
    }


def _children(
    selected: str,
    view: str,
    population: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    if selected.startswith("leaf:") or selected.startswith("review:"):
        return []
    if view == "review":
        if selected != "root":
            return []
        nodes = [
            _make_node(node_id, view, grouped[node_id], labels)
            for node_id in grouped
        ]
        return _sort_children(nodes, "frequent")
    if selected == "root" and view == "frequent":
        nodes = [
            _make_node(node_id, view, grouped[node_id], labels)
            for node_id in grouped
            if node_id.startswith("leaf:")
        ]
        return _sort_children(nodes, "frequent")
    if selected == "root":
        identifiers = {f"category:{row['category_id']}" for row in population}
    elif selected.startswith("category:"):
        category_id = selected.split(":", 1)[1]
        identifiers = {
            f"service:{row['service_id']}"
            for row in population
            if row["category_id"] == category_id
        }
    elif selected.startswith("service:"):
        service_id = selected.split(":", 1)[1]
        identifiers = {
            f"leaf:{service_id}:{question_type}"
            for row in population
            if row["service_id"] == service_id
            for question_type in row["question_types"]
        }
    else:
        return []
    nodes = [
        _make_node(node_id, view, grouped[node_id], labels)
        for node_id in identifiers
        if node_id in grouped
    ]
    return _sort_children(nodes, view)


def _make_node(
    node_id: str,
    view: str,
    rows: list[dict[str, Any]],
    labels: dict[str, str],
) -> dict[str, Any]:
    parsed = _parse_node(node_id, view)
    kind = parsed["kind"]
    category_id = parsed.get("category_id")
    service_id = parsed.get("service_id")
    supplied_service_id = parsed.get("supplied_service_id")
    supplied_category_id = parsed.get("supplied_category_id")
    question_type = parsed.get("question_type")
    sample = rows[0] if rows else None
    if kind == "root":
        category_id = None
        service_id = None
        question_type = None
        supplied_service_id = None
        supplied_category_id = None
    elif kind == "category":
        service_id = None
        question_type = None
        supplied_service_id = None
        supplied_category_id = None
    elif kind == "service" and sample is not None:
        question_type = None
        category_id = sample.get("category_id")
        supplied_service_id = None
        supplied_category_id = None
    elif kind == "question_type" and sample is not None:
        category_id = sample.get("category_id")
        supplied_category_id = sample.get("supplied_category_id")
        if service_id is None:
            supplied_service_id = supplied_service_id or sample.get("supplied_service_id")
    elif kind == "exchange" and sample is not None:
        category_id = sample.get("category_id")
        service_id = sample.get("service_id")
        supplied_service_id = sample.get("supplied_service_id")
        supplied_category_id = sample.get("supplied_category_id")
        types = sample["question_types"]
        question_type = types[0] if len(types) == 1 else None
    per_type = kind == "question_type"
    exchange_count, membership_count = _counts(rows, per_type=per_type)
    rating_count, average_stars = _ratings(rows)
    category_label = _category_label(category_id, labels)
    if category_label is None:
        category_label = _category_label(supplied_category_id, labels)
    service_label = _service_label(rows, service_id, supplied_service_id)
    if kind == "root":
        label = _ROOT_LABELS[view]
        category_label = None
        service_label = None
    elif kind == "category":
        label = category_label or category_id or node_id
        service_label = None
    elif kind == "service":
        label = service_label or service_id or node_id
    elif question_type:
        label = _QUESTION_LABELS.get(question_type, question_type)
    else:
        label = "Нужна проверка"
    return {
        "id": node_id,
        "kind": parsed["kind"],
        "label": label,
        "exchange_count": exchange_count,
        "membership_count": membership_count,
        "rating_count": rating_count,
        "average_stars": average_stars,
        "needs_review": parsed["needs_review"],
        "category_id": category_id,
        "category_label": category_label,
        "service_id": service_id,
        "service_label": service_label,
        "question_type": question_type,
        "supplied_service_id": supplied_service_id,
        "supplied_category_id": supplied_category_id,
    }


def _parse_node(node_id: str, view: str) -> dict[str, Any]:
    if node_id == "root":
        return {"kind": "root", "needs_review": view == "review"}
    if node_id.startswith("category:"):
        return {
            "kind": "category",
            "needs_review": False,
            "category_id": node_id.split(":", 1)[1],
        }
    if node_id.startswith("service:"):
        return {
            "kind": "service",
            "needs_review": False,
            "service_id": node_id.split(":", 1)[1],
        }
    if node_id.startswith("leaf:"):
        service_id, question_type = node_id[len("leaf:"):].rsplit(":", 1)
        return {
            "kind": "question_type",
            "needs_review": False,
            "service_id": service_id,
            "question_type": question_type,
        }
    if node_id.startswith("review:service:"):
        service_id, question_type = node_id[len("review:service:"):].rsplit(":", 1)
        return {
            "kind": "question_type",
            "needs_review": True,
            "service_id": service_id,
            "question_type": question_type,
        }
    if node_id.startswith("review:supplied:"):
        supplied_service_id, question_type = node_id[len("review:supplied:"):].rsplit(":", 1)
        return {
            "kind": "question_type",
            "needs_review": True,
            "supplied_service_id": supplied_service_id,
            "question_type": question_type,
        }
    if node_id.startswith("review:exchange:"):
        return {"kind": "exchange", "needs_review": True}
    raise CustomerQuestionError("unknown node")


def _result_node_ids(row: dict[str, Any]) -> list[str]:
    question_types = row.get("question_types") or []
    service_id = row.get("service_id")
    supplied_service_id = row.get("supplied_service_id")
    category_id = row.get("category_id")
    if (
        row.get("resolution") == "resolved"
        and service_id
        and category_id
        and question_types
    ):
        return [
            f"category:{category_id}",
            f"service:{service_id}",
            *[f"leaf:{service_id}:{question_type}" for question_type in question_types],
        ]
    if service_id and question_types:
        return [
            f"review:service:{service_id}:{question_type}"
            for question_type in question_types
        ]
    if supplied_service_id and question_types:
        return [
            f"review:supplied:{supplied_service_id}:{question_type}"
            for question_type in question_types
        ]
    return [f"review:exchange:{row['conversation_id']}:{row['request_id']}"]


def _index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for node_id in _result_node_ids(row):
            grouped.setdefault(node_id, []).append(row)
    return grouped


def _counts(rows: list[dict[str, Any]], *, per_type: bool) -> tuple[int, int]:
    unique = _unique(rows)
    exchange_count = len(unique)
    if per_type:
        return exchange_count, exchange_count
    return exchange_count, sum(_placements(row) for row in unique.values())


def _ratings(rows: list[dict[str, Any]]) -> tuple[int, float | None]:
    """Distinct rated exchanges in the node. One shared exchange counts once."""

    rated = [
        row["stars"]
        for row in _unique(rows).values()
        if isinstance(row.get("stars"), int) and not isinstance(row.get("stars"), bool)
    ]
    if not rated:
        return 0, None
    return len(rated), round(sum(rated) / len(rated), 4)


def _placements(row: dict[str, Any]) -> int:
    count = len(row.get("question_types") or [])
    if row.get("resolution") == "resolved":
        return count
    if count and (row.get("service_id") or row.get("supplied_service_id")):
        return count
    return 1


def _unique(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["conversation_id"], row["request_id"]): row for row in rows}


def _ordered_unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = _unique(rows)
    return sorted(
        unique.values(),
        key=lambda row: (-row["_sort_at"].timestamp(), row["conversation_id"], row["request_id"]),
    )


def _history_item(row: dict[str, Any], labels: dict[str, str]) -> dict[str, Any]:
    category_id = row["category_id"]
    category_label = _category_label(category_id, labels)
    if category_label is None:
        category_label = _category_label(row["supplied_category_id"], labels)
    item = {
        "conversation_id": row["conversation_id"],
        "request_id": row["request_id"],
        "customer_message": row["customer_message"],
        "assistant_reply": row["assistant_reply"],
        "exchanged_at": row["exchanged_at"],
        "question_types": list(row["question_types"]),
        "needs_review": row["resolution"] != "resolved",
        "service_id": row["service_id"],
        "service_label": row["service_label"] or row["supplied_service_id"],
        "category_id": category_id,
        "category_label": category_label,
        "supplied_service_id": row["supplied_service_id"],
        "supplied_category_id": row["supplied_category_id"],
    }
    feedback = _public_feedback(row)
    if feedback is not None:
        item["feedback"] = feedback
    return item


def _public_feedback(row: dict[str, Any]) -> dict[str, Any] | None:
    stars = row.get("stars")
    resolved = row.get("resolved")
    if stars is None and resolved is None:
        return None
    return {"stars": stars, "resolved": resolved}


def _sort_children(nodes: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
    if view == "frequent":
        return sorted(
            nodes,
            key=lambda node: (-node["exchange_count"], -node["membership_count"], node["id"]),
        )
    return sorted(nodes, key=lambda node: (str(node["label"]).casefold(), node["id"]))


def _normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    exchanged = _parse_time(str(raw.get("exchanged_at") or ""))
    title = raw.get("service_title")
    service_label = None
    if isinstance(title, str) and title.strip():
        service_label = title.strip().rstrip(".").strip()
    resolution = raw.get("resolution")
    return {
        "conversation_id": raw.get("conversation_id"),
        "request_id": raw.get("request_id"),
        "customer_message": raw.get("customer_message"),
        "assistant_reply": raw.get("assistant_reply"),
        "exchanged_at": exchanged.isoformat(),
        "_sort_at": exchanged,
        "service_id": raw.get("service_id"),
        "service_label": service_label,
        "category_id": raw.get("category_id"),
        "supplied_service_id": raw.get("supplied_service_id"),
        "supplied_category_id": raw.get("supplied_category_id"),
        "resolution": resolution,
        "question_types": _string_list(raw.get("question_types")),
        "stars": _optional_stars(raw.get("stars")),
        "resolved": _optional_resolved(raw.get("resolved")),
    }


def _optional_stars(value: Any) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 1 <= value <= 5:
        return None
    return value


def _optional_resolved(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _service_label(
    rows: list[dict[str, Any]],
    service_id: str | None,
    supplied_service_id: str | None,
) -> str | None:
    if service_id:
        for row in rows:
            if row.get("service_id") == service_id and row.get("service_label"):
                return row["service_label"]
        return service_id
    return supplied_service_id


def _category_label(category_id: str | None, labels: dict[str, str]) -> str | None:
    if not category_id:
        return None
    return labels.get(category_id, category_id)


def _category_labels() -> dict[str, str]:
    global _CATEGORY_LABELS
    if _CATEGORY_LABELS is not None:
        return _CATEGORY_LABELS
    labels: dict[str, str] = {}
    path = ROOT / "autoservice_dataset" / "schema" / "catalog.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _CATEGORY_LABELS = labels
        return labels
    profiles = document.get("profiles") if isinstance(document, dict) else None
    if isinstance(profiles, dict):
        for key, profile in profiles.items():
            if not isinstance(key, str) or not isinstance(profile, dict):
                continue
            title = profile.get("source_section_title")
            if isinstance(title, str) and title.strip():
                labels[key] = title.strip()
    _CATEGORY_LABELS = labels
    return labels


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        parsed = json.loads(value)
        value = parsed
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str)})


def _uuid(value: str, message: str) -> str:
    if not isinstance(value, str) or _UUID_RE.fullmatch(value.lower()) is None:
        raise CustomerQuestionError(message)
    return value.lower()


def _exact_text(value: str, message: str, limit: int) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise CustomerQuestionError(message)
    if not value.strip() or len(value) > limit:
        raise CustomerQuestionError(message)
    return value


def _optional_slug(value: str | None, message: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CustomerQuestionError(message)
    text = value.strip().lower()
    if text == "":
        return None
    if len(text) > 80 or _SLUG_RE.fullmatch(text) is None:
        raise CustomerQuestionError(message)
    return text


def _question_types(value: Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CustomerQuestionError("invalid question_types")
    found: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise CustomerQuestionError("invalid question_types")
        token = item.strip().lower()
        canonical = _TYPE_ALIASES.get(token, token)
        if _TYPE_RE.fullmatch(canonical) is None:
            raise CustomerQuestionError("invalid question_types")
        found.add(canonical)
    return sorted(found)


def _timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = _parse_time(value)
    else:
        raise CustomerQuestionError("invalid exchanged_at")
    if parsed.tzinfo is None:
        raise CustomerQuestionError("invalid exchanged_at")
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    if re.fullmatch(r".*[+-]\d\d$", text):
        text += ":00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CustomerQuestionError("invalid exchanged_at") from exc
    if parsed.tzinfo is None:
        raise CustomerQuestionError("invalid exchanged_at")
    return parsed.astimezone(timezone.utc)


def _sql_text(value: str | None) -> str:
    if value is None:
        return "null"
    return _dollar(value)


def _dollar(value: str) -> str:
    tag = "msg"
    while f"${tag}$" in value:
        tag += "x"
    return f"${tag}${value}${tag}$"


def _query_json(statement: str) -> Any:
    if "autoservice_api" not in statement:
        raise CustomerQuestionError("question tree access must use the runtime interface")
    env = os.environ.copy()
    env["PGCLIENTENCODING"] = "UTF8"
    try:
        completed = subprocess.run(
            [
                PSQL,
                "-h", SOCKET_DIR,
                "-p", PORT,
                "-U", ROLE,
                "-d", DATABASE,
                "-v", "ON_ERROR_STOP=1",
                "-X",
                "-q",
                "-t",
                "-A",
                "-f", "-",
            ],
            input=statement,
            text=True,
            capture_output=True,
            check=False,
            timeout=8,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log_database_failure(str(exc))
        raise CustomerQuestionError("question tree database call failed") from exc
    if completed.returncode != 0:
        _log_database_failure(completed.stderr)
        raise _database_error(completed.stderr)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CustomerQuestionError("question tree database call failed") from exc


def _log_database_failure(detail: str) -> None:
    text = (detail or "").strip()
    if not text:
        text = "no database diagnostic"
    sys.stderr.write(f"question tree database call failed: {text}\n")


def _database_error(stderr: str) -> CustomerQuestionError:
    for line in (stderr or "").splitlines():
        text = line.strip()
        if not text.startswith("ERROR:"):
            continue
        reason = text.split(":", 1)[1].strip()
        if reason.startswith("invalid "):
            return CustomerQuestionError(reason)
        break
    return CustomerQuestionError("question tree database call failed")
