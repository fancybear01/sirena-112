"""Оценка учебной сессии: заглушка с объяснимым отчётом.

Форма отчёта здесь окончательная, содержательные правила добавляются
задачей #16. Инварианты, которые обязаны сохраниться и дальше:

1. Сумма maxPoints по критериям равна maxScore.
2. totalScore = сумма earnedPoints минус сумма штрафов, не ниже нуля.
3. Каждый критерий не в статусе PASSED имеет запись в errors.

Оценка детерминирована: одинаковый запрос даёт побайтово одинаковый ответ.
"""

from typing import Dict, List, Tuple

from app.config import SERVICE_VERSION
from app.schemas.common import ResponseMeta
from app.schemas.scenario import RubricCriterion
from app.schemas.scoring import (
    CriterionResult,
    CriterionStatus,
    Penalty,
    ScoreRequest,
    ScoreResponse,
    ScoringError,
    Severity,
)

MAX_SCORE = 100.0
PASS_THRESHOLD = 60.0
TIME_PENALTY_POINTS = 10.0

# Заглушка выставляет статусы по позиции критерия в рубрике.
# Так отчёт содержит все три статуса сразу, и frontend может отрисовать
# каждый из них, не дожидаясь настоящей модели оценки.
STATUS_PATTERN: List[Tuple[CriterionStatus, float]] = [
    (CriterionStatus.PASSED, 1.0),
    (CriterionStatus.PARTIAL, 0.5),
    (CriterionStatus.FAILED, 0.0),
]

RECOMMENDATION_BY_CODE: Dict[str, str] = {
    "GREETING": "Начинайте разговор с представления: служба, фамилия, номер рабочего места.",
    "ADDRESS": "Уточняйте адрес до дома, корпуса и подъезда и повторяйте его заявителю вслух.",
    "INCIDENT_TYPE": "Определяйте тип происшествия по признакам, а не по первой фразе заявителя.",
    "VICTIMS": "Всегда задавайте вопрос о пострадавших, даже если заявитель о них не упомянул.",
    "SERVICES": "Сверяйте список оповещения с типом происшествия перед сохранением карточки.",
    "TIMING": "Следите за таймером: норматив подтверждения приёма — 30 секунд.",
}

DEFAULT_RECOMMENDATION = "Разберите этот критерий с преподавателем и повторите сценарий."

# Поле карточки, которое frontend может подсветить при ошибке.
# Заполняется только там, где критерий действительно относится к полю:
# у критериев вроде соблюдения норматива поля в карточке нет.
CARD_FIELD_BY_CODE: Dict[str, str] = {
    "ADDRESS": "address",
    "INCIDENT_TYPE": "incidentType",
    "SERVICES": "services",
}


def _distribute_points(criteria: List[RubricCriterion]) -> List[float]:
    """Делит MAX_SCORE между критериями пропорционально весам.

    Остаток от округления добавляется к последнему критерию, поэтому сумма
    всегда равна ровно MAX_SCORE.
    """
    total_weight = sum(criterion.weight for criterion in criteria)
    if total_weight <= 0:
        # Рубрика без весов: делим поровну.
        equal = round(MAX_SCORE / len(criteria), 2)
        points = [equal] * len(criteria)
    else:
        points = [
            round(criterion.weight / total_weight * MAX_SCORE, 2) for criterion in criteria
        ]

    points[-1] = round(points[-1] + (MAX_SCORE - sum(points)), 2)
    return points


def _severity(criterion: RubricCriterion, status: CriterionStatus) -> Severity:
    if criterion.critical:
        return Severity.CRITICAL
    return Severity.MAJOR if status == CriterionStatus.FAILED else Severity.MINOR


def _message(criterion: RubricCriterion, status: CriterionStatus) -> str:
    if status == CriterionStatus.FAILED:
        return "Критерий не выполнен: {description}.".format(
            description=criterion.description.lower()
        )
    return "Критерий выполнен частично: {description}.".format(
        description=criterion.description.lower()
    )


def score(request: ScoreRequest) -> ScoreResponse:
    """Считает отчёт по рубрике сценария."""
    criteria = request.scenario.rubric.criteria
    max_points = _distribute_points(criteria)

    results: List[CriterionResult] = []
    errors: List[ScoringError] = []
    # Коды критериев, по которым потеряны баллы: по ним же строятся рекомендации.
    lost_codes: List[str] = []

    for index, criterion in enumerate(criteria):
        status, share = STATUS_PATTERN[index % len(STATUS_PATTERN)]
        earned = round(max_points[index] * share, 2)

        results.append(
            CriterionResult(
                code=criterion.code,
                description=criterion.description,
                weight=criterion.weight,
                max_points=max_points[index],
                earned_points=earned,
                status=status,
            )
        )

        if status != CriterionStatus.PASSED:
            lost_codes.append(criterion.code)
            errors.append(
                ScoringError(
                    code="CRITERION_{code}".format(code=criterion.code),
                    severity=_severity(criterion, status),
                    message=_message(criterion, status),
                    field=CARD_FIELD_BY_CODE.get(criterion.code),
                )
            )

    penalties: List[Penalty] = []
    limit = request.scenario.time_limit_seconds
    if request.elapsed_seconds is not None and request.elapsed_seconds > limit:
        penalties.append(
            Penalty(
                code="TIME_LIMIT_EXCEEDED",
                message=(
                    "Норматив {limit} с превышен: карточка заполнена за {actual} с."
                ).format(limit=limit, actual=request.elapsed_seconds),
                points=TIME_PENALTY_POINTS,
            )
        )

    earned_total = sum(result.earned_points for result in results)
    penalty_total = sum(penalty.points for penalty in penalties)
    total = round(max(0.0, earned_total - penalty_total), 2)

    has_critical = any(error.severity == Severity.CRITICAL for error in errors)
    recommendations = [
        RECOMMENDATION_BY_CODE.get(code, DEFAULT_RECOMMENDATION) for code in lost_codes
    ]

    return ScoreResponse(
        session_id=request.session_id,
        total_score=total,
        max_score=MAX_SCORE,
        passed=total >= PASS_THRESHOLD and not has_critical,
        criteria=results,
        errors=errors,
        penalties=penalties,
        recommendations=recommendations,
        meta=ResponseMeta(engine="mock", version=SERVICE_VERSION, deterministic=True),
    )
