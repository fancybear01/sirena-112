"""Настройки AI-сервиса.

Сервис не имеет доступа к основной схеме PostgreSQL и не хранит бизнес-состояние.
Весь контекст приходит от Kotlin Core в теле запроса.
"""

import os

SERVICE_NAME = "sirena-ai"
SERVICE_VERSION = "0.1.0"


class Settings:
    """Параметры запуска, читаются из окружения."""

    def __init__(self) -> None:
        self.host = os.getenv("AI_HOST", "0.0.0.0")
        self.port = int(os.getenv("AI_PORT", "8000"))
        # engine определяет реализацию генерации, диалога и оценки.
        # На этом этапе доступен только mock, локальные модели подключаются
        # отдельными задачами и не меняют контракт.
        self.engine = os.getenv("AI_ENGINE", "mock")


settings = Settings()
