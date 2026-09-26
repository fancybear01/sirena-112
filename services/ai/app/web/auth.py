"""Проверка сервисного токена.

Токен нужен для того, чтобы к внутреннему API AI ходил только Core и Media,
а не кто попало из той же сети. Если переменная AI_SERVICE_TOKEN не задана,
проверка выключена: в разработке и в тестах она только мешает.

Сравнение идёт по байтам, а не по строкам. hmac.compare_digest со строками
падает на не-ASCII символах, а заголовок Authorization приходит от клиента -
значит, в нём может оказаться что угодно. Без этого один запрос с кривым
заголовком отвечал не 401, а 500.
"""

import hmac
import os
from typing import Optional

ENVIRONMENT_VARIABLE = "AI_SERVICE_TOKEN"
HEADER = "authorization"


def required() -> bool:
    """Включена ли проверка. Пустая переменная означает выключена."""
    return bool(os.getenv(ENVIRONMENT_VARIABLE, ""))


def accepted(header_value: Optional[str]) -> bool:
    """Подходит ли заголовок Authorization под настроенный токен."""
    token = os.getenv(ENVIRONMENT_VARIABLE, "")
    if not token:
        return True

    expected = ("Bearer " + token).encode("utf-8")
    # Заголовки приходят байтами, а сервер раскодирует их как latin-1.
    # Обратное кодирование возвращает исходные байты без потерь. Символы,
    # которые в latin-1 не влезают, заменяются - такой заголовок всё равно
    # не подойдёт, и ответ будет 401.
    supplied = (header_value or "").encode("latin-1", "replace")
    return hmac.compare_digest(supplied, expected)
