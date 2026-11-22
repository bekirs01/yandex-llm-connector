# Yandex LLM Connector

Python-клиент для **YandexGPT** через [Foundation Models API](https://yandex.cloud/ru/docs/foundation-models/).

## Local chat preview

### Локальные модели Mica + Qwen

В `local_models/` включены обученные адаптеры Mica и Qwen, схема слотов, код извлечения и запуск трёх локальных сервисов. Большие **базовые** модели скачиваются при настройке из Hugging Face с закреплёнными ревизиями; файлы весов не входят в Git. Для Windows нужны Python 3.12, свободное место примерно 6 ГБ, доступ к Hugging Face и установленный `llama-server` из [llama.cpp](https://github.com/ggml-org/llama.cpp) в `PATH`.

Из корня репозитория в PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r local_models\requirements.txt
.\.venv\Scripts\python.exe local_models\setup_models.py
.\.venv\Scripts\python.exe local_models\start_preview.py
```

Открыть http://127.0.0.1:8766 . `Ctrl+C` останавливает запущенные этим скриптом сервисы. Базовые модели загружаются один раз. Для проверки напишите, например: `У меня Skoda Octavia 2018 года. После дождя в салоне пахнет сыростью и запотевают стёкла. Я в Екатеринбурге.` На CPU ответ может занимать около двух минут.

Интерфейс сейчас показывает **JSON извлечённых слотов и evidence**, а не разговорный ответ. Формирование ответа и диалоговый движок остаются отдельными компонентами. Это локальная демонстрация с обученными адаптерами; её нельзя выдавать за точное воспроизведение ранее опубликованных метрик: Mica здесь запускается через GGUF/llama.cpp и простой выбор метки, а не через прежний ограниченный readout логитов.

Для другой реализации сервера установите `AUTOSERVICE_MODEL_URL` на локальный `/extract`: веб-приложение отправляет `{"messages": [{"role": "user", "text": "..."}]}` и ожидает `slots_after_message` (object) и `evidence` (array).

From the repository root, using the project virtual environment:

```bash
source .venv/bin/activate
python -m webapp.server
```

Open http://127.0.0.1:8766 . The process listens on `127.0.0.1` only. Pass `--port` if `8766` is already taken. The older single-prompt demo is a separate process on port `8765`.

Opening the page and `GET /api/health` does not call Yandex. `POST /api/chat` calls Yandex when a folder id and exactly one of the API key or IAM token are supplied. Open “Настройки сервиса” to enter an API key or IAM token and, optionally, a folder id. The token overrides server credentials for that request; a blank folder id uses the server setting. These fields last until the page reloads and are not saved to browser storage or `.env`. With a blank token, credentials come from the environment or local `.env` file. A filled configuration is not proof that those credentials work. The server always adds its own instruction to answer in Russian; the interface language does not change that instruction, and a live Russian reply still has to be observed against the provider.

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
