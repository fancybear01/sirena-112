"""Оценка учебной сессии по эталону классификатора.

Проверяется главное свойство: AI не считает службы сам, а сравнивает расчёт
Core с эталоном сценария, и объясняет каждое снижение балла.
"""

from copy import deepcopy

import pytest

from tests.conftest import core_calculation, perfect_card

GOOD_TRANSCRIPT = [
    {"role": "OPERATOR", "text": "Служба 112, здравствуйте", "atMs": 0},
    {"role": "CALLER", "text": "Помогите!", "atMs": 900},
    {"role": "OPERATOR", "text": "Назовите адрес", "atMs": 3000},
]


def score(client, scenario, card=None, calculation=..., transcript=None, elapsed=None):
    payload = {
        "sessionId": "session-test",
        "scenario": scenario,
        "submittedCard": perfect_card(scenario) if card is None else card,
        "transcript": GOOD_TRANSCRIPT if transcript is None else transcript,
    }
    payload["calculation"] = core_calculation(scenario) if calculation is ... else calculation
    if elapsed is not None:
        payload["elapsedSeconds"] = elapsed
    response = client.post("/ai/sessions/score", json=payload)
    assert response.status_code == 200
    return response.json()


def criterion(report, code):
    return next(item for item in report["criteria"] if item["code"] == code)


def message_for(report, code):
    return next(item["message"] for item in report["errors"] if code in item["code"])


# --- успешное и ошибочное прохождение -----------------------------------------


def test_perfect_session_passes_with_full_score(client, scenario):
    report = score(client, scenario, elapsed=20)

    assert report["totalScore"] == 100.0
    assert report["passed"] is True
    assert report["errors"] == []
    assert report["penalties"] == []


def test_empty_card_fails(client, scenario):
    """По пустой карточке Core ничего не определит, и зачёта быть не может."""
    nothing_resolved = core_calculation(
        scenario, status="INCOMPLETE", classifierCode=None, services=[], mainServices=[]
    )

    report = score(client, scenario, card={}, calculation=nothing_resolved, elapsed=90)

    assert report["totalScore"] == 0.0
    assert report["passed"] is False
    assert any(item["severity"] == "CRITICAL" for item in report["errors"])


# --- отчёт помнит, по какому эталону считал -----------------------------------


def test_report_identifies_scenario_and_catalog_version(client, scenario):
    report = score(client, scenario)

    assert report["sessionId"] == "session-test"
    assert report["scenarioId"] == scenario["id"]
    assert report["classifierVersion"] == scenario["groundTruth"]["classifierVersion"]


# --- инварианты отчёта --------------------------------------------------------


@pytest.mark.parametrize("card", [None, {}, {"description": "что-то"}])
def test_criteria_points_always_sum_to_max_score(client, scenario, card):
    report = score(client, scenario, card=card)

    total = round(sum(item["maxPoints"] for item in report["criteria"]), 2)
    assert total == report["maxScore"]


def test_total_equals_earned_minus_penalties(client, scenario):
    report = score(client, scenario, card={}, elapsed=200)

    earned = sum(item["earnedPoints"] for item in report["criteria"])
    lost = sum(item["points"] for item in report["penalties"])
    assert report["totalScore"] == round(max(0.0, earned - lost), 2)


def test_every_lost_criterion_is_explained(client, scenario):
    card = perfect_card(scenario)
    card["address"]["displayAddress"] = "Совсем другая улица"

    report = score(client, scenario, card=card)
    failed = {item["code"] for item in report["criteria"] if item["status"] != "PASSED"}
    explained = {
        item["code"].replace("CRITERION_", "")
        for item in report["errors"]
        if item["code"].startswith("CRITERION_")
    }
    assert failed == explained


def test_score_is_reproducible(client, scenario):
    card = perfect_card(scenario)
    card["description"] = "короткое описание"

    first = score(client, scenario, card=card, elapsed=55)
    second = score(client, scenario, card=card, elapsed=55)

    assert first == second


# --- признаки и вопросы опросной карты ----------------------------------------


def test_missing_sign_is_named_by_label(client, scenario):
    card = perfect_card(scenario)
    card["incident"]["selectedSignIds"] = card["incident"]["selectedSignIds"][:2]

    report = score(client, scenario, card=card)

    assert criterion(report, "SIGNS")["status"] == "PARTIAL"
    assert "дым" in message_for(report, "SIGNS")


def test_unanswered_question_lowers_score_and_is_explained(client, scenario):
    card = perfect_card(scenario)
    dropped = card["incident"]["answers"].pop()

    report = score(client, scenario, card=card)

    assert criterion(report, "QUESTIONS")["status"] == "PARTIAL"
    assert "не уточнено" in message_for(report, "QUESTIONS")
    assert dropped["questionId"]


def test_different_answer_is_distinguished_from_missing_one(client, scenario):
    card = perfect_card(scenario)
    card["incident"]["answers"][0]["optionIds"] = ["YES"]

    report = score(client, scenario, card=card)

    assert "ответ отличается" in message_for(report, "QUESTIONS")


