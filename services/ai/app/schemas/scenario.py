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
    """Группа происшествий по классификатору ГБУ «Система 112».

    Двадцать три значения соответствуют группам классификатора один к одному.
    Русское название каждой группы указано в комментарии, чтобы код можно было
    сверить с исходным файлом классификатора без дополнительных справочников.
    """

    FIRE = "FIRE"  # 1. Пожары и задымления
    ACCIDENT = "ACCIDENT"  # 2. ДТП
    EXPLOSION = "EXPLOSION"  # 3. Взрывы
    EXPLOSION_THREAT = "EXPLOSION_THREAT"  # 4. Угрозы взрывов и терактов
    COLLAPSE = "COLLAPSE"  # 5. Обрушения
    COLLAPSE_THREAT = "COLLAPSE_THREAT"  # 6. Угрозы обрушений
    NATURAL_HAZARD = "NATURAL_HAZARD"  # 7. Опасные природные явления
    ENVIRONMENT = "ENVIRONMENT"  # 8. Экологические происшествия
    HYDRAULIC_FACILITY = "HYDRAULIC_FACILITY"  # 9. Аварии на гидротехнических сооружениях
    INDUSTRIAL_ACCIDENT = "INDUSTRIAL_ACCIDENT"  # 10. Аварии на опасных объектах
    HAZMAT_THREAT = "HAZMAT_THREAT"  # 11. Угрозы выброса опасных веществ
    TRANSPORT_FACILITY = "TRANSPORT_FACILITY"  # 12. Происшествия на транспортных объектах
    GAS = "GAS"  # 13. Запах газа
    UTILITY = "UTILITY"  # 14. Аварии в городском хозяйстве
    PUBLIC_ORDER = "PUBLIC_ORDER"  # 15. Нарушение правопорядка
    ROAD_CONDITION = "ROAD_CONDITION"  # 16. Проблемы на дороге
    PERSON_AT_RISK = "PERSON_AT_RISK"  # 17. Человек в опасности
    CHILD_AT_RISK = "CHILD_AT_RISK"  # 18. Ребёнок в опасности
    DEATH = "DEATH"  # 19. Смертельный исход человека
    SOCIAL_AID = "SOCIAL_AID"  # 20. Социальная помощь
    ANIMAL = "ANIMAL"  # 21. Происшествия с участием животных
    MEDICAL = "MEDICAL"  # 22. Оказание скорой и неотложной помощи
    OTHER = "OTHER"  # 23. Прочие происшествия


class Difficulty(str, Enum):
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class IncidentSigns(CamelModel):
    """Формализованные признаки происшествия из опросной карты АРМ-112.

    Оператор выбирает именно признаки, а итоговый тип происшествия и список
    оповещения вычисляются из их комбинации по классификатору. Поэтому
    оценивать нужно выбор признаков, а не введённое руками название типа.
    """

    level1: str = Field(min_length=1)
    level2: Optional[str] = None
    level3: Optional[str] = None
    additional: List[str] = Field(default_factory=list)


class GroundTruth(OpenCamelModel):
    """Эталон: то, с чем сравнивается карточка обучающегося.

    incident_type и required_services не задаются произвольно: они должны
    соответствовать комбинации признаков в классификаторе. Пока классификатор
    не разобран, значения проставлены вручную по его строкам.
    """

    incident_type: str
    ekp_code: Optional[str] = Field(default=None, pattern=r"^[0-9]{6,9}$")
    signs: Optional[IncidentSigns] = None
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
