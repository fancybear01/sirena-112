"""Общие типы и базовая модель.

Наружу всё отдаётся в camelCase, чтобы Kotlin Core и frontend читали ответы
без дополнительных преобразований. Внутри кода используется snake_case.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


def to_camel(value: str) -> str:
    """snake_case -> camelCase."""
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    """Базовая модель: camelCase наружу, неизвестные поля запрещены.

    Запрет неизвестных полей выбран намеренно: на интеграции лучше получить
    понятную ошибку с именем поля, чем молча потерять данные.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class OpenCamelModel(CamelModel):
    """Модель, допускающая дополнительные поля.

    Используется там, где схема контракта разрешает additionalProperties:
    это позволит добавить поля классификатора происшествий, не ломая Core.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class ErrorDetail(CamelModel):
    """Одна конкретная проблема в запросе."""

    field: str
    message: str


class ApiError(CamelModel):
    """Формат ошибки, повторяющий ApiError из Kotlin Core."""

    timestamp: str
    status: int
    code: str
    message: str
    path: str
    request_id: Optional[str] = None
    details: Optional[List[ErrorDetail]] = None


class ResponseMeta(CamelModel):
    """Служебная информация об ответе, одинаковая для всех эндпоинтов."""

    engine: str
    version: str
    deterministic: bool