# --- службы и классификация приходят от Core ----------------------------------


def test_services_are_compared_with_core_result(client, scenario):
    calculation = core_calculation(scenario)
    dropped = calculation["services"].pop()

    report = score(client, scenario, calculation=calculation)

    assert criterion(report, "SERVICES")["status"] != "PASSED"
    assert dropped["displayName"] in message_for(report, "SERVICES")


def test_wrong_classification_is_reported(client, scenario):
    calculation = core_calculation(scenario, classifierCode="2010000")

    report = score(client, scenario, calculation=calculation)

    assert criterion(report, "CLASSIFICATION")["status"] == "FAILED"
    assert "2010000" in message_for(report, "CLASSIFICATION")


def test_without_core_calculation_services_are_not_scored(client, scenario):
    """Сам AI службы не считает: без расчёта Core проверять нечем."""
    report = score(client, scenario, calculation=None)

    assert criterion(report, "SERVICES")["maxPoints"] == 0.0
    assert criterion(report, "CLASSIFICATION")["maxPoints"] == 0.0
    assert any(item["code"] == "CALCULATION_MISSING" for item in report["errors"])


# --- ошибки эталона отделены от ошибок оператора ------------------------------


def test_catalog_version_change_is_detected(client, scenario):
    stale = deepcopy(scenario)
    stale["groundTruth"]["classifierVersion"] = "045-2023-01-01"

    report = score(client, stale, calculation=core_calculation(stale))
    mismatch = next(item for item in report["errors"] if item["code"] == "CLASSIFIER_VERSION_MISMATCH")

    assert mismatch["kind"] == "GROUND_TRUTH"
    assert "045-2023-01-01" in mismatch["message"]


def test_ground_truth_problem_does_not_block_pass(client, scenario):
    """Расхождение версий - вопрос к данным, а не к обучающемуся."""
    stale = deepcopy(scenario)
    stale["groundTruth"]["classifierVersion"] = "045-2023-01-01"

    report = score(client, stale, calculation=core_calculation(stale), elapsed=20)

    assert any(item["kind"] == "GROUND_TRUTH" for item in report["errors"])
    assert all(item["kind"] != "OPERATOR" for item in report["errors"])
    assert report["passed"] is True


def test_calculated_fields_cannot_be_submitted_by_client(client, scenario):
    card = perfect_card(scenario)
    card["facts"] = {"classifierCode": "1050602", "requiredServices": ["MCHS"]}

    report = score(client, scenario, card=card)
    substituted = next(item for item in report["errors"] if item["code"] == "CALCULATED_FIELDS_SUBMITTED")

    assert substituted["kind"] == "GROUND_TRUTH"
    assert "classifierCode" in substituted["message"]


# --- адрес, пострадавшие, описание --------------------------------------------


def test_address_abbreviations_are_accepted(client, scenario):
    card = perfect_card(scenario)
    card["address"]["displayAddress"] = card["address"]["displayAddress"].upper()

    assert criterion(score(client, scenario, card=card), "ADDRESS")["status"] == "PASSED"


def test_victims_must_be_recorded(client, scenario):
    card = perfect_card(scenario)
    card.pop("victims")

    report = score(client, scenario, card=card)

    assert criterion(report, "VICTIMS")["status"] == "FAILED"
    assert "не заполнены" in message_for(report, "VICTIMS")


def test_description_is_compared_by_meaning_not_wording(client, scenario):
    """Порядок слов и формулировка не важны, важны обстоятельства."""
    original = scenario["groundTruth"]["expectedInput"]["description"]
    card = perfect_card(scenario)
    card["description"] = " ".join(reversed(original.split()))

    assert criterion(score(client, scenario, card=card), "DESCRIPTION")["status"] == "PASSED"


# --- разговор и нормативы -----------------------------------------------------


def test_greeting_is_checked_by_transcript(client, scenario):
    without = [{"role": "OPERATOR", "text": "Назовите адрес", "atMs": 0}]

    report = score(client, scenario, transcript=without)

    assert criterion(report, "GREETING")["status"] == "FAILED"


def test_card_mode_does_not_punish_missing_conversation(client, scenario):
    report = score(client, scenario, transcript=[], elapsed=20)

    assert criterion(report, "GREETING")["maxPoints"] == 0.0
    assert report["totalScore"] == 100.0


def test_time_penalty_applied_only_over_limit(client, scenario):
    limit = scenario["timeLimitSeconds"]

    within = score(client, scenario, elapsed=limit)
    over = score(client, scenario, elapsed=limit + 1)

    assert within["penalties"] == []
    assert [item["code"] for item in over["penalties"]] == ["TIME_LIMIT_EXCEEDED"]


def test_card_without_address_cannot_be_transferred(client, scenario):
    card = perfect_card(scenario)
    card.pop("address")

    report = score(client, scenario, card=card)

    assert "CARD_NOT_TRANSFERABLE" in [item["code"] for item in report["penalties"]]
    assert report["passed"] is False
