# Yandex LLM Connector

Python-клиент для **YandexGPT** через [Foundation Models API](https://yandex.cloud/ru/docs/foundation-models/).

## Local chat preview

From the repository root, using the project virtual environment:

```bash
source .venv/bin/activate
python -m webapp.server
```

Open http://127.0.0.1:8766 . The process listens on `127.0.0.1` only. Pass `--port` if `8766` is already taken. The older single-prompt demo is a separate process on port `8765`.

Opening the page and `GET /api/health` does not call Yandex. `POST /api/chat` calls Yandex only when a folder id and exactly one of the API key or IAM token are present in the environment or in a local `.env` file. A filled configuration is not proof that those credentials work. The server always adds its own instruction to answer in Russian; the interface language does not change that instruction, and a live Russian reply still has to be observed against the provider.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Настройка

```bash
cp .env.example .env
```

| Переменная | Описание |
|------------|----------|
| `YANDEX_CLOUD_FOLDER_ID` | ID каталога в Yandex Cloud |
| `YANDEX_CLOUD_API_KEY` | API-ключ сервисного аккаунта (`Authorization: Api-Key …`) |
| `YANDEX_IAM_TOKEN` | Альтернатива: IAM-токен (`Authorization: Bearer …`) |
| `YANDEX_GPT_MODEL` | Имя модели без префикса, по умолчанию `yandexgpt-lite` |

Не коммитьте `.env` и файлы ключей.

## Использование

```python
from connector import YandexLLMClient

client = YandexLLMClient(
    folder_id="b1g...",
    api_key="AQV...",
    model="yandexgpt-lite",
)

answer = client.complete("Привет! Кратко: что такое API?")
print(answer.text)

# или из окружения
client = YandexLLMClient.from_env()
```

Диалог с несколькими сообщениями:

```python
client.complete_messages(
    [
        {"role": "system", "text": "Ты лаконичный ассистент."},
        {"role": "user", "text": "Два плюс два?"},
    ],
    temperature=0.1,
    max_tokens=100,
)
```

Проверка:

```bash
python examples/smoke.py
```

## Структура

```
yandex-llm-connector/
├── connector/          # пакет клиента
├── examples/
├── tests/
├── pyproject.toml
└── .env.example
```

## Тесты

```bash
pytest
```
