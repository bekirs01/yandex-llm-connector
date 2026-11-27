"""Developer review of saved feedback. This does not call a model.

Classification ("which branch?") stays on the question tree. This module
answers a different question: is the stored exchange a useful training
example? Approval is explicit. A star click never changes the next reply.
The export is a local file of approved examples only. The stored transcript
is left as the customer wrote it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any

from data_layer.customer_questions import CustomerQuestionError, load_exchange_rows


PSQL = os.environ.get("AUTOSERVICE_PSQL", "/opt/homebrew/opt/postgresql@18/bin/psql")
SOCKET_DIR = os.environ.get("AUTOSERVICE_LOCAL_PGSOCKET", "/tmp/autoservice-pg")
PORT = os.environ.get("AUTOSERVICE_LOCAL_PGPORT", "54332")
DATABASE = os.environ.get("AUTOSERVICE_LOCAL_PGDATABASE", "autoservice_assistant")
ROLE = "autoservice_runtime"

BUCKETS = ("positive", "examine", "conflict", "other", "approved", "excluded")
_SAFE_REASONS = {
    "invalid conversation_id",
    "invalid request_id",
    "invalid decision",
    "invalid request",
    "unknown exchange",
    "feedback required",
}
_EMAIL_RE = re.compile(r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\-\s()]{8,18}\d)(?!\d)")
_CONTACT_URL_RE = re.compile(r"(?i)\b(?:https?://)?(?:t\.me|telegram\.me|wa\.me)/[A-Za-z0-9_+\-./]+")


class QualityReviewError(Exception):
    """A training decision could not be read or saved."""


def quality_signal(stars: int | None, resolved: bool | None) -> str | None:
    """Name the quality bucket. None means the exchange has no feedback signal."""

    if stars is None and resolved is None:
        return None
    high = stars in (4, 5)
    low = stars in (1, 2)
    if high and resolved is True:
        return "positive"
    if (high and resolved is False) or (low and resolved is True):
        return "conflict"
    if low or resolved is False:
        return "examine"
    return "other"


def list_quality(bucket: str, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Return one page of the chosen quality bucket, from the full exchange set."""

    if bucket not in BUCKETS:
        raise QualityReviewError("invalid request")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise QualityReviewError("invalid request")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise QualityReviewError("invalid request")
    items = [item for item in _annotated() if item["bucket"] == bucket]
    page = items[offset:offset + limit]
    return {
        "bucket": bucket,
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": [_public_item(item, include_context=True) for item in page],
    }


def save_decision(conversation_id: str, request_id: str, decision: str) -> dict[str, Any]:
    """Record an explicit approve or exclude. The exchange text is not rewritten."""

    if decision not in ("approved", "excluded"):
        raise QualityReviewError("invalid decision")
    if not isinstance(conversation_id, str) or not isinstance(request_id, str):
        raise QualityReviewError("invalid request")
    statement = (
        "select autoservice_api.save_training_review("
        f"{_uuid_sql(conversation_id, 'invalid conversation_id')}, "
        f"{_uuid_sql(request_id, 'invalid request_id')}, "
        f"{_dollar(decision)}"
        ")::text;"
    )
    return _public_decision(_query_json(statement))


def export_approved_jsonl() -> tuple[str, int]:
    """JSONL of explicitly approved examples whose feedback snapshot still matches.

    Contact details and the stored conversation and request ids are removed
    from the file. The database transcript is not updated.
    """

    lines = []
    for item in _annotated():
        if item["bucket"] != "approved":
            continue
        lines.append(json.dumps(_export_record(item), ensure_ascii=False, separators=(",", ":")))
    body = "" if not lines else "\n".join(lines) + "\n"
    return body, len(lines)


