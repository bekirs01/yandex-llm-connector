class YandexLLMError(Exception):
    """Ошибка вызова Yandex Foundation Models API."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
