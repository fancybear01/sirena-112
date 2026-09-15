"""Единый формат ошибок.

Повторяет ApiError из Kotlin Core, чтобы Core и frontend разбирали ошибки
любого сервиса одинаково.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ApiError, ErrorDetail

VALIDATION_MESSAGE = "Запрос не соответствует контракту сервиса"

# Константа задана числом: имя этого статуса в starlette менялось между
# версиями, а код ответа стабилен.
HTTP_422_VALIDATION = 422


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "")


def _error_response(
    request: Request,
    http_status: int,
    code: str,
    message: str,
    details: Optional[List[ErrorDetail]] = None,
) -> JSONResponse:
    request_id = _request_id(request)
    payload = ApiError(
        timestamp=_now(),
        status=http_status,
        code=code,
        message=message,
        path=request.url.path,
        request_id=request_id or None,
        details=details,
    )
    response = JSONResponse(status_code=http_status, content=payload.model_dump(by_alias=True))
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


def _field_path(location) -> str:
    """Превращает путь pydantic в читаемое имя поля.

    Первый элемент это источник данных (body, query), он не нужен пользователю.
    """
    parts = [str(item) for item in location[1:]] or [str(item) for item in location]
    return ".".join(parts)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(field=_field_path(error["loc"]), message=error["msg"])
            for error in exc.errors()
        ]
        return _error_response(
            request,
            HTTP_422_VALIDATION,
            "VALIDATION_ERROR",
            VALIDATION_MESSAGE,
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == status.HTTP_404_NOT_FOUND else "HTTP_ERROR"
        message = exc.detail if isinstance(exc.detail, str) else "Ошибка обработки запроса"
        return _error_response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "Внутренняя ошибка сервиса",
        )
