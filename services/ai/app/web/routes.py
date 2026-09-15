"""Внутреннее API AI-сервиса.

Все методы синхронные и не обращаются к базе данных: весь нужный контекст
приходит в теле запроса от Kotlin Core.

Правило сериализации: незаполненные необязательные поля не попадают в ответ.
Так сценарий проходит contracts/scenario.schema.json, где для необязательных
полей разрешён конкретный тип, но не null.
"""

from fastapi import APIRouter

from app.config import SERVICE_NAME, SERVICE_VERSION, settings
from app.engines import mock_scenarios, mock_scoring, rule_dialogue
from app.schemas.common import CamelModel
from app.schemas.dialogue import DialogueRequest, DialogueResponse
from app.schemas.generation import ScenarioGenerateRequest, ScenarioGenerateResponse
from app.schemas.scoring import ScoreRequest, ScoreResponse


class HealthResponse(CamelModel):
    status: str
    service: str
    version: str
    engine: str


health_router = APIRouter(tags=["health"])
ai_router = APIRouter(prefix="/ai", tags=["ai"])


@health_router.get("/health", response_model=HealthResponse, summary="Проверка живости")
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        engine=settings.engine,
    )


@ai_router.post(
    "/scenarios/generate",
    response_model=ScenarioGenerateResponse,
    summary="Сгенерировать черновики учебных сценариев",
    response_model_exclude_none=True,
)
def generate_scenarios(request: ScenarioGenerateRequest) -> ScenarioGenerateResponse:
    """Возвращает черновики. Публикацию сценария подтверждает преподаватель в Core."""
    return mock_scenarios.generate(request)


@ai_router.post(
    "/dialogue/respond",
    response_model=DialogueResponse,
    summary="Получить реплику AI-абонента",
    response_model_exclude_none=True,
)
def dialogue_respond(request: DialogueRequest) -> DialogueResponse:
    """Отвечает на реплику оператора в пределах фактов сценария."""
    return rule_dialogue.respond(request)


@ai_router.post(
    "/sessions/score",
    response_model=ScoreResponse,
    summary="Оценить завершённую учебную сессию",
    response_model_exclude_none=True,
)
def score_session(request: ScoreRequest) -> ScoreResponse:
    """Считает объяснимый отчёт. Итоговую оценку сохраняет Core, а не AI."""
    return mock_scoring.score(request)
