"""Сквозной идентификатор запроса.

Core проставляет X-Request-ID, AI подхватывает его и возвращает обратно,
чтобы один вызов можно было проследить по логам всех сервисов.
"""

from uuid import uuid4

from fastapi import FastAPI, Request

HEADER = "X-Request-ID"


def register_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get(HEADER) or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[HEADER] = request_id
        return response