def parse_decision_payload(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise QualityReviewError("invalid request")
    allowed = {"conversation_id", "request_id", "decision"}
    if set(payload) != allowed:
        raise QualityReviewError("invalid request")
    if not isinstance(payload["conversation_id"], str) or not isinstance(payload["request_id"], str):
        raise QualityReviewError("invalid request")
    if payload["decision"] not in ("approved", "excluded"):
        raise QualityReviewError("invalid decision")
    return {
        "conversation_id": payload["conversation_id"],
        "request_id": payload["request_id"],
        "decision": payload["decision"],
    }


def redact_customer_text(text: str, identifiers: tuple[str, ...] = ()) -> str:
    """Hide contact details and the given ids. Other words stay in place."""

    if not isinstance(text, str):
        return ""
    cleaned = text
    for identifier in identifiers:
        if identifier:
            cleaned = cleaned.replace(identifier, "[скрыто]")
    cleaned = _EMAIL_RE.sub("[скрыто]", cleaned)
    cleaned = _CONTACT_URL_RE.sub("[скрыто]", cleaned)

    def replace_phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 10 or len(digits) > 15:
            return match.group(0)
        return "[скрыто]"

    return _PHONE_RE.sub(replace_phone, cleaned)


def _annotated() -> list[dict[str, Any]]:
    try:
        rows = load_exchange_rows()
    except CustomerQuestionError as exc:
        raise QualityReviewError("quality review database call failed") from exc
    decisions = {
        (item["conversation_id"], item["request_id"]): item
        for item in _load_decisions()
    }
    by_conversation: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_conversation.setdefault(row["conversation_id"], []).append(row)
    for group in by_conversation.values():
        group.sort(key=lambda row: (row["_sort_at"], row["request_id"]))
    annotated = []
    for row in rows:
        signal = quality_signal(row.get("stars"), row.get("resolved"))
        if signal is None:
            continue
        decision = decisions.get((row["conversation_id"], row["request_id"]))
        reopened = False
        decision_name = None
        if decision is not None:
            decision_name = decision["decision"]
            reopened = (
                decision.get("stars") != row.get("stars")
                or decision.get("resolved") != row.get("resolved")
            )
        if decision_name == "approved" and not reopened:
            bucket = "approved"
        elif decision_name == "excluded" and not reopened:
            bucket = "excluded"
        else:
            bucket = signal
        earlier = [
            item for item in by_conversation.get(row["conversation_id"], [])
            if item["_sort_at"] < row["_sort_at"]
        ]
        annotated.append({
            "row": row,
            "signal": signal,
            "bucket": bucket,
            "decision": decision_name,
            "reopened": reopened,
            "context": earlier[-6:],
        })
    annotated.sort(
        key=lambda item: (
            -item["row"]["_sort_at"].timestamp(),
            item["row"]["conversation_id"],
            item["row"]["request_id"],
        )
    )
    return annotated


def _public_item(item: dict[str, Any], *, include_context: bool) -> dict[str, Any]:
    row = item["row"]
    payload = {
        "conversation_id": row["conversation_id"],
        "request_id": row["request_id"],
        "customer_message": row["customer_message"],
        "assistant_reply": row["assistant_reply"],
        "exchanged_at": row["exchanged_at"],
        "question_types": list(row["question_types"]),
        "service_id": row.get("service_id"),
        "service_label": row.get("service_label"),
        "signal": item["signal"],
        "bucket": item["bucket"],
        "reopened": item["reopened"],
        "decision": item["decision"],
        "feedback": {"stars": row.get("stars"), "resolved": row.get("resolved")},
    }
    if include_context:
        context = []
        for earlier in item["context"]:
            context.append({"speaker": "customer", "text": earlier["customer_message"]})
            context.append({"speaker": "assistant", "text": earlier["assistant_reply"]})
        payload["context"] = context
    return payload


def _export_record(item: dict[str, Any]) -> dict[str, Any]:
    row = item["row"]
    identifiers = (row["conversation_id"], row["request_id"])
    context = []
    for earlier in item["context"]:
        context.append({
            "speaker": "customer",
            "text": redact_customer_text(earlier["customer_message"], identifiers),
        })
        context.append({
            "speaker": "assistant",
            "text": redact_customer_text(earlier["assistant_reply"], identifiers),
        })
    return {
        "example_id": hashlib.sha256(
            f"{row['conversation_id']}:{row['request_id']}".encode("utf-8")
        ).hexdigest()[:16],
        "signal": item["signal"],
        "question": redact_customer_text(row["customer_message"], identifiers),
        "answer": redact_customer_text(row["assistant_reply"], identifiers),
        "context": context,
        "question_types": list(row["question_types"]),
        "service_id": row.get("service_id"),
    }


def _load_decisions() -> list[dict[str, Any]]:
    loaded = _query_json("select autoservice_api.read_training_reviews()::text;")
    if not isinstance(loaded, list):
        raise QualityReviewError("quality review database call failed")
    decisions = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        stars = item.get("stars")
        resolved = item.get("resolved")
        if stars is not None and (isinstance(stars, bool) or not isinstance(stars, int)):
            continue
        if resolved is not None and not isinstance(resolved, bool):
            continue
        decisions.append({
            "conversation_id": item.get("conversation_id"),
            "request_id": item.get("request_id"),
            "decision": item.get("decision"),
            "feedback_revision": item.get("feedback_revision"),
            "stars": stars,
            "resolved": resolved,
        })
    return decisions


def _public_decision(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise QualityReviewError("quality review database call failed")
    decision = payload.get("decision")
    if decision not in ("approved", "excluded"):
        raise QualityReviewError("quality review database call failed")
    return {
        "conversation_id": payload.get("conversation_id"),
        "request_id": payload.get("request_id"),
        "decision": decision,
        "feedback_revision": payload.get("feedback_revision"),
        "stars": payload.get("stars"),
        "resolved": payload.get("resolved"),
    }


def _uuid_sql(value: str, reason: str) -> str:
    text = value.strip().lower()
    if len(text) != 36:
        raise QualityReviewError(reason)
    return _dollar(text)


def _dollar(value: str) -> str:
    tag = "qr"
    while f"${tag}$" in value:
        tag += "x"
    return f"${tag}${value}${tag}$"


def _query_json(statement: str) -> Any:
    if "autoservice_api" not in statement:
        raise QualityReviewError("quality review database call failed")
    env = os.environ.copy()
    env["PGCLIENTENCODING"] = "UTF8"
    try:
        completed = subprocess.run(
            [
                PSQL, "-h", SOCKET_DIR, "-p", PORT, "-U", ROLE, "-d", DATABASE,
                "-v", "ON_ERROR_STOP=1", "-X", "-q", "-t", "-A", "-f", "-",
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
        raise QualityReviewError("quality review database call failed") from exc
    if completed.returncode != 0:
        _log_failure(completed.stderr)
        raise _database_error(completed.stderr)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise QualityReviewError("quality review database call failed") from exc


def _log_failure(detail: str) -> None:
    text = (detail or "").strip() or "no database diagnostic"
    sys.stderr.write(f"quality review database call failed: {text}\n")


def _database_error(stderr: str) -> QualityReviewError:
    for line in (stderr or "").splitlines():
        text = line.strip()
        marker = text.find("ERROR:")
        if marker < 0:
            continue
        reason = text[marker + len("ERROR:"):].strip()
        if reason in _SAFE_REASONS:
            return QualityReviewError(reason)
        break
    return QualityReviewError("quality review database call failed")
