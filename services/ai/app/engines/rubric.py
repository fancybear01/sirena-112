"""Рубрика оценки: методика обучения, а не данные классификатора.

В каталоге происшествий рубрики нет и быть не может: он описывает, что
случилось, а не как за это ставить баллы. Импорт кладёт в сценарий заглушку
с одним критерием, и если считать по ней, преподаватель увидит "сто баллов,
критерий один" - формально верно, разбирать нечего.

Поэтому сервис дополняет рубрику до минимального набора критериев. Свою
рубрику преподавателя он при этом не трогает: если в присланной есть все
обязательные критерии, считается по ней.
"""

from typing import Any, Dict, List

from app.schemas.scenario import Rubric, RubricCriterion, Scenario

BASE_RUBRIC: List[Dict[str, Any]] = [
    {"code": "GREETING", "description": "Представился и назвал службу", "weight": 1.0},
    {
        "code": "SIGNS",
        "description": "Выбрал полный путь признаков происшествия",
        "weight": 3.0,
        "critical": True,
    },
    {
        "code": "QUESTIONS",
        "description": "Уточнил обязательные вопросы опросной карты",
        "weight": 2.0,
        "critical": True,
    },
    {
        "code": "ADDRESS",
        "description": "Собрал адрес происшествия",
        "weight": 3.0,
        "critical": True,
    },
    {
        "code": "VICTIMS",
        "description": "Зафиксировал пострадавших и угрозу людям",
        "weight": 2.0,
        "critical": True,
    },
    {"code": "DESCRIPTION", "description": "Описал существенные обстоятельства", "weight": 1.0},
    {
        "code": "CLASSIFICATION",
        "description": "По карточке определилось верное происшествие",
        "weight": 2.0,
    },
    {
        "code": "SERVICES",
        "description": "Состав оповещённых служб совпал с эталоном",
        "weight": 2.0,
    },
]

# Минимальный набор из постановки задачи. Рубрика без этих критериев считается
# заглушкой импорта, а не осознанным выбором преподавателя.
MINIMUM_CRITERIA = frozenset(
    {"SIGNS", "QUESTIONS", "ADDRESS", "VICTIMS", "DESCRIPTION", "SERVICES"}
)


def base_rubric() -> Rubric:
    return Rubric(criteria=[RubricCriterion(**criterion) for criterion in BASE_RUBRIC])


def covers_minimum(rubric: Rubric) -> bool:
    return MINIMUM_CRITERIA <= {criterion.code for criterion in rubric.criteria}


def ensure_rubric(scenario: Scenario) -> Scenario:
    """Возвращает сценарий с рубрикой, по которой есть что разбирать."""
    if covers_minimum(scenario.rubric):
        return scenario
    return scenario.model_copy(update={"rubric": base_rubric()})
