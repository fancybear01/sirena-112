"""Модели объяснимой оценки учебной сессии.

Правило формата: сумма earnedPoints по критериям минус сумма штрафов равна
totalScore. Любое снижение балла обязано иметь запись в errors или penalties,
иначе отчёт нельзя объяснить обучающемуся.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common import CamelModel, OpenCamelModel, ResponseMeta
from app.schemas.dialogue import DialogueTurn
from app.schemas.scenario import Scenario


class CriterionStatus(str, Enum):
    PASSED = "PASSED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class SubmittedCard(OpenCamelModel):
    """Карточка происшествия, заполненная обучающимся."""

    incident_type: Optional[str] = None
    address: Optional[str] = None
    services: List[str] = Field(default_factory=list)
    fields: Dict[str, Any] = Field(default_factory=dict)


class ActionLogItem(CamelModel):
    """Одно действие обучающегося с отметкой времени от начала сессии."""

    type: str = Field(min_length=1)
    at_ms: int = Field(ge=0)
    field: Optional[str] = None
    value: Optional[Any] = None


class CriterionResult(CamelModel):
    code: str
    description: str
    weight: float
    max_points: float
    earned_points: float
    status: CriterionStatus


class ScoringError(CamelModel):
    """Конкретная ошибка обучающегося с человеческим объяснением."""

    code: str
    severity: Severity
    message: str
    field: Optional[str] = None


class Penalty(CamelModel):
    """Штраф, применяемый поверх суммы критериев."""

    code: str
    message: str
    points: float = Field(ge=0)


class ScoreRequest(CamelModel):
    session_id: str = Field(min_length=1)
    scenario: Scenario
    submitted_card: SubmittedCard
    transcript: List[DialogueTurn] = Field(default_factory=list)
    actions: List[ActionLogItem] = Field(default_factory=list)
    elapsed_seconds: Optional[int] = Field(default=None, ge=0)


class ScoreResponse(CamelModel):
    session_id: str
    total_score: float
    max_score: float
    passed: bool
    criteria: List[CriterionResult]
    errors: List[ScoringError]
    penalties: List[Penalty]
    recommendations: List[str]
    meta: ResponseMeta
