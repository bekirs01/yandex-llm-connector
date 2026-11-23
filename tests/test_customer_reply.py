"""Offline checks for the Russian customer reply and its single follow-up."""

from webapp.customer_reply import build_customer_reply, follow_up_question, grounded_quotes


USER = "У меня Kia Rio 2018 года. При торможении вибрирует руль."


def _prediction(slots, evidence):
    return {"slots_after_message": slots, "evidence": evidence}


def test_reply_quotes_only_grounded_evidence_and_asks_one_question():
    prediction = _prediction(
        {"vehicle": "Kia Rio 2018", "observed_context": "braking"},
        [
            {
                "slot": "vehicle",
                "message_id": "m1",
                "raw_text": "Kia Rio 2018 года",
                "kind": "observation",
                "time_scope": "current",
                "supersedes": None,
                "interpretation": "Kia Rio 2018",
            },
            {
                "slot": "observed_context",
                "message_id": "m1",
                "raw_text": "При торможении",
                "kind": "observation",
                "time_scope": "current",
                "supersedes": None,
                "interpretation": "braking",
            },
            {
                "slot": "main_symptom",
                "message_id": "m1",
                "raw_text": "износ дисков",
                "kind": "hypothesis",
                "time_scope": "current",
                "supersedes": None,
                "interpretation": "износ дисков",
            },
        ],
    )
    reply = build_customer_reply(prediction, [USER])
    assert "«Kia Rio 2018 года»" in reply
    assert "«При торможении»" in reply
    assert "износ дисков" not in reply
    assert reply.count("?") == 1
    assert reply.endswith("Что случилось с машиной?")
    assert "диагноз" not in reply.casefold()
    assert "записал" not in reply.casefold()
    assert "мастерская на" not in reply.casefold()


def test_unknown_slot_is_not_asked_again():
    prediction = _prediction(
        {
            "vehicle": "unknown",
            "main_symptom": "вибрация руля",
            "observed_context": "unknown",
            "current_state": "present",
        },
        [],
    )
    assert follow_up_question(prediction) is None
    reply = build_customer_reply(prediction, [USER])
    assert "?" not in reply
    assert "не определяю" in reply
    assert "не создаю" in reply


def test_mismatched_interpretation_is_not_stated():
    prediction = _prediction(
        {"vehicle": "другая машина"},
        [
            {
                "slot": "vehicle",
                "message_id": "m1",
                "raw_text": "Kia Rio 2018 года",
                "kind": "observation",
                "time_scope": "current",
                "supersedes": None,
                "interpretation": "Kia Rio 2018",
            }
        ],
    )
    assert grounded_quotes(prediction, [USER]) == []
    reply = build_customer_reply(prediction, [USER])
    assert "Kia Rio" not in reply
