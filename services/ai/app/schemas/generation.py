"""Модели запроса на подбор сценариев.

Преподаватель выбирает тему занятия и сложность, сервис возвращает подходящие
сценарии каталога. Поля сценария при этом не переписываются: идентификаторы,
признаки и службы должны совпадать с тем, что использует Core.

Сценарий становится доступен обучающимся только после подтверждения
преподавателем, и это решение принимает Core, а не AI.
"""

from typing import List, Optional

from pydantic import Field

from app.schemas.common import CamelModel, ResponseMeta
from app.schemas.scenario import Category, Difficulty, Scenario


class ScenarioGenerateRequest(CamelModel):
    category: Optional[Category] = None
    difficulty: Optional[Difficulty] = None
    count: int = Field(default=1, ge=1, le=20)
    # seed сдвигает начало выборки, чтобы на повторных занятиях выпадали
    # разные сценарии. Один и тот же запрос всегда даёт один и тот же набор.
    seed: int = Field(default=0, ge=0)


class ScenarioGenerateResponse(CamelModel):
    scenarios: List[Scenario]
    meta: ResponseMeta
