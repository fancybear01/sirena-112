"""Оценка учебной сессии сравнением с эталоном.

Каждый критерий рубрики проверяется отдельной функцией. Проверка возвращает
долю выполнения от нуля до единицы и человеческое объяснение, чего не хватило.
Частичное выполнение считается честно: выбрал три службы из четырёх - это не
полный провал, а три четверти баллов.

Критерии про общение с заявителем проверяются по транскрипту тем же словарём
вопросов, который в диалоге управляет поведением абонента. Один и тот же
разбор реплик работает в обе стороны: вчера он решал, что абоненту отвечать,
сегодня - задал ли оператор нужный вопрос.

Разделение штрафов и критериев: критерии показывают качество работы, штрафы -
нарушение жёстких нормативов. Одна и та же ошибка не должна наказываться
дважды, поэтому норматив времени живёт только в штрафах.

Оценка детерминирована: одинаковый запрос даёт побайтово одинаковый отчёт.
"""

from typing import Callable, Dict, List, NamedTuple, Optional

from app.config import SERVICE_VERSION
from app.engines.address_match import compare as compare_address
from app.engines.question_intents import match_question, match_tone
from app.schemas.common import ResponseMeta
from app.schemas.dialogue import SpeakerRole
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
NOT_TRANSFERABLE_PENALTY_POINTS = 20.0

# Ниже этой доли адрес считается не найденным, а не частично верным.
ADDRESS_PARTIAL_FLOOR = 0.5

# Поля, без которых карточка не имеет смысла.
REQUIRED_CARD_FIELDS = (
    ("incidentType", "тип происшествия"),
    ("signs", "признаки происшествия"),
    ("address", "адрес"),
    ("requiredServices", "список оповещения"),
)

# Без этих полей карточку невозможно передать в службу.
TRANSFER_CRITICAL_FIELDS = ("address", "incidentType")


class CheckResult(NamedTuple):
    """Доля выполнения критерия и объяснение, чего не хватило.

    Доля None означает, что критерий проверить нечем. Так бывает в карточном
    режиме, где звонка нет вообще: наказывать за непредставление там, где
    оператор физически не говорил, нельзя. Такой критерий не участвует
    в распределении баллов.
    """

    share: Optional[float]
    detail: str


NOT_APPLICABLE = CheckResult(None, "")


def _text(value: Optional[str]) -> str:
    """Приводит строку к виду, пригодному для сравнения."""
    return (value or "").strip().lower().replace("ё", "е")


def _operator_lines(request: ScoreRequest) -> List[str]:
    return [turn.text for turn in request.transcript if turn.role == SpeakerRole.OPERATOR]


# --- проверки отдельных критериев ---------------------------------------------


def check_greeting(request: ScoreRequest) -> CheckResult:
    """Представился ли оператор. Проверяется по записи разговора."""
    if not request.transcript:
        return NOT_APPLICABLE

    for line in _operator_lines(request):
        if "GREETING" in match_tone(line):
            return CheckResult(1.0, "")
    return CheckResult(0.0, "в разговоре нет представления службы")


def check_victims(request: ScoreRequest) -> CheckResult:
    """Уточнил ли оператор наличие пострадавших."""
    if not request.transcript:
        return NOT_APPLICABLE

    for line in _operator_lines(request):
        if match_question(line) == "VICTIMS":
            return CheckResult(1.0, "")
    return CheckResult(0.0, "вопрос о пострадавших не задан")


def check_address(request: ScoreRequest) -> CheckResult:
    """Сравнивает адрес по значимым частям, не придираясь к сокращениям."""
    expected = request.scenario.ground_truth.address
    if not expected:
        return CheckResult(1.0, "")

    # Пустое поле и неверное значение - разные ошибки, и преподаватель должен
    # видеть разницу: во втором случае человек хотя бы пытался.
    if not request.submitted_card.address:
        return CheckResult(0.0, "адрес не заполнен")

    match = compare_address(expected, request.submitted_card.address)
    if match.share >= 1.0:
        return CheckResult(1.0, "")
    if match.share < ADDRESS_PARTIAL_FLOOR:
        return CheckResult(0.0, "адрес не совпадает с эталоном")
    return CheckResult(match.share, "не указано: {parts}".format(parts=", ".join(match.missing)))


def check_signs(request: ScoreRequest) -> CheckResult:
    """Сравнивает формализованные признаки по уровням."""
    expected = request.scenario.ground_truth.signs
    if expected is None:
        return CheckResult(1.0, "")

    actual = request.submitted_card.signs
    if actual is None:
        return CheckResult(0.0, "признаки происшествия не выбраны")

    levels = [
        ("первого уровня", expected.level1, actual.level1),
        ("второго уровня", expected.level2, actual.level2),
        ("третьего уровня", expected.level3, actual.level3),
    ]
    checked = [(name, want, got) for name, want, got in levels if want]

    wrong = [
        "признак {name} должен быть «{want}», выбран «{got}»".format(
            name=name, want=want, got=got or "не выбран"
        )
        for name, want, got in checked
        if _text(want) != _text(got)
    ]
    share = round((len(checked) - len(wrong)) / len(checked), 3)
    return CheckResult(share, "; ".join(wrong))


