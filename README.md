# Yandex LLM Connector

Python-клиент для **YandexGPT** через [Foundation Models API](https://yandex.cloud/ru/docs/foundation-models/).

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
