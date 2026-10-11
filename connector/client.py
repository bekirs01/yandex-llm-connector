from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

import httpx

from connector.exceptions import YandexLLMError

Role = Literal["system", "user", "assistant"]
Message = Mapping[str, str]

COMPLETION_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


@dataclass(frozen=True, slots=True)
class CompletionUsage:
    input_text_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    model_version: str | None
    usage: CompletionUsage | None
    raw: dict[str, Any]


class YandexLLMClient:
    """Синхронный клиент YandexGPT через Foundation Models API."""

    def __init__(
        self,
        folder_id: str,
        *,
        api_key: str | None = None,
        iam_token: str | None = None,
        model: str = "yandexgpt-lite",
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key and not iam_token:
            raise ValueError("Укажите api_key или iam_token")
        if api_key and iam_token:
            raise ValueError("Укажите только один способ авторизации: api_key или iam_token")

        self.folder_id = folder_id
        self.model = model
        self._api_key = api_key
        self._iam_token = iam_token
        self._owns_client = client is None
        self._http = client or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, *, env: Mapping[str, str] | None = None) -> YandexLLMClient:
        """Создаёт клиент из переменных окружения (см. .env.example)."""
        source = env if env is not None else os.environ
        folder_id = source.get("YANDEX_CLOUD_FOLDER_ID", "").strip()
        if not folder_id:
            raise ValueError("YANDEX_CLOUD_FOLDER_ID не задан")

        api_key = source.get("YANDEX_CLOUD_API_KEY", "").strip() or None
        iam_token = source.get("YANDEX_IAM_TOKEN", "").strip() or None
        model = source.get("YANDEX_GPT_MODEL", "yandexgpt-lite").strip() or "yandexgpt-lite"

        return cls(
            folder_id,
            api_key=api_key,
            iam_token=iam_token,
            model=model,
        )

    def _auth_header(self) -> str:
        if self._api_key:
            return f"Api-Key {self._api_key}"
        return f"Bearer {self._iam_token}"

    def _model_uri(self) -> str:
        return f"gpt://{self.folder_id}/{self.model}/latest"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> CompletionResult:
        """Один пользовательский запрос (опционально с system-промптом)."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "text": system})
        messages.append({"role": "user", "text": prompt})
        return self.complete_messages(messages, max_tokens=max_tokens, temperature=temperature)

    def complete_messages(
        self,
        messages: Sequence[Message],
        *,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> CompletionResult:
        """Диалог в формате role/text (system, user, assistant)."""
        payload = {
            "modelUri": self._model_uri(),
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": max_tokens,
            },
            "messages": [{"role": m["role"], "text": m["text"]} for m in messages],
        }

        response = self._http.post(
            COMPLETION_URL,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if response.status_code != httpx.codes.OK:
            self._raise_api_error(response)

        data = response.json()
        return self._parse_completion(data)

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> YandexLLMClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        try:
            body = response.json()
            message = body.get("error", {}).get("message") or body.get("message") or response.text
        except ValueError:
            message = response.text
        raise YandexLLMError(str(message), status_code=response.status_code)

    @staticmethod
    def _parse_completion(data: dict[str, Any]) -> CompletionResult:
        result = data.get("result") or {}
        alternatives = result.get("alternatives") or []
        if not alternatives:
            raise YandexLLMError("Пустой ответ: нет alternatives")

        text = alternatives[0].get("message", {}).get("text", "")
        usage_raw = result.get("usage") or {}
        usage: CompletionUsage | None = None
        if usage_raw:
            usage = CompletionUsage(
                input_text_tokens=int(usage_raw.get("inputTextTokens", 0)),
                completion_tokens=int(usage_raw.get("completionTokens", 0)),
                total_tokens=int(usage_raw.get("totalTokens", 0)),
            )

        return CompletionResult(
            text=text,
            model_version=result.get("modelVersion"),
            usage=usage,
            raw=data,
        )
