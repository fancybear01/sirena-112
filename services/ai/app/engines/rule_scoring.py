"""Оценка учебной сессии по эталону классификатора.

Что изменилось по сравнению с прежней версией: оценивается не введённая
строка с типом происшествия, а то, что оператор действительно делает -
выбирает признаки в опросной карте, отвечает на обязательные вопросы,
собирает адрес, фиксирует пострадавших и описывает обстоятельства.

Тип происшествия и список служб оператор не вводит: их вычисляет Core
по каталогу. Поэтому AI ничего не маршрутизирует сам, а сравнивает расчёт
Core по карточке обучающегося с расчётом, записанным в эталоне сценария.

Ошибки разделены по источнику. Ошибка оператора снижает оценку и может
закрыть зачёт. Неполнота эталона или расхождение версий каталога - это
вопрос к данным, а не к обучающемуся, и в вину ему не ставится.

Оценка детерминирована: одинаковый запрос даёт побайтово одинаковый отчёт.
"""

import re
from typing import Callable, Dict, List, NamedTuple, Optional, Set

from app.catalog import load_catalog
from app.config import SERVICE_VERSION
from app.engines.address_match import compare as compare_address
from app.engines.question_intents import match_tone
from app.engines.rubric import ensure_rubric
from app.schemas.common import ResponseMeta
from app.schemas.dialogue import SpeakerRole
from app.schemas.scenario import RubricCriterion, ResponseScenarioStatus
from app.schemas.scoring import (
    CriterionResult,
    CriterionStatus,
    ErrorKind,
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

# Вычисляемые поля не имеют права приходить от клиента: их считает Core.
FORBIDDEN_INPUT_KEYS = (
    "classifierCode",
    "incidentType",
    "ekp35IncidentType",
    "requiredServices",
    "mainServices",
    "responseScenarioCode",
)

_WORDS = re.compile(r"[^а-яa-z0-9]+")
# Короткие слова и служебные части речи не несут обстоятельств.
STOP_WORDS = {"это", "или", "для", "над", "под", "при", "без", "что", "как", "там"}


class CheckResult(NamedTuple):
    """Доля выполнения критерия и объяснение, чего не хватило.

    Доля None означает, что критерий проверить нечем: например, в карточном
    режиме нет разговора, а без расчёта Core нечем сверять службы. Такой
    критерий не участвует в распределении баллов.
    """

    share: Optional[float]
    detail: str


NOT_APPLICABLE = CheckResult(None, "")


def _text(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace("ё", "е")


def _significant_words(text: str) -> Set[str]:
    """Значимые слова описания: без коротких и служебных."""
    return {
        word
        for word in _WORDS.sub(" ", _text(text)).split()
        if len(word) > 3 and word not in STOP_WORDS
    }


def _labels(sign_ids: List[str]) -> str:
    catalog = load_catalog()
    return ", ".join(catalog.sign_label(s) if catalog else s for s in sign_ids)


def _question_labels(question_ids: List[str]) -> str:
    catalog = load_catalog()
    return ", ".join(catalog.question_label(q) if catalog else q for q in question_ids)


# --- проверки отдельных критериев ---------------------------------------------


def check_greeting(request: ScoreRequest) -> CheckResult:
    """Представился ли оператор. Проверяется по записи разговора."""
    if not request.transcript:
        return NOT_APPLICABLE

    for turn in request.transcript:
        if turn.role == SpeakerRole.OPERATOR and "GREETING" in match_tone(turn.text):
            return CheckResult(1.0, "")
    return CheckResult(0.0, "в разговоре нет представления службы")


def check_signs(request: ScoreRequest) -> CheckResult:
    """Сравнивает выбранный путь признаков с эталонным.

    Признаки - главное действие оператора: из их комбинации каталог выводит
    и тип происшествия, и список служб.
    """
    expected_incident = request.scenario.ground_truth.expected_input.incident
    expected = list(expected_incident.selected_sign_ids) if expected_incident else []
    if not expected:
        return NOT_APPLICABLE

    incident = request.submitted_card.incident
    actual = set(incident.selected_sign_ids) if incident else set()
    missing = [s for s in expected if s not in actual]
    extra = sorted(actual - set(expected))

    share = round(max(0.0, (len(expected) - len(missing) - len(extra)) / len(expected)), 3)

    notes = []
    if missing:
        notes.append("не выбрано: {names}".format(names=_labels(missing)))
    if extra:
        notes.append("лишнее: {names}".format(names=_labels(extra)))
    return CheckResult(share, "; ".join(notes))


def check_questions(request: ScoreRequest) -> CheckResult:
    """Проверяет ответы на обязательные вопросы опросной карты.

    Неотвеченный вопрос и ответ, отличный от эталонного, - разные ошибки:
    первый означает, что оператор не уточнил, второй - что уточнил и понял
    иначе. От ответа зависит список служб, поэтому оба важны.
    """
    expected_incident = request.scenario.ground_truth.expected_input.incident
    expected = list(expected_incident.answers) if expected_incident else []
    if not expected:
        return NOT_APPLICABLE

    incident = request.submitted_card.incident
    actual = {answer.question_id: answer for answer in (incident.answers if incident else [])}

    unanswered, different = [], []
    for answer in expected:
        given = actual.get(answer.question_id)
        if given is None:
            unanswered.append(answer.question_id)
        elif sorted(given.option_ids) != sorted(answer.option_ids):
            different.append(answer.question_id)

    share = round((len(expected) - len(unanswered) - len(different)) / len(expected), 3)

    notes = []
    if unanswered:
        notes.append("не уточнено: {names}".format(names=_question_labels(unanswered)))
    if different:
        notes.append("ответ отличается от эталона: {names}".format(names=_question_labels(different)))
    return CheckResult(share, "; ".join(notes))


def check_address(request: ScoreRequest) -> CheckResult:
    """Сравнивает адрес по значимым частям, не придираясь к сокращениям."""
    expected_address = request.scenario.ground_truth.expected_input.address
    if expected_address is None:
        return NOT_APPLICABLE

    actual = request.submitted_card.address
    if actual is None or not actual.display_address:
        return CheckResult(0.0, "адрес не заполнен")

    match = compare_address(expected_address.display_address, actual.display_address)
    if match.share >= 1.0:
        return CheckResult(1.0, "")
    if match.share < ADDRESS_PARTIAL_FLOOR:
        return CheckResult(0.0, "адрес не совпадает с эталоном")
    return CheckResult(match.share, "не указано: {parts}".format(parts=", ".join(match.missing)))


def check_victims(request: ScoreRequest) -> CheckResult:
    """Зафиксированы ли пострадавшие и угроза людям."""
    expected = request.scenario.ground_truth.expected_input.victims
    if expected is None:
        return NOT_APPLICABLE

    actual = request.submitted_card.victims
    if actual is None:
        return CheckResult(0.0, "сведения о пострадавших не заполнены")

    wrong = []
    if actual.present != expected.present:
        wrong.append(
            "пострадавшие: в эталоне {want}, в карточке {got}".format(
                want="есть" if expected.present else "нет",
                got="есть" if actual.present else "нет",
            )
        )
    if expected.threat_to_people is not None and actual.threat_to_people != expected.threat_to_people:
        wrong.append("не зафиксирована угроза людям")

    checked = 1 + (1 if expected.threat_to_people is not None else 0)
    return CheckResult(round((checked - len(wrong)) / checked, 3), "; ".join(wrong))


def check_description(request: ScoreRequest) -> CheckResult:
    """Содержит ли описание существенные обстоятельства.

    Сравниваются значимые слова, а не текст целиком: оператор вправе написать
    своими словами, лишь бы обстоятельства были на месте.
    """
    expected = request.scenario.ground_truth.expected_input.description
    if not expected:
        return NOT_APPLICABLE

    actual = request.submitted_card.description
    if not actual:
        return CheckResult(0.0, "описание не заполнено")

    wanted = _significant_words(expected)
    if not wanted:
        return CheckResult(1.0, "")

    missing = sorted(wanted - _significant_words(actual))
    share = round((len(wanted) - len(missing)) / len(wanted), 3)
    detail = "в описании не отражено: {words}".format(words=", ".join(missing)) if missing else ""
    return CheckResult(share, detail)


def check_classification(request: ScoreRequest) -> CheckResult:
    """Совпал ли код классификатора, вычисленный Core, с эталонным.

    Сравниваются коды, а не текстовые названия: одно и то же происшествие
    в разных классификаторах называется по-разному.
    """
    if request.calculation is None:
        return NOT_APPLICABLE

    expected = request.scenario.ground_truth.classifier_code
    actual = request.calculation.classifier_code
    if actual == expected:
        return CheckResult(1.0, "")
    if actual is None:
        return CheckResult(0.0, "по выбранным признакам происшествие не определилось")
    return CheckResult(
        0.0,
        "определилось происшествие {got}, ожидалось {want}".format(got=actual, want=expected),
    )


def check_services(request: ScoreRequest) -> CheckResult:
    """Сравнивает список оповещения, вычисленный Core, с эталонным.

    Оператор службы не выбирает - они следуют из признаков и ответов.
    Поэтому расхождение здесь всегда следствие ошибки в опросной карте,
    и объяснение указывает, каких служб не хватило.
    """
    if request.calculation is None:
        return NOT_APPLICABLE

    expected = {service.id: service.display_name for service in request.scenario.ground_truth.required_services}
    if not expected:
        return NOT_APPLICABLE

    actual = {service.id: service.display_name for service in request.calculation.services}
    missing = sorted(expected[key] for key in set(expected) - set(actual))
    extra = sorted(actual[key] for key in set(actual) - set(expected))
    hit = len(set(expected) & set(actual))

    share = round(max(0.0, (hit - len(extra)) / len(expected)), 3)

    notes = []
    if missing:
        notes.append("не оповещены: {names}".format(names=", ".join(missing)))
    if extra:
        notes.append("оповещены лишние: {names}".format(names=", ".join(extra)))
    return CheckResult(share, "; ".join(notes))


CHECKERS: Dict[str, Callable[[ScoreRequest], CheckResult]] = {
    "GREETING": check_greeting,
    "SIGNS": check_signs,
    "QUESTIONS": check_questions,
    "ADDRESS": check_address,
    "VICTIMS": check_victims,
    "DESCRIPTION": check_description,
    "CLASSIFICATION": check_classification,
    "SERVICES": check_services,
}

RECOMMENDATION_BY_CODE: Dict[str, str] = {
    "GREETING": "Начинайте разговор с представления: служба, фамилия, номер рабочего места.",
    "SIGNS": "Выбирайте признаки последовательно по опросной карте: из них следует тип происшествия.",
    "QUESTIONS": "Отвечайте на все уточняющие вопросы карты: от них зависит состав служб.",
    "ADDRESS": "Уточняйте адрес до корпуса и подъезда и повторяйте его заявителю вслух.",
    "VICTIMS": "Всегда уточняйте наличие пострадавших и угрозу людям, даже если заявитель молчит об этом.",
    "DESCRIPTION": "Записывайте в описание обстоятельства, которых нет среди признаков.",
    "CLASSIFICATION": "Проверьте выбранные признаки: происшествие определилось не то.",
    "SERVICES": "Состав служб зависит от признаков и ответов, проверьте их перед отправкой.",
}

UNCHECKED_RECOMMENDATION = "Критерий «{code}» автоматически не проверяется, оцените его вручную."

CARD_FIELD_BY_CODE: Dict[str, str] = {
    "SIGNS": "incident.selectedSignIds",
    "QUESTIONS": "incident.answers",
    "ADDRESS": "address.displayAddress",
    "VICTIMS": "victims",
    "DESCRIPTION": "description",
}


# --- проблемы эталона, а не обучающегося --------------------------------------


def _ground_truth_errors(request: ScoreRequest) -> List[ScoringError]:
    """Находит расхождения и пробелы в исходных данных занятия."""
    errors: List[ScoringError] = []
    truth = request.scenario.ground_truth
    catalog_version = load_catalog().version if load_catalog() else ""

    if catalog_version and truth.classifier_version != catalog_version:
        errors.append(
            ScoringError(
                code="CLASSIFIER_VERSION_MISMATCH",
                kind=ErrorKind.GROUND_TRUTH,
                severity=Severity.MAJOR,
                message=(
                    "Сценарий собран по версии классификатора {scenario}, "
                    "а сервис загрузил {catalog}. Оценку нужно перепроверить."
                ).format(scenario=truth.classifier_version, catalog=catalog_version),
            )
        )

    if request.calculation is None:
        errors.append(
            ScoringError(
                code="CALCULATION_MISSING",
                kind=ErrorKind.GROUND_TRUTH,
                severity=Severity.MAJOR,
                message=(
                    "Расчёт Core по карточке не передан, поэтому происшествие "
                    "и список служб не проверялись."
                ),
            )
        )
    elif request.calculation.classifier_version != truth.classifier_version:
        errors.append(
            ScoringError(
                code="CALCULATION_VERSION_MISMATCH",
                kind=ErrorKind.GROUND_TRUTH,
                severity=Severity.MAJOR,
                message=(
                    "Core считал по версии {core}, а эталон собран по {scenario}."
                ).format(
                    core=request.calculation.classifier_version,
                    scenario=truth.classifier_version,
                ),
            )
        )

    if truth.response_scenario_status == ResponseScenarioStatus.MISSING:
        errors.append(
            ScoringError(
                code="RESPONSE_SCENARIO_MISSING",
                kind=ErrorKind.GROUND_TRUTH,
                severity=Severity.MINOR,
                message="В классификаторе у этого происшествия нет сценария реагирования.",
            )
        )

    if not truth.required_services:
        errors.append(
            ScoringError(
                code="REQUIRED_SERVICES_EMPTY",
                kind=ErrorKind.GROUND_TRUTH,
                severity=Severity.MAJOR,
                message="В эталоне нет ни одной службы, состав оповещения проверить нечем.",
            )
        )

    forbidden = sorted(key for key in FORBIDDEN_INPUT_KEYS if key in request.submitted_card.extra_facts)
    if forbidden:
        errors.append(
            ScoringError(
                code="CALCULATED_FIELDS_SUBMITTED",
                kind=ErrorKind.GROUND_TRUTH,
                severity=Severity.CRITICAL,
                message=(
                    "В карточке пришли вычисляемые поля: {names}. Их считает Core, "
                    "клиент подменять их не может."
                ).format(names=", ".join(forbidden)),
                field="facts",
            )
        )

    return errors


# --- сборка отчёта ------------------------------------------------------------


def _distribute_points(criteria: List[RubricCriterion], scored: List[bool]) -> List[float]:
    """Делит сто баллов между критериями, которые удалось проверить."""
    total_weight = sum(criterion.weight for criterion, ok in zip(criteria, scored) if ok)
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


def _penalties(request: ScoreRequest) -> List[Penalty]:
    """Нарушения жёстких нормативов, не покрытые критериями рубрики."""
    result: List[Penalty] = []
    card = request.submitted_card

    no_address = card.address is None or not card.address.display_address
    no_signs = card.incident is None or not card.incident.selected_sign_ids
    if no_address or no_signs:
        result.append(
            Penalty(
                code="CARD_NOT_TRANSFERABLE",
                message=(
                    "Карточку невозможно передать в службу: без адреса или признаков "
                    "происшествия реагирование не начнётся."
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


def score(request: ScoreRequest) -> ScoreResponse:
    """Считает объяснимый отчёт по рубрике сценария.

    Сценарий может прийти от Core с рубрикой-заглушкой из импорта. В этом
    случае берётся минимальный набор критериев: иначе отчёт будет формально
    верным, но разбирать в нём нечего.
    """
    criteria = ensure_rubric(request.scenario).rubric.criteria

    # Сначала проверяем всё, и только потом делим баллы: до проверки неизвестно,
    # какие критерии вообще применимы к этому занятию.
    checks = [
        CHECKERS.get(criterion.code, lambda _: NOT_APPLICABLE)(request) for criterion in criteria
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
                    kind=ErrorKind.OPERATOR,
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

    errors.extend(_ground_truth_errors(request))
    penalties = _penalties(request)

    earned = sum(result.earned_points for result in results)
    lost = sum(penalty.points for penalty in penalties)
    total = round(max(0.0, earned - lost), 2)

    # Зачёт закрывают только ошибки обучающегося. Проблемы эталона видны
    # в отчёте, но в вину ему не ставятся.
    blocking = any(
        error.severity == Severity.CRITICAL and error.kind == ErrorKind.OPERATOR
        for error in errors
    )

    return ScoreResponse(
        session_id=request.session_id,
        scenario_id=str(request.scenario.id),
        classifier_version=request.scenario.ground_truth.classifier_version,
        total_score=total,
        max_score=MAX_SCORE,
        passed=total >= PASS_THRESHOLD and not blocking,
        criteria=results,
        errors=errors,
        penalties=penalties,
        recommendations=recommendations,
        meta=ResponseMeta(engine="rules", version=SERVICE_VERSION, deterministic=True),
    )