def check_incident_type(request: ScoreRequest) -> CheckResult:
    """Итоговый тип происшествия должен совпасть с эталоном точно."""
    expected = request.scenario.ground_truth.incident_type
    actual = request.submitted_card.incident_type
    if _text(expected) == _text(actual):
        return CheckResult(1.0, "")
    if not actual:
        return CheckResult(0.0, "тип происшествия не выбран")
    return CheckResult(
        0.0,
        "выбран тип «{got}», в эталоне «{want}»".format(got=actual, want=expected),
    )


def check_services(request: ScoreRequest) -> CheckResult:
    """Сравнивает список оповещения: чего не хватает и что лишнее.

    Сравнение идёт по приведённым названиям, а в объяснении показываются
    исходные: преподаватель должен видеть службу так, как она называется.
    """
    expected = {_text(name): name for name in request.scenario.ground_truth.required_services}
    if not expected:
        return CheckResult(1.0, "")

    actual = {_text(name): name for name in request.submitted_card.required_services}
    missing = sorted(expected[key] for key in set(expected) - set(actual))
    extra = sorted(actual[key] for key in set(actual) - set(expected))
    hit = len(set(expected) & set(actual))

    # Лишняя служба - тоже ошибка: её зря поднимут по тревоге.
    share = round(max(0.0, (hit - len(extra)) / len(expected)), 3)

    notes = []
    if missing:
        notes.append("не выбрано: {names}".format(names=", ".join(missing)))
    if extra:
        notes.append("лишнее: {names}".format(names=", ".join(extra)))
    return CheckResult(share, "; ".join(notes))


CHECKERS: Dict[str, Callable[[ScoreRequest], CheckResult]] = {
    "GREETING": check_greeting,
    "VICTIMS": check_victims,
    "ADDRESS": check_address,
    "SIGNS": check_signs,
    "INCIDENT_TYPE": check_incident_type,
    "SERVICES": check_services,
}

RECOMMENDATION_BY_CODE: Dict[str, str] = {
    "GREETING": "Начинайте разговор с представления: служба, фамилия, номер рабочего места.",
    "VICTIMS": "Всегда спрашивайте о пострадавших, даже если заявитель о них не упомянул.",
    "ADDRESS": "Уточняйте адрес до корпуса и подъезда и повторяйте его заявителю вслух.",
    "SIGNS": "Выбирайте признаки по опросной карте: тип происшествия следует из них.",
    "INCIDENT_TYPE": "Сверяйте итоговый тип с выбранными признаками перед сохранением.",
    "SERVICES": "Проверяйте список оповещения по типу происшествия, лишние службы тоже ошибка.",
}

UNCHECKED_RECOMMENDATION = (
    "Критерий «{code}» автоматически не проверяется, оцените его вручную."
)

CARD_FIELD_BY_CODE: Dict[str, str] = {
    "ADDRESS": "address",
    "INCIDENT_TYPE": "incidentType",
    "SIGNS": "signs",
    "SERVICES": "requiredServices",
}


# --- сборка отчёта ------------------------------------------------------------


def _distribute_points(
    criteria: List[RubricCriterion], scored: List[bool]
) -> List[float]:
    """Делит сто баллов между критериями, которые удалось проверить.

    Непроверенный критерий получает ноль: он не должен ни завышать оценку,
    ни занижать её. Остаток от округления уходит последнему проверенному,
    поэтому сумма всегда равна ровно ста.
    """
    total_weight = sum(
        criterion.weight for criterion, ok in zip(criteria, scored) if ok
    )
    if total_weight <= 0:
        return [0.0] * len(criteria)

    points = [
        round(criterion.weight / total_weight * MAX_SCORE, 2) if ok else 0.0
        for criterion, ok in zip(criteria, scored)
    ]
    last = max(index for index, ok in enumerate(scored) if ok)
    points[last] = round(points[last] + (MAX_SCORE - sum(points)), 2)
    return points


def _status(share: float) -> CriterionStatus:
    if share >= 1.0:
        return CriterionStatus.PASSED
    return CriterionStatus.PARTIAL if share > 0 else CriterionStatus.FAILED


def _severity(criterion: RubricCriterion, status: CriterionStatus) -> Severity:
    if criterion.critical:
        return Severity.CRITICAL if status == CriterionStatus.FAILED else Severity.MAJOR
    return Severity.MAJOR if status == CriterionStatus.FAILED else Severity.MINOR


