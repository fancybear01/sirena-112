"""Поведение AI-абонента.

Главное, что здесь проверяется: абонент не может сообщить того, чего нет
в сценарии, и один и тот же разговор всегда идёт одинаково.
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
    """Все три сценария каталога: пожар, задымление, ДТП."""
    return client.post("/ai/scenarios/generate", json={"count": 3, "seed": 1}).json()[
        "scenarios"
    ]


# --- три диалога, по одному на сценарий ---------------------------------------


def test_dialogue_fire_container(client, scenarios):
    scenario = scenarios[0]
    replies = dialogue(
        client,
        scenario,
        ["Служба 112, слушаю вас", "Назовите адрес", "Что горит?", "Пострадавшие есть?"],
    )

    assert scenario["groundTruth"]["address"] in replies[1]["reply"]
    assert "мусорный контейнер" in replies[2]["reply"]
    assert "пострадавших нет" in replies[3]["reply"].lower()
    assert replies[-1]["revealedFacts"] == ["address", "openFlame", "victims"]


def test_dialogue_smoke_in_building(client, scenarios):
    scenario = scenarios[1]
    replies = dialogue(
        client,
        scenario,
        ["Назовите адрес происшествия", "На каком вы этаже?", "Представьтесь, пожалуйста"],
    )

    assert "Берзарина" in replies[0]["reply"]
    # За один вопрос абонент выдаёт не больше двух фактов: он не диктует анкету.
    assert "седьмом этаже" in replies[1]["reply"] and "17 этажей" in replies[1]["reply"]
    assert "Ким Олег Юрьевич" in replies[2]["reply"]
    assert all(answer["hangUp"] is False for answer in replies)


def test_dialogue_road_accident(client, scenarios):
    scenario = scenarios[2]
    replies = dialogue(
        client, scenario, ["Что произошло?", "Сколько пострадавших?", "Куда ехать?"]
    )

    assert "троллейбус" in replies[0]["reply"].lower()
    assert "3 пострадавших" in replies[1]["reply"]
    assert "Волгоградский проспект" in replies[2]["reply"]


# --- абонент не выдумывает ----------------------------------------------------


def test_address_is_silent_until_asked(client, scenario):
    """Пока оператор не спросил адрес, абонент его не называет."""
    address = scenario["groundTruth"]["address"]

    replies = dialogue(
        client, scenario, ["Служба 112, здравствуйте", "Что случилось?", "Успокойтесь"]
    )

    assert all(address not in answer["reply"] for answer in replies)
    assert all("address" not in answer["revealedFacts"] for answer in replies)


def test_unrecognised_question_reveals_nothing(client, scenario):
    answer = ask(client, scenario, "Какого цвета у вас обои в прихожей?")

    assert answer["revealedFacts"] == []
    assert answer["reply"] in ("Простите, не понимаю вопрос.", "Что? Вы приедете или нет?")


def test_caller_never_says_facts_absent_from_scenario(client, scenarios):
    """Реплика не содержит данных из чужих сценариев."""
    scenario = scenarios[0]
    foreign = scenarios[1]["groundTruth"]

    replies = dialogue(
        client,
        scenario,
        ["Назовите адрес", "Что горит?", "На каком вы этаже?", "Кто звонит?"],
    )

    for answer in replies:
        assert foreign["address"] not in answer["reply"]
        assert foreign["facts"]["callerName"] not in answer["reply"]


def test_question_without_fact_gets_honest_answer(client, scenarios):
    """Если факта в сценарии нет, абонент говорит, что не знает, а не выдумывает."""
    # В сценарии с ДТП нет ни этажей, ни домофона.
    answer = ask(client, scenarios[2], "На каком вы этаже?")

    assert answer["revealedFacts"] == []
    assert "не знаю" in answer["reply"].lower()


# --- состояние абонента -------------------------------------------------------


def test_greeting_does_not_punish_operator(client, scenario):
    """Представление по регламенту - правильное действие, терпение почти не падает."""
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
    """Шкалы не выходят за границы, сколько бы реплик ни было."""
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

    first = dialogue(client, scenario, lines)
    second = dialogue(client, scenario, lines)

    assert first == second


def test_punctuation_and_case_do_not_matter(client, scenario):
    plain = ask(client, scenario, "назовите адрес")
    loud = ask(client, scenario, "АДРЕС?!!")

    assert plain["reply"] == loud["reply"]
