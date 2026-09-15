"""Точка входа AI-сервиса.

Запуск: uvicorn app.main:app --port 8000
"""

from fastapi import FastAPI

from app.config import SERVICE_NAME, SERVICE_VERSION
from app.web.errors import register_error_handlers
from app.web.middleware import register_request_id
from app.web.routes import ai_router, health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sirena-112 AI Service",
        version=SERVICE_VERSION,
        summary="Генерация сценариев, поведение AI-абонента и оценка занятия",
    )

    register_request_id(app)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(ai_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    uvicorn.run(app, host=settings.host, port=settings.port)
