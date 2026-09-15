"""Модель учебного сценария.

Повторяет contracts/scenario.schema.json. Любое изменение здесь должно
сопровождаться изменением схемы в contracts, иначе тест test_contract упадёт.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.common import CamelModel, OpenCamelModel


class Category(str, Enum):
    """Грубая группировка для интерфейса преподавателя."""

    FIRE = "FIRE"
    ACCIDENT = "ACCIDENT"
    MEDICAL = "MEDICAL"
    UTILITY = "UTILITY"
    GAS = "GAS"
    OTHER = "OTHER"


class Difficulty(str, Enum):
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class GroundTruth(OpenCamelModel):
    """Эталон: то, с чем сравнивается карточка обучающегося.

    Схема разрешает дополнительные поля. Сюда позже добавятся код ЕКП,
    признаки происшествия трёх уровней и итоговый тип из классификатора.
    """

    incident_type: str
    address: Optional[str] = None
    required_services: List[str] = Field(default_factory=list)
    facts: Dict[str, Any] = Field(default_factory=dict)


class Caller(CamelModel):
    """Профиль звонящего и его состояние на начало разговора."""

    persona: Optional[str] = None
    panic: Optional[float] = Field(default=None, ge=0, le=1)
    trust: Optional[float] = Field(default=None, ge=0, le=1)
    patience: Optional[float] = Field(default=None, ge=0, le=1)
    voice: Optional[str] = None
    background: Optional[str] = None


class RubricCriterion(CamelModel):
    """Один критерий оценки с весом."""

    code: str
    description: str
    weight: float = Field(ge=0)
    critical: bool = False


class Rubric(CamelModel):
    criteria: List[RubricCriterion] = Field(min_length=1)


class Scenario(CamelModel):
    """Учебный сценарий целиком."""

    id: UUID
    version: int = Field(ge=1)
    title: str = Field(min_length=1)
    category: Category
    difficulty: Difficulty
    profile: str = Field(min_length=1)
    time_limit_seconds: int = Field(default=30, ge=1)
    ground_truth: GroundTruth
    caller: Optional[Caller] = None
    rubric: Rubric
