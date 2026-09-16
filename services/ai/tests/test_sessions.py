"""Оценка учебной сессии.

Инварианты, которые обязаны держаться при любом входе:
сумма maxPoints равна maxScore, итог равен заработанному минус штрафы,
и каждое снижение оценки объяснено.
"""

import pytest

GOOD_TRANSCRIPT = [
    {"role": "OPERATOR", "text": "Служба 112, здравствуйте", "atMs": 0},
    {"role": "CALLER", "text": "Помогите!", "atMs": 900},
    {"role": "OPERATOR", "text": "Назовите адрес", "atMs": 3000},
    {"role": "OPERATOR", "text": "Пострадавшие есть?", "atMs": 9000},
]


def perfect_card(scenario):
    truth = scenario["groundTruth"]
    return {
        "incidentType": truth["incidentType"],
        "signs": truth["signs"],
        "address": truth["address"],
        "requiredServices": truth["requiredServices"],
    }


def score(client, scenario, card=None, transcript=None, elapsed=None):
    payload = {
        "sessionId": "session-test",
        "scenario": scenario,
        "submittedCard": perfect_card(scenario) if card is None else card,
        "transcript": GOOD_TRANSCRIPT if transcript is None else transcript,
    }
    if elapsed is not None:
        payload["elapsedSeconds"] = elapsed
    response = client.post("/ai/sessions/score", json=payload)
    assert response.status_code == 200
    return response.json()


def criterion(report, code):
    return next(item for item in report["criteria"] if item["code"] == code)


# --- успешное и ошибочное прохождение -----------------------------------------


def test_perfect_session_passes_with_full_score(client, scenario):
    report = score(client, scenario, elapsed=20)

    assert report["totalScore"] == 100.0
    assert report["passed"] is True
    assert report["errors"] == []
    assert report["penalties"] == []


def test_empty_card_fails(client, scenario):
    report = score(client, scenario, card={}, elapsed=90)

    assert report["totalScore"] == 0.0
    assert report["passed"] is False
    assert any(error["severity"] == "CRITICAL" for error in report["errors"])


# --- инварианты отчёта --------------------------------------------------------


@pytest.mark.parametrize("card", [None, {}, {"address": "Тверская 1"}])
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
    report = score(client, scenario, card={"address": "Берзарина 21"})

    failed = {item["code"] for item in report["criteria"] if item["status"] != "PASSED"}
    explained = {
        item["code"].replace("CRITERION_", "")
        for item in report["errors"]
        if item["code"].startswith("CRITERION_")
    }
    assert failed == explained
    assert all(item["message"] for item in report["errors"])


def test_score_is_reproducible(client, scenario):
    first = score(client, scenario, card={"address": "Берзарина"}, elapsed=55)
    second = score(client, scenario, card={"address": "Берзарина"}, elapsed=55)

    assert first == second


# --- отдельные проверки -------------------------------------------------------


def test_address_abbreviations_are_accepted(client, scenario):
    card = perfect_card(scenario)
    card["address"] = card["address"].replace("д. ", "дом ").upper()

    assert criterion(score(client, scenario, card=card), "ADDRESS")["status"] == "PASSED"


def test_incomplete_address_is_partial_and_names_missing_parts(client, scenario):
    card = perfect_card(scenario)
    # Потеряно строение: остального достаточно, чтобы засчитать частично.
    card["address"] = "Москва, МЖД Киевская 1 км, д. 2"

    report = score(client, scenario, card=card)
    result = criterion(report, "ADDRESS")
    message = next(item["message"] for item in report["errors"] if "ADDRESS" in item["code"])

    assert result["status"] == "PARTIAL"
    assert 0 < result["earnedPoints"] < result["maxPoints"]
    assert "не указано" in message


def test_wrong_sign_level_is_partial(client, scenario):
    card = perfect_card(scenario)
    card["signs"] = dict(card["signs"], level3="дым")

    report = score(client, scenario, card=card)
    result = criterion(report, "SIGNS")
    message = next(item["message"] for item in report["errors"] if "SIGNS" in item["code"])

    assert result["status"] == "PARTIAL"
    assert "третьего уровня" in message


def test_extra_service_costs_points(client, scenario):
    card = perfect_card(scenario)
    card["requiredServices"] = card["requiredServices"] + ["Мослифт"]

    report = score(client, scenario, card=card)
    message = next(item["message"] for item in report["errors"] if "SERVICES" in item["code"])

    assert criterion(report, "SERVICES")["status"] != "PASSED"
    assert "лишнее: Мослифт" in message


def test_missing_service_names_it_as_written(client, scenario):
    card = perfect_card(scenario)
    dropped = card["requiredServices"][0]
    card["requiredServices"] = card["requiredServices"][1:]

    report = score(client, scenario, card=card)
    message = next(item["message"] for item in report["errors"] if "SERVICES" in item["code"])

    assert dropped in message


# --- проверки по транскрипту --------------------------------------------------


def test_greeting_is_checked_by_transcript(client, scenario):
    without = [{"role": "OPERATOR", "text": "Назовите адрес", "atMs": 0}]

    report = score(client, scenario, transcript=without)
    result = criterion(report, "GREETING")

    assert result["status"] == "FAILED"
    assert any("представления службы" in item["message"] for item in report["errors"])


def test_victims_question_is_checked_by_transcript(client, scenario):
    without = [{"role": "OPERATOR", "text": "Служба 112, назовите адрес", "atMs": 0}]

    report = score(client, scenario, transcript=without)

    assert criterion(report, "VICTIMS")["status"] == "FAILED"


def test_caller_words_do_not_count_as_operator_questions(client, scenario):
    """Вопрос о пострадавших должен задать оператор, а не заявитель."""
    transcript = [
        {"role": "OPERATOR", "text": "Служба 112", "atMs": 0},
        {"role": "CALLER", "text": "А пострадавшие будут?", "atMs": 500},
    ]

    assert criterion(score(client, scenario, transcript=transcript), "VICTIMS")["status"] == "FAILED"


def test_card_mode_does_not_punish_missing_conversation(client, scenario):
    """В карточном режиме звонка нет, наказывать за непредставление нельзя."""
    report = score(client, scenario, transcript=[], elapsed=20)

    assert criterion(report, "GREETING")["maxPoints"] == 0.0
    assert criterion(report, "VICTIMS")["maxPoints"] == 0.0
    assert report["totalScore"] == 100.0
    assert report["passed"] is True


# --- штрафы -------------------------------------------------------------------


def test_time_penalty_applied_only_over_limit(client, scenario):
    limit = scenario["timeLimitSeconds"]

    within = score(client, scenario, elapsed=limit)
    over = score(client, scenario, elapsed=limit + 1)

    assert within["penalties"] == []
    assert [item["code"] for item in over["penalties"]] == ["TIME_LIMIT_EXCEEDED"]
    assert over["totalScore"] < within["totalScore"]


def test_card_without_address_cannot_be_transferred(client, scenario):
    card = perfect_card(scenario)
    card["address"] = None

    report = score(client, scenario, card=card)
    codes = [item["code"] for item in report["penalties"]]

    assert "CARD_NOT_TRANSFERABLE" in codes
    assert any(
        item["severity"] == "CRITICAL" and item["code"] == "CARD_NOT_TRANSFERABLE"
        for item in report["errors"]
    )
    assert report["passed"] is False


def test_recommendation_for_each_error(client, scenario):
    report = score(client, scenario, card={"address": "Берзарина 21"})

    assert len(report["recommendations"]) >= 1
    assert all(text for text in report["recommendations"])
