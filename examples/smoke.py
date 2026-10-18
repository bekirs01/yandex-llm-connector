#!/usr/bin/env python3
"""Проверка клиента: python examples/smoke.py (нужен .env или переменные окружения)."""

from connector import YandexLLMClient


def main() -> None:
    client = YandexLLMClient.from_env()
    result = client.complete("Ответь одним словом: работает?")
    print(result.text)
    if result.usage:
        print(f"tokens: {result.usage.total_tokens}")


if __name__ == "__main__":
    main()
