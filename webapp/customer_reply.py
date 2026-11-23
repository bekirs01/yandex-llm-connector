"""Build one Russian customer reply from a validated local extraction.

Stated facts are verbatim customer quotes that the extraction evidence ties to a
slot. The reply asks at most one follow-up and does not diagnose, book, or name
a workshop.
"""

from __future__ import annotations

from typing import Any

# Schema questions for slots a customer can answer without a workshop search.
FOLLOW_UPS = (
    ("vehicle", "Какая у вас машина: марка, модель и примерно год?"),
    ("main_symptom", "Что случилось с машиной?"),
    ("observed_context", "Когда вы это замечаете?"),
    ("current_state", "Что происходит сейчас?"),
)

def grounded_quotes(prediction: dict[str, Any], user_texts: list[str]) -> list[str]:
    """Return evidence quotes that match the slot value and a customer message."""

    slots = prediction.get("slots_after_message")
    evidence = prediction.get("evidence")
    if not isinstance(slots, dict) or not isinstance(evidence, list):
        return []
    quotes: list[str] = []
    for entry in evidence:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("raw_text")
        slot = entry.get("slot")
        interpretation = entry.get("interpretation")
        if not isinstance(raw, str) or raw == "":
            continue
        if not isinstance(slot, str) or not isinstance(interpretation, str):
            continue
        if slots.get(slot) != interpretation:
            continue
        if not any(isinstance(text, str) and raw in text for text in user_texts):
            continue
        if raw not in quotes:
            quotes.append(raw)
    return quotes


def follow_up_question(prediction: dict[str, Any]) -> str | None:
    """Ask the first useful slot that has no recorded value."""

    slots = prediction.get("slots_after_message")
    if not isinstance(slots, dict):
        slots = {}
    for slot, question in FOLLOW_UPS:
        value = slots.get(slot)
        if isinstance(value, str) and value.strip():
            continue
        return question
    return None


def build_customer_reply(prediction: dict[str, Any], user_texts: list[str]) -> str:
    """Return the customer-facing Russian text for one extraction."""

    if not isinstance(prediction, dict):
        prediction = {}
    if not isinstance(user_texts, list):
        user_texts = []
    quotes = grounded_quotes(prediction, user_texts)
    if quotes:
        quoted = "; ".join(f"«{item}»" for item in quotes)
        text = f"Понял. Вы написали: {quoted}."
    else:
        text = "Понял ваше сообщение."
    question = follow_up_question(prediction)
    if question:
        return f"{text} {question}"
    return f"{text} Причину по переписке не определяю и запись в мастерскую не создаю."
