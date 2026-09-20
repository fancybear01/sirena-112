"""Поведение AI-абонента на сценариях каталога.

Главное, что здесь проверяется: абонент знает ровно то, что записано
в ожидаемом вводе оператора, и один и тот же разговор всегда идёт одинаково.
"""

import pytest


def ask(client, scenario, utterance, state=None):
    """Одна реплика оператора. Состояние абонента передаётся между ходами."""
    payload = {
        "aiSessionId": "test",
        "scenario": scenario,
        "operatorUtterance": utterance,
    }
    if state is not None:
        payload["callerState"] = state
    response = client.post("/ai/dialogue/respond", json=payload)
    assert response.status_code == 200
    return response.json()


def dialogue(client, scenario, lines):
    """Прогоняет разговор целиком и возвращает список ответов."""
    state, replies = None, []
    for line in lines:
        answer = ask(client, scenario, line, state)
        state = answer["callerState"]
        replies.append(answer)
    return replies


@pytest.fixture()
def scenarios(client):
    """Все сценарии каталога."""
    return client.post("/ai/scenarios/generate", json={"count": 4}).json()["scenarios"]


def expected(scenario):
    return scenario["groundTruth"]["expectedInput"]


# --- три диалога по разным сценариям ------------------------------------------


def test_dialogue_follows_scenario_facts(client, scenario):
    replies = dialogue(
        client,
        scenario,
        ["Служба 112, слушаю вас", "Назовите адрес", "Что случилось?", "Пострадавшие есть?"],
    )
    truth = expected(scenario)

    assert truth["address"]["displayAddress"] in replies[1]["reply"]
    assert truth["description"].lower() in replies[2]["reply"].lower()
    assert "пострадавших нет" in replies[3]["reply"].lower()
    assert replies[-1]["revealedFacts"] == ["address", "description", "victims"]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_every_catalog_scenario_answers_about_address(client, scenarios, index):
    scenario = scenarios[index]
    answer = ask(client, scenario, "Назовите адрес происшествия")

    assert expected(scenario)["address"]["displayAddress"] in answer["reply"]


def test_victims_answer_comes_from_structured_field(client, scenarios):
    """Сведения о пострадавших лежат структурой, а абонент проговаривает их словами."""
    for scenario in scenarios:
        victims = expected(scenario).get("victims")
        if victims is None:
            continue
        answer = ask(client, scenario, "Пострадавшие есть?")
        assert ("нет" in answer["reply"].lower()) == (victims["present"] is False)


# --- абонент не выдумывает ----------------------------------------------------


def test_address_is_silent_until_asked(client, scenario):
    address = expected(scenario)["address"]["displayAddress"]

    replies = dialogue(
        client, scenario, ["Служба 112, здравствуйте", "Что случилось?", "Успокойтесь"]
    )

    assert all(address not in answer["reply"] for answer in replies)
    assert all("address" not in answer["revealedFacts"] for answer in replies)


def test_unrecognised_question_reveals_nothing(client, scenario):
    answer = ask(client, scenario, "Какого цвета у вас обои в прихожей?")

    assert answer["revealedFacts"] == []
    assert answer["reply"] in ("Простите, не понимаю вопрос.", "Что? Вы приедете или нет?")


def test_caller_never_says_facts_from_another_scenario(client, scenarios):
    scenario, foreign = scenarios[0], scenarios[1]
    foreign_address = expected(foreign)["address"]["displayAddress"]

    replies = dialogue(client, scenario, ["Назовите адрес", "Что случилось?", "Кто звонит?"])

    if foreign_address != expected(scenario)["address"]["displayAddress"]:
        assert all(foreign_address not in answer["reply"] for answer in replies)


def test_question_without_fact_gets_honest_answer(client, scenario):
    """В эталоне нет сведений о заявителе, и выдумывать имя абонент не станет."""
    answer = ask(client, scenario, "Представьтесь, пожалуйста")

    assert answer["revealedFacts"] == []
    assert "называться" in answer["reply"].lower() or "разница" in answer["reply"].lower()


# --- состояние абонента -------------------------------------------------------


def test_greeting_does_not_punish_operator(client, scenario):
    before = ask(client, scenario, "Какая у вас погода?")
    after = ask(client, scenario, "Служба 112, здравствуйте, слушаю вас")

    assert after["callerState"]["trust"] > before["callerState"]["trust"]
    assert after["callerState"]["patience"] > before["callerState"]["patience"]


def test_repeated_question_costs_patience(client, scenario):
    first = ask(client, scenario, "Назовите адрес")
    second = ask(client, scenario, "Назовите адрес", first["callerState"])

    assert second["revealedFacts"] == first["revealedFacts"]
    assert second["callerState"]["patience"] < first["callerState"]["patience"]
    assert "уже" in second["reply"].lower()


def test_caller_hangs_up_when_patience_runs_out(client, scenario):
    state = {"panic": 0.5, "trust": 0.5, "patience": 0.1, "revealedFacts": []}

    answer = ask(client, scenario, "Какого цвета у вас обои?", state)

    assert answer["hangUp"] is True
    assert answer["callerState"]["patience"] == 0.0
    assert answer["revealedFacts"] == []


def test_state_stays_within_bounds(client, scenario):
    replies = dialogue(client, scenario, ["Успокойтесь, помощь уже выехала"] * 8)

    for answer in replies:
        for scale in ("panic", "trust", "patience"):
            assert 0.0 <= answer["callerState"][scale] <= 1.0


# --- форма ответа и воспроизводимость -----------------------------------------


def test_response_has_strict_structure(client, scenario):
    answer = ask(client, scenario, "Назовите адрес")

    assert set(answer) == {"reply", "callerState", "revealedFacts", "hangUp", "meta"}
    assert set(answer["callerState"]) == {"panic", "trust", "patience", "revealedFacts"}
    assert answer["meta"]["deterministic"] is True


def test_same_dialogue_is_reproducible(client, scenario):
    lines = ["Служба 112", "Назовите адрес", "Пострадавшие есть?", "Что случилось?"]

    assert dialogue(client, scenario, lines) == dialogue(client, scenario, lines)


def test_punctuation_and_case_do_not_matter(client, scenario):
    plain = ask(client, scenario, "назовите адрес")
    loud = ask(client, scenario, "АДРЕС?!!")

    assert plain["reply"] == loud["reply"]
