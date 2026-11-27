"""Check the local extraction route while keeping the Yandex route unchanged."""

import json
import unittest
from unittest import mock

from webapp.chat_service import ChatService


REQUEST_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION_ID = "22222222-2222-4222-8222-222222222222"


def test_local_model_response():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract",
                                 "AUTOSERVICE_REPLY_WRITER": "off"})
    payload = {"request_id": REQUEST_ID, "conversation_id": CONVERSATION_ID,
               "messages": [{"role": "user", "text": "У меня Nissan Leaf 2019"}]}
    prediction = {"slots_after_message": {"vehicle": "Nissan Leaf, 2019"}, "evidence": []}
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = prediction
    with mock.patch("webapp.chat_service.httpx.post", return_value=response) as post:
        status, body = service.handle_chat(payload)
    assert status == 200
    assert body["structured"] == prediction
    assert "Nissan Leaf, 2019" in body["message"]["text"]
    assert "марку, модель и год" not in body["message"]["text"]
    assert not body["message"]["text"].lstrip().startswith("{")
    assert service.health()["provider"] == "local"
    post.assert_called_once_with("http://127.0.0.1:8767/extract",
                                 json={"messages": payload["messages"]}, timeout=1800.0)


def test_stage_timings_do_not_change_the_reply():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract",
                                 "AUTOSERVICE_REPLY_WRITER": "off"})
    payload = {"request_id": REQUEST_ID, "conversation_id": CONVERSATION_ID,
               "messages": [{"role": "user", "text": "У меня Nissan Leaf 2019"}]}
    prediction = {
        "slots_after_message": {"vehicle": "Nissan Leaf, 2019"},
        "evidence": [],
        "stage_ms": {"catalog_shortlist_ms": 1.5, "mica_ms": 20, "qwen_ms": 30.25},
    }
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = prediction
    with mock.patch("webapp.chat_service.httpx.post", return_value=response):
        status, body = service.handle_chat(payload)
    assert status == 200
    assert "Nissan Leaf, 2019" in body["message"]["text"]
    assert body["structured"] == {
        "slots_after_message": {"vehicle": "Nissan Leaf, 2019"},
        "evidence": [],
    }
    assert body["metrics"]["stages"] == {
        "catalog_shortlist_ms": 1.5,
        "mica_ms": 20.0,
        "qwen_ms": 30.2,
        "reply_plan_ms": body["metrics"]["stages"]["reply_plan_ms"],
        "retrieval_ms": None,
    }
    assert body["metrics"]["stages"]["reply_plan_ms"] >= 0


def test_social_turn_does_not_call_extractors_or_invent_an_intake_form():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract",
                                 "AUTOSERVICE_REPLY_WRITER": "off"})
    payload = {"request_id": REQUEST_ID, "conversation_id": CONVERSATION_ID,
               "messages": [{"role": "user", "text": "Привт"}]}
    with mock.patch("webapp.chat_service.httpx.post") as post:
        status, body = service.handle_chat(payload)
    assert status == 200
    assert body["metrics"]["route"] == "conversation"
    assert body["metrics"]["extraction_skipped"] is True
    assert "марку, модель" not in body["message"]["text"]
    post.assert_not_called()


def test_thanks_plus_price_is_not_treated_as_plain_thanks():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract",
                                 "AUTOSERVICE_REPLY_WRITER": "off"})
    payload = {"request_id": REQUEST_ID, "conversation_id": CONVERSATION_ID,
               "messages": [
                   {"role": "user", "text": "Нужно поменять масло"},
                   {"role": "assistant", "text": "Понял вас: замена масла."},
                   {"role": "user", "text": "Спасибо, а сколько это стоит?"},
               ]}
    with mock.patch("webapp.chat_service.httpx.post") as post:
        status, body = service.handle_chat(payload)
    assert status == 200
    text = body["message"]["text"].casefold()
    assert "сумму не называю" in text or "цены" in text
    assert body["metrics"]["extraction_skipped"] is True
    post.assert_not_called()


class LocalRouteTests(unittest.TestCase):
    def test_social_turn_skips_the_model(self) -> None:
        test_social_turn_does_not_call_extractors_or_invent_an_intake_form()

    def test_price_follow_up_skips_extraction(self) -> None:
        test_thanks_plus_price_is_not_treated_as_plain_thanks()

    def test_vehicle_fact_still_uses_the_extractor(self) -> None:
        test_local_model_response()


def test_local_model_rejects_invalid_schema():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract",
                                 "AUTOSERVICE_REPLY_WRITER": "off"})
    response = mock.Mock()
    response.status_code = 200
    response.json.return_value = {"message": "unstructured"}
    with mock.patch("webapp.chat_service.httpx.post", return_value=response):
        status, body = service.handle_chat({
            "request_id": REQUEST_ID, "conversation_id": CONVERSATION_ID,
            "messages": [{"role": "user", "text": "У меня Nissan Leaf 2019"}],
        })
    assert status == 200
    assert body["metrics"]["response_origin"] == "degraded"
    assert body["metrics"]["degraded"] is True
    assert body["model"] is None
    assert "structured" not in body
    assert "Nissan Leaf, 2019" in body["message"]["text"]
