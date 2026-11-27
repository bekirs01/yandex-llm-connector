"""Read and update feedback for one completed exchange.

The identity is conversation_id plus request_id. This module does not call a
model, does not list transcripts, and does not rewrite the exchange row.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


PSQL = os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")
SOCKET_DIR = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", "/tmp/autoservice-pg")
PORT = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", "54332")
DATABASE = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", "autoservice_assistant")
ROLE = "autoservice_runtime"

_SAFE_REASONS = {
    "invalid conversation_id",
    "invalid request_id",
    "invalid stars",
    "invalid resolved",
    "invalid revision",
    "invalid request",
    "unknown exchange",
}


class ExchangeFeedbackError(Exception):
    """Feedback for one exchange could not be read or saved."""


def read_feedback(conversation_id: str, request_id: str) -> dict[str, Any]:
    """Return one exchange's feedback. Absence of the feedback key means unrated."""

    statement = (
        "select autoservice_api.read_exchange_feedback("
        f"{_uuid_sql(conversation_id, 'invalid conversation_id')}, "
        f"{_uuid_sql(request_id, 'invalid request_id')}"
        ")::text;"
    )
    return _public(_query_json(statement), include_applied=False)


def save_feedback(
    conversation_id: str,
    request_id: str,
    stars: int | None,
    resolved: bool | None,
    revision: int,
) -> dict[str, Any]:
    """Store the full feedback state for one existing exchange.

    A second call with the same pair updates that row. A repeated revision
    with the same values does not add a row. A lower revision leaves the
    stored row in place. An unknown exchange raises and inserts nothing.
    """

    _validate_choice(stars, resolved, revision)
    statement = (
        "select autoservice_api.save_exchange_feedback("
        f"{_uuid_sql(conversation_id, 'invalid conversation_id')}, "
        f"{_uuid_sql(request_id, 'invalid request_id')}, "
        f"{_stars_sql(stars)}, {_bool_sql(resolved)}, {int(revision)}"
        ")::text;"
    )
    return _public(_query_json(statement), include_applied=True)


def parse_save_payload(payload: Any) -> dict[str, Any]:
    """Accept one feedback object. Extra fields and lists are rejected."""

    if not isinstance(payload, dict):
        raise ExchangeFeedbackError("invalid request")
    allowed = {"conversation_id", "request_id", "stars", "resolved", "revision"}
    if set(payload) - allowed:
        raise ExchangeFeedbackError("invalid request")
    if not allowed <= set(payload):
        raise ExchangeFeedbackError("invalid request")
    stars = payload["stars"]
    resolved = payload["resolved"]
    revision = payload["revision"]
    if stars is not None and (isinstance(stars, bool) or not isinstance(stars, int)):
        raise ExchangeFeedbackError("invalid stars")
    if resolved is not None and not isinstance(resolved, bool):
        raise ExchangeFeedbackError("invalid resolved")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise ExchangeFeedbackError("invalid revision")
    _validate_choice(stars, resolved, revision)
    if not isinstance(payload["conversation_id"], str) or not isinstance(payload["request_id"], str):
        raise ExchangeFeedbackError("invalid request")
    return {
        "conversation_id": payload["conversation_id"],
        "request_id": payload["request_id"],
        "stars": stars,
        "resolved": resolved,
        "revision": revision,
    }


def _validate_choice(stars: int | None, resolved: bool | None, revision: int) -> None:
    if stars is not None and not 1 <= stars <= 5:
        raise ExchangeFeedbackError("invalid stars")
    if resolved is not None and not isinstance(resolved, bool):
        raise ExchangeFeedbackError("invalid resolved")
    if not isinstance(revision, int) or isinstance(revision, bool) or not 1 <= revision <= 1_000_000_000:
        raise ExchangeFeedbackError("invalid revision")


def _public(payload: Any, *, include_applied: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExchangeFeedbackError("exchange feedback database call failed")
    conversation_id = payload.get("conversation_id")
    request_id = payload.get("request_id")
    revision = payload.get("revision")
    if not isinstance(conversation_id, str) or not isinstance(request_id, str):
        raise ExchangeFeedbackError("exchange feedback database call failed")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ExchangeFeedbackError("exchange feedback database call failed")
    result: dict[str, Any] = {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "revision": revision,
    }
    if include_applied:
        result["applied"] = payload.get("applied") is True
    if "feedback" in payload and payload["feedback"] is not None:
        feedback = _feedback_object(payload["feedback"])
        if feedback is not None:
            result["feedback"] = feedback
    return result


def _feedback_object(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        raise ExchangeFeedbackError("exchange feedback database call failed")
    stars = value.get("stars")
    resolved = value.get("resolved")
    if stars is not None and (isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5):
        raise ExchangeFeedbackError("exchange feedback database call failed")
    if resolved is not None and not isinstance(resolved, bool):
        raise ExchangeFeedbackError("exchange feedback database call failed")
    if stars is None and resolved is None:
        return None
    return {"stars": stars, "resolved": resolved}


def _uuid_sql(value: str, reason: str) -> str:
    if not isinstance(value, str):
        raise ExchangeFeedbackError(reason)
    text = value.strip().lower()
    if len(text) != 36:
        raise ExchangeFeedbackError(reason)
    return _dollar(text)


def _stars_sql(value: int | None) -> str:
    if value is None:
        return "null"
    return str(int(value))


def _bool_sql(value: bool | None) -> str:
    if value is None:
        return "null"
    return "true" if value else "false"


def _dollar(value: str) -> str:
    tag = "fb"
    while f"${tag}$" in value:
        tag += "x"
    return f"${tag}${value}${tag}$"


def _query_json(statement: str) -> Any:
    if "autoservice_api" not in statement:
        raise ExchangeFeedbackError("exchange feedback database call failed")
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
        _log_failure(str(exc))
        raise ExchangeFeedbackError("exchange feedback database call failed") from exc
    if completed.returncode != 0:
        _log_failure(completed.stderr)
        raise _database_error(completed.stderr)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ExchangeFeedbackError("exchange feedback database call failed") from exc


def _log_failure(detail: str) -> None:
    text = (detail or "").strip() or "no database diagnostic"
    sys.stderr.write(f"exchange feedback database call failed: {text}\n")


def _database_error(stderr: str) -> ExchangeFeedbackError:
    for line in (stderr or "").splitlines():
        text = line.strip()
        marker = text.find("ERROR:")
        if marker < 0:
            continue
        reason = text[marker + len("ERROR:"):].strip()
        if reason in _SAFE_REASONS:
            return ExchangeFeedbackError(reason)
        break
    return ExchangeFeedbackError("exchange feedback database call failed")
