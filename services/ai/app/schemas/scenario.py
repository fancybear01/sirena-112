"""Модель учебного сценария, версия контракта 0.3.

Повторяет contracts/scenario.schema.json. Ключевое отличие от прежней версии:
оператор не вводит тип происшествия и список служб - он выбирает признаки
и отвечает на вопросы, а классификацию и маршрутизацию вычисляет Core
по каталогу. Поэтому в эталоне лежат и ожидаемый ввод оператора, и уже
посчитанный результат маршрутизации.

AI не вычисляет службы самостоятельно: он сравнивает то, что Core посчитал
по карточке обучающегося, с тем, что записано в эталоне сценария.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.common import CamelModel, OpenCamelModel


class Category(str, Enum):
    """Высокоуровневая учебная группа. Она не заменяет код классификатора."""

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


class ResponseScenarioStatus(str, Enum):
    """Почему сценарий реагирования отсутствует, если его нет.

    В классификаторе часть строк не имеет кода сценария, и придумывать его
    нельзя. Статус отличает "кода нет в источнике" от "источник явно указал,
    что сценария не требуется".
    """

    CODE = "CODE"
    MISSING = "MISSING"
    EXPLICIT_NONE = "EXPLICIT_NONE"
    SOURCE_LABEL = "SOURCE_LABEL"


# --- службы и объяснение маршрутизации ----------------------------------------


class ServiceRef(CamelModel):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class RoutingReason(CamelModel):
    """Почему служба попала в список оповещения."""

    rule_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    matched_input_ids: List[str] = Field(default_factory=list)


class RoutedService(ServiceRef):
    reasons: List[RoutingReason] = Field(min_length=1)


# --- исходные данные, которые вводит оператор ---------------------------------


class PhoneNumber(CamelModel):
    value: str = Field(min_length=1, max_length=64)
    kind: str
    foreign: bool = False


class CallerInput(CamelModel):
    phone_numbers: List[PhoneNumber] = Field(default_factory=list)
    full_name: Optional[str] = None
    status: Optional[str] = None
    communication_channel: Optional[str] = None
    language: Optional[str] = None


class QuestionAnswer(CamelModel):
    question_id: str = Field(min_length=1)
    option_ids: List[str] = Field(default_factory=list)
    free_text: Optional[str] = None


class IncidentInput(CamelModel):
    """Выбор оператора в опросной карте: признаки и ответы на вопросы."""

    selected_sign_ids: List[str] = Field(default_factory=list)
    answers: List[QuestionAnswer] = Field(default_factory=list)


class AddressInput(CamelModel):
    display_address: str = Field(min_length=1, max_length=500)
    region: Optional[str] = None
    locality: Optional[str] = None
    street: Optional[str] = None
    house: Optional[str] = None
    building: Optional[str] = None
    apartment: Optional[str] = None
    description: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class VictimsInput(CamelModel):
    present: bool
    count: Optional[int] = Field(default=None, ge=0)
    threat_to_people: Optional[bool] = None


class OperatorCardInput(CamelModel):
    """Только исходные сведения оператора.

    Код классификатора, тип происшествия и службы сюда попадать не должны:
    это вычисляемые поля, и их считает Core.
    """

    caller: Optional[CallerInput] = None
    incident: Optional[IncidentInput] = None
    address: Optional[AddressInput] = None
    description: Optional[str] = Field(default=None, max_length=1999)
    victims: Optional[VictimsInput] = None
    # Необязательные подробности сверх контракта. Поле именно необязательное,
    # а не пустой словарь по умолчанию: иначе сериализация добавляла бы facts
    # туда, где его нет, и сценарий переставал бы совпадать с общим файлом.
    facts: Optional[Dict[str, Any]] = None

    @property
    def extra_facts(self) -> Dict[str, Any]:
        """Подробности в виде словаря, даже если поле не заполнено."""
        return self.facts or {}


# --- эталон сценария ----------------------------------------------------------


class GroundTruth(OpenCamelModel):
    """Эталон: ожидаемый ввод оператора и посчитанный по нему результат."""

    classifier_version: str = Field(min_length=1)
    classifier_code: str = Field(pattern=r"^[0-9]{6,9}$")
    incident_type: str = Field(min_length=1)
    ekp35_incident_type: Optional[str] = None
    response_scenario_code: Optional[str] = None
    response_scenario_status: ResponseScenarioStatus
    main_services: List[ServiceRef] = Field(default_factory=list)
    required_services: List[RoutedService] = Field(default_factory=list)
    expected_input: OperatorCardInput


class Caller(CamelModel):
    """Профиль звонящего: характер и состояние, а не факты происшествия.

    Факты берутся из эталона, здесь только то, как человек себя ведёт.
    """

    persona: Optional[str] = None
    panic: Optional[float] = Field(default=None, ge=0, le=1)
    trust: Optional[float] = Field(default=None, ge=0, le=1)
    patience: Optional[float] = Field(default=None, ge=0, le=1)
    voice: Optional[str] = None
    background: Optional[str] = None


class RubricCriterion(CamelModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    weight: float = Field(ge=0)
    critical: bool = False


class Rubric(CamelModel):
    criteria: List[RubricCriterion] = Field(min_length=1)


class Scenario(CamelModel):
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
