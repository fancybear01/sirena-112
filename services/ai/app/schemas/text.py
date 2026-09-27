"""Разбор текста карточки и рекомендации преподавателю.

Отдельная схема, а не добавка к оценке: оценку читает Core и ломать её
формат нельзя. Здесь другой потребитель - преподаватель, который смотрит,
что оператор написал руками.

Правило этой схемы: у каждого вывода видно, насколько ему можно верить.
Вывод без измеренной точности обязан приходить с признаком того, что его
надо проверить глазами.
"""

from typing import List, Optional

from pydantic import Field

from app.schemas.common import CamelModel, ResponseMeta
from app.schemas.scenario import Scenario


class TextReviewRequest(CamelModel):
    """Что проверяем. Историю и карточку присылает Core: своей базы у AI нет."""

    session_id: str = Field(min_length=1)
    scenario: Scenario
    # Текст, который оператор написал или поправил руками.
    description: Optional[str] = None
    address_text: Optional[str] = None
    victims_text: Optional[str] = None
    elapsed_seconds: Optional[int] = Field(default=None, ge=0)


class TextFinding(CamelModel):
    """Вывод одной проверки.

    confidence - это не самоощущение модели, а измеренная на разметке доля
    совпадений с экспертом. Ноль означает, что проверку не мерили.
    """

    code: str
    status: str
    explanation: str
    details: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_teacher_check: bool


class TextReviewResponse(CamelModel):
    session_id: str
    scenario_id: str
    # Чем разбирали: morphology - со словарём, words - без него.
    method: str
    # Прямо перечисленные ограничения разбора. Пустым не бывает: даже когда
    # всё работает, синонимы мы не понимаем, и молчать об этом нельзя.
    limitations: List[str]
    findings: List[TextFinding]
    meta: ResponseMeta


class GroupErrorSample(CamelModel):
    """Одна ошибка одного занятия. Приходит от Core из уже сохранённых отчётов."""

    session_id: str = Field(min_length=1)
    criterion_code: str = Field(min_length=1)
    severity: Optional[str] = None


class GroupRecommendationsRequest(CamelModel):
    """Свод ошибок группы. AI ничего не выдумывает: считает по присланному."""

    group_id: Optional[str] = None
    sessions_total: int = Field(ge=0)
    errors: List[GroupErrorSample] = Field(default_factory=list)


class GroupRecommendation(CamelModel):
    """Рекомендация, которую преподаватель вправе изменить или убрать.

    Поэтому у неё есть код и числа, на которых она построена: иначе править
    её было бы вслепую.
    """

    criterion_code: str
    sessions_affected: int
    share: float = Field(ge=0.0, le=1.0)
    text: str
    editable: bool = True


class GroupRecommendationsResponse(CamelModel):
    group_id: Optional[str] = None
    sessions_total: int
    recommendations: List[GroupRecommendation]
    limitations: List[str]
    meta: ResponseMeta
