"""Модели объяснимой оценки учебной сессии.

Оценивается то, что оператор действительно делает: выбирает признаки,
отвечает на обязательные вопросы, собирает адрес, фиксирует пострадавших
и описывает обстоятельства. Тип происшествия и список служб он не вводит -
их вычисляет Core, поэтому в оценку приходит готовый расчёт.

Правило формата: сумма earnedPoints по критериям минус сумма штрафов равна
totalScore. Любое снижение балла обязано иметь запись в errors или penalties,
иначе отчёт нельзя объяснить обучающемуся.

Ошибки разделены по источнику: ошибка оператора и неполнота эталона - разные
вещи, и смешивать их в одном списке без пометки нельзя.
"""

from enum import Enum
from typing import List, Optional

from pydantic import Field

from app.schemas.common import CamelModel, ResponseMeta
from app.schemas.dialogue import DialogueTurn
from app.schemas.scenario import (
    OperatorCardInput,
    ResponseScenarioStatus,
    RoutedService,
    Scenario,
    ServiceRef,
)


class CriterionStatus(str, Enum):
    PASSED = "PASSED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class ErrorKind(str, Enum):
    """Чья это проблема.

    OPERATOR - обучающийся сделал не то. GROUND_TRUTH - вопрос к эталону
    или каталогу: например, разошлись версии классификатора. Второе нельзя
    ставить в вину обучающемуся.
    """

    OPERATOR = "OPERATOR"
    GROUND_TRUTH = "GROUND_TRUTH"


class CalculationStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    RESOLVED = "RESOLVED"
    NO_MATCH = "NO_MATCH"


class CardCalculation(CamelModel):
    """Результат, вычисленный Core по карточке обучающегося.

    AI его не пересчитывает и не подменяет: только сравнивает с эталоном.
    """

    status: CalculationStatus
    classifier_version: str = Field(min_length=1)
    classifier_code: Optional[str] = None
    incident_type: Optional[str] = None
    ekp35_incident_type: Optional[str] = None
    response_scenario_code: Optional[str] = None
    response_scenario_status: Optional[ResponseScenarioStatus] = None
    main_services: List[ServiceRef] = Field(default_factory=list)
    services: List[RoutedService] = Field(default_factory=list)
    missing_input_ids: List[str] = Field(default_factory=list)
    explanations: List[str] = Field(default_factory=list)


class ActionLogItem(CamelModel):
    """Одно действие обучающегося с отметкой времени от начала сессии."""

    type: str = Field(min_length=1)
    at_ms: int = Field(ge=0)
    field: Optional[str] = None
    value: Optional[object] = None


class CriterionResult(CamelModel):
    code: str
    description: str
    weight: float
    max_points: float
    earned_points: float
    status: CriterionStatus


class ScoringError(CamelModel):
    """Конкретная ошибка с человеческим объяснением."""

    code: str
    kind: ErrorKind = ErrorKind.OPERATOR
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
    submitted_card: OperatorCardInput
    # Расчёт Core по карточке обучающегося. Без него службы и код
    # происшествия проверить нечем: сам AI их не вычисляет.
    calculation: Optional[CardCalculation] = None
    transcript: List[DialogueTurn] = Field(default_factory=list)
    actions: List[ActionLogItem] = Field(default_factory=list)
    elapsed_seconds: Optional[int] = Field(default=None, ge=0)


class ScoreResponse(CamelModel):
    session_id: str
    scenario_id: str
    classifier_version: str
    total_score: float
    max_score: float
    passed: bool
    criteria: List[CriterionResult]
    errors: List[ScoringError]
    penalties: List[Penalty]
    recommendations: List[str]
    meta: ResponseMeta