def _completeness_errors(request: ScoreRequest, covered: set) -> List[ScoringError]:
    """Проверяет, что обязательные поля карточки вообще заполнены.

    Поля, для которых в рубрике есть свой критерий, здесь пропускаются: о них
    уже сказано в разборе критерия, и повторять это второй раз значит засорять
    отчёт, который преподаватель должен прочитать целиком.
    """
    card = request.submitted_card
    filled = {
        "incidentType": bool(card.incident_type),
        "signs": card.signs is not None,
        "address": bool(card.address),
        "requiredServices": bool(card.required_services),
    }
    return [
        ScoringError(
            code="CARD_FIELD_EMPTY",
            severity=Severity.MAJOR,
            message="Не заполнено обязательное поле карточки: {title}.".format(title=title),
            field=field,
        )
        for field, title in REQUIRED_CARD_FIELDS
        if not filled[field] and field not in covered
    ]


def _penalties(request: ScoreRequest) -> List[Penalty]:
    """Нарушения жёстких нормативов, не покрытые критериями рубрики."""
    result: List[Penalty] = []
    card = request.submitted_card

    empty_critical = [
        field for field in TRANSFER_CRITICAL_FIELDS if not getattr(card, _attr(field))
    ]
    if empty_critical:
        result.append(
            Penalty(
                code="CARD_NOT_TRANSFERABLE",
                message=(
                    "Карточку невозможно передать в службу: не заполнено обязательное "
                    "поле. Реагирование не начнётся."
                ),
                points=NOT_TRANSFERABLE_PENALTY_POINTS,
            )
        )

    limit = request.scenario.time_limit_seconds
    if request.elapsed_seconds is not None and request.elapsed_seconds > limit:
        result.append(
            Penalty(
                code="TIME_LIMIT_EXCEEDED",
                message="Норматив {limit} с превышен: карточка заполнена за {actual} с.".format(
                    limit=limit, actual=request.elapsed_seconds
                ),
                points=TIME_PENALTY_POINTS,
            )
        )
    return result


def _attr(field: str) -> str:
    """Имя поля модели по имени поля в JSON."""
    return {"address": "address", "incidentType": "incident_type"}[field]


def score(request: ScoreRequest) -> ScoreResponse:
    """Считает объяснимый отчёт по рубрике сценария."""
    criteria = request.scenario.rubric.criteria

    # Сначала проверяем всё, и только потом делим баллы: до проверки неизвестно,
    # какие критерии вообще применимы к этому занятию.
    checks = [
        CHECKERS.get(criterion.code, lambda _: NOT_APPLICABLE)(request)
        for criterion in criteria
    ]
    scored = [check.share is not None for check in checks]
    max_points = _distribute_points(criteria, scored)

    results: List[CriterionResult] = []
    errors: List[ScoringError] = []
    recommendations: List[str] = []

    for criterion, check, points in zip(criteria, checks, max_points):
        if check.share is None:
            results.append(
                CriterionResult(
                    code=criterion.code,
                    description=criterion.description,
                    weight=criterion.weight,
                    max_points=0.0,
                    earned_points=0.0,
                    status=CriterionStatus.PASSED,
                )
            )
            recommendations.append(UNCHECKED_RECOMMENDATION.format(code=criterion.code))
            continue

        status = _status(check.share)
        results.append(
            CriterionResult(
                code=criterion.code,
                description=criterion.description,
                weight=criterion.weight,
                max_points=points,
                earned_points=round(points * check.share, 2),
                status=status,
            )
        )

        if status != CriterionStatus.PASSED:
            errors.append(
                ScoringError(
                    code="CRITERION_{code}".format(code=criterion.code),
                    severity=_severity(criterion, status),
                    message="{description}: {detail}.".format(
                        description=criterion.description, detail=check.detail
                    )
                    if check.detail
                    else "{description}: критерий не выполнен.".format(
                        description=criterion.description
                    ),
                    field=CARD_FIELD_BY_CODE.get(criterion.code),
                )
            )
            recommendations.append(
                RECOMMENDATION_BY_CODE.get(
                    criterion.code, "Разберите этот критерий с преподавателем."
                )
            )

    covered = {
        CARD_FIELD_BY_CODE[criterion.code]
        for criterion in criteria
        if criterion.code in CARD_FIELD_BY_CODE
    }
    errors.extend(_completeness_errors(request, covered))
    penalties = _penalties(request)

    if any(penalty.code == "CARD_NOT_TRANSFERABLE" for penalty in penalties):
        errors.append(
            ScoringError(
                code="CARD_NOT_TRANSFERABLE",
                severity=Severity.CRITICAL,
                message="Карточка не может быть передана в службу: нет адреса или типа происшествия.",
            )
        )

    earned = sum(result.earned_points for result in results)
    lost = sum(penalty.points for penalty in penalties)
    total = round(max(0.0, earned - lost), 2)
    has_critical = any(error.severity == Severity.CRITICAL for error in errors)

    return ScoreResponse(
        session_id=request.session_id,
        total_score=total,
        max_score=MAX_SCORE,
        passed=total >= PASS_THRESHOLD and not has_critical,
        criteria=results,
        errors=errors,
        penalties=penalties,
        recommendations=recommendations,
        meta=ResponseMeta(engine="rules", version=SERVICE_VERSION, deterministic=True),
    )
