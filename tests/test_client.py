import pytest

from connector import YandexLLMClient, YandexLLMError


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
    assert result.usage is not None
    assert result.usage.total_tokens == 15

    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["Authorization"] == "Api-Key secret"
    assert request.url == "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


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
