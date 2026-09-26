"""Точка входа AI-сервиса.

Запуск: uvicorn app.main:app --port 8090
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import SERVICE_VERSION
from app.web import auth
from app.web.errors import register_error_handlers
from app.web.middleware import register_request_id
from app.web.routes import ai_router, health_router
from app.web.voice_routes import stream_router, voice_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sirena-112 AI Service",
        version=SERVICE_VERSION,
        summary="Генерация сценариев, поведение AI-абонента и оценка занятия",
    )

    register_request_id(app)

    @app.middleware("http")
    async def require_service_token(request: Request, call_next):
        """Пускает к /ai/ только со сервисным токеном, если он настроен.

        /health остаётся открытым: по нему проверяют живость контейнера,
        и токена у healthcheck нет.
        """
        if request.url.path.startswith("/ai/") and not auth.accepted(
            request.headers.get(auth.HEADER)
        ):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(ai_router)
    app.include_router(voice_router)
    app.include_router(stream_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    uvicorn.run(app, host=settings.host, port=settings.port)
