import pytest

from connector import CompletionUsage, YandexLLMClient, YandexLLMError


def test_complete_messages_success(httpx_mock) -> None:
    httpx_mock.add_response(
        json={
            "result": {
                "alternatives": [
                    {"message": {"role": "assistant", "text": "Привет!"}, "status": "ALTERNATIVE_STATUS_FINAL"}
                ],
                "usage": {
                    "inputTextTokens": "10",
                    "completionTokens": "5",
                    "totalTokens": "15",
                },
                "modelVersion": "25.03.2025",
            }
        }
    )

    client = YandexLLMClient("b1gtest", api_key="secret")
    result = client.complete("Как дела?")

    assert result.text == "Привет!"
    assert result.usage == CompletionUsage(
        input_text_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )

    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["Authorization"] == "Api-Key secret"
    assert request.url == "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


def _completion_body(usage: object) -> dict:
    body = {
        "result": {
            "alternatives": [
                {"message": {"role": "assistant", "text": "Да"}, "status": "ALTERNATIVE_STATUS_FINAL"}
            ],
            "modelVersion": "25.03.2025",
        }
    }
    if usage is not _OMIT:
        body["result"]["usage"] = usage
    return body


class _Omit:
    pass


_OMIT = _Omit()


def test_usage_fields_stay_null_when_omitted(httpx_mock) -> None:
    cases = [
        (_OMIT, None),
        (None, None),
        ({}, CompletionUsage(None, None, None)),
        (
            {"inputTextTokens": "10"},
            CompletionUsage(input_text_tokens=10, completion_tokens=None, total_tokens=None),
        ),
        (
            {"inputTextTokens": 4, "completionTokens": None, "totalTokens": 0},
            CompletionUsage(input_text_tokens=4, completion_tokens=None, total_tokens=0),
        ),
        (
            {"inputTextTokens": 0, "completionTokens": 0, "totalTokens": 0},
            CompletionUsage(0, 0, 0),
        ),
        (
            {"inputTextTokens": "8", "completionTokens": "nope", "totalTokens": 9},
            CompletionUsage(input_text_tokens=8, completion_tokens=None, total_tokens=9),
        ),
        (
            {"inputTextTokens": -3, "completionTokens": 2},
            CompletionUsage(input_text_tokens=-3, completion_tokens=2, total_tokens=None),
        ),
    ]
    for usage, expected in cases:
        httpx_mock.add_response(json=_completion_body(usage))
        with YandexLLMClient("b1gtest", api_key="secret") as client:
            result = client.complete("x")
        assert result.usage == expected


def test_api_error(httpx_mock) -> None:
    httpx_mock.add_response(
        status_code=400,
        json={"error": {"message": "bad folder", "httpCode": 400}},
    )

    client = YandexLLMClient("bad", api_key="secret")
    with pytest.raises(YandexLLMError, match="bad folder") as exc_info:
        client.complete("x")

    assert exc_info.value.status_code == 400


def test_from_env() -> None:
    client = YandexLLMClient.from_env(
        env={
            "YANDEX_CLOUD_FOLDER_ID": "fld",
            "YANDEX_CLOUD_API_KEY": "k",
            "YANDEX_GPT_MODEL": "yandexgpt",
        }
    )
    assert client.folder_id == "fld"
    assert client.model == "yandexgpt"
