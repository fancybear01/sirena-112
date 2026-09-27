"""Внутреннее API AI-сервиса.

Все методы синхронные и не обращаются к базе данных: весь нужный контекст
приходит в теле запроса от Kotlin Core.

Правило сериализации: незаполненные необязательные поля не попадают в ответ.
Так сценарий проходит contracts/scenario.schema.json, где для необязательных
полей разрешён конкретный тип, но не null.
"""

from fastapi import APIRouter

from app.config import SERVICE_NAME, SERVICE_VERSION, settings
from app.engines import card_text, catalog_scenarios, group_advice, rule_dialogue, rule_scoring
from app.schemas.common import CamelModel
from app.voice.speech import get_pipeline
from app.schemas.dialogue import DialogueRequest, DialogueResponse
from app.schemas.generation import ScenarioGenerateRequest, ScenarioGenerateResponse
from app.schemas.scoring import ScoreRequest, ScoreResponse
from app.schemas.text import (
    GroupRecommendationsRequest,
    GroupRecommendationsResponse,
    TextReviewRequest,
    TextReviewResponse,
)


class HealthResponse(CamelModel):
    status: str
    service: str
    version: str
    engine: str
    # Режим речи виден в health: иначе непонятно, работают настоящие модели
    # или подмены, а на демонстрации это первое, что надо проверить.
    speech: str
    speech_available: bool
    speech_simulated: bool


health_router = APIRouter(tags=["health"])
ai_router = APIRouter(prefix="/ai", tags=["ai"])


@health_router.get("/health", response_model=HealthResponse, summary="Проверка живости")
def health() -> HealthResponse:
    pipeline = get_pipeline()
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
        engine=settings.engine,
        speech=pipeline.describe(),
        speech_available=pipeline.available,
        speech_simulated=pipeline.simulated,
    )


@ai_router.post(
    "/scenarios/generate",
    response_model=ScenarioGenerateResponse,
    summary="Сгенерировать черновики учебных сценариев",
    response_model_exclude_none=True,
)
def generate_scenarios(request: ScenarioGenerateRequest) -> ScenarioGenerateResponse:
    """Возвращает черновики. Публикацию сценария подтверждает преподаватель в Core."""
    return catalog_scenarios.generate(request)


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
    return rule_scoring.score(request)


@ai_router.post(
    "/text/review",
    response_model=TextReviewResponse,
    summary="Разобрать текст карточки: смысл, грамотность, регламент, время",
    response_model_exclude_none=True,
)
def review_text(request: TextReviewRequest) -> TextReviewResponse:
    """Разбирает то, что оператор написал руками.

    У каждого вывода указана измеренная точность, а вывод, которому верить
    нельзя, помечен как требующий проверки преподавателем.
    """
    return card_text.review(request)


@ai_router.post(
    "/groups/recommendations",
    response_model=GroupRecommendationsResponse,
    summary="Рекомендации преподавателю по типичным ошибкам группы",
    response_model_exclude_none=True,
)
def group_recommendations(
    request: GroupRecommendationsRequest,
) -> GroupRecommendationsResponse:
    """Считает по присланным отчётам. Своей истории и базы у AI нет."""
    return group_advice.recommend(request)
