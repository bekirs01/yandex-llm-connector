"""Check the local extraction route while keeping the Yandex route unchanged."""

import json
from unittest import mock

from webapp.chat_service import ChatService


REQUEST_ID = "11111111-1111-4111-8111-111111111111"
CONVERSATION_ID = "22222222-2222-4222-8222-222222222222"


def test_local_model_response():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract"})
    payload = {"request_id": REQUEST_ID, "conversation_id": CONVERSATION_ID,
               "messages": [{"role": "user", "text": "У меня Nissan Leaf 2019"}]}
    prediction = {"slots_after_message": {"vehicle": "Nissan Leaf, 2019"}, "evidence": []}
    response = mock.Mock()
    response.json.return_value = prediction
    with mock.patch("webapp.chat_service.httpx.post", return_value=response) as post:
        status, body = service.handle_chat(payload)
    assert status == 200
    assert body["structured"] == prediction
    assert body["message"]["text"] == (
        "Новых сведений не вижу. Оставляю как есть: Nissan Leaf, 2019."
    )
    assert not body["message"]["text"].lstrip().startswith("{")
    assert service.health()["provider"] == "local"
    post.assert_called_once_with("http://127.0.0.1:8767/extract",
                                 json={"messages": payload["messages"]}, timeout=1800.0)


def test_local_model_rejects_invalid_schema():
    service = ChatService(env={"AUTOSERVICE_MODEL_URL": "http://127.0.0.1:8767/extract"})
    response = mock.Mock()
    response.json.return_value = {"message": "unstructured"}
    with mock.patch("webapp.chat_service.httpx.post", return_value=response):
        status, body = service.handle_chat({
            "request_id": REQUEST_ID, "conversation_id": CONVERSATION_ID,
            "messages": [{"role": "user", "text": "У меня Nissan Leaf 2019"}],
        })
    assert status == 502
    assert body["error"]["code"] == "INVALID_MODEL_OUTPUT"
