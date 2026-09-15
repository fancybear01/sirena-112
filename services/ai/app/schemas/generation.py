"""Модели запроса на генерацию сценариев.

Преподаватель выбирает тему занятия и сложность, сервис возвращает черновики.
Сценарий становится доступен обучающимся только после подтверждения
преподавателем, это решение принимает Core, а не AI.
"""

from typing import List, Optional

from pydantic import Field

from app.schemas.common import CamelModel, ResponseMeta
from app.schemas.scenario import Category, Difficulty, Scenario


class ScenarioGenerateRequest(CamelModel):
    category: Optional[Category] = None
    difficulty: Difficulty = Difficulty.BASIC
    count: int = Field(default=1, ge=1, le=20)
    profile: str = Field(default="ДДС района", min_length=1)
    time_limit_seconds: int = Field(default=30, ge=1)
    # seed фиксирует выдачу: один и тот же запрос даёт один и тот же результат.
    seed: int = Field(default=0, ge=0)


class ScenarioGenerateResponse(CamelModel):
    scenarios: List[Scenario]
    meta: ResponseMeta
