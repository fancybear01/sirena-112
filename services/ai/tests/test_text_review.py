"""Разбор текста карточки и рекомендации преподавателю. Задача #86.

Главное, что здесь проверяется: разбор не выдаёт догадку за проверенный
вывод. У каждого вывода есть измеренная точность, и суждение о смысле
всегда уходит преподавателю на проверку.
"""

import json
from copy import deepcopy

import pytest

from app.engines import card_text, text_review

REFERENCE = (
    "Жильцы сообщают о едком дыме из мусоропровода в подъезде, "
    "открытого пламени не видно, людям угрозы нет"
)


@pytest.fixture(autouse=True)
def real_morphology():
    """Каждый тест начинает с настоящего разбора, а не с чужой подмены."""
    text_review.use_morphology(None)
    text_review.use_semantics(text_review.Semantics(model_path=""))
    yield
    text_review.use_morphology(None)
    text_review.use_semantics(None)


@pytest.fixture()
def scenario_with_reference(scenario):
    """Сценарий с настоящим описанием вместо заглушки импорта."""
    prepared = deepcopy(scenario)
    prepared["groundTruth"]["expectedInput"]["description"] = REFERENCE
    return prepared


def review(client, scenario, **overrides):
    body = {
        "sessionId": "core-1",
        "scenario": scenario,
        "description": None,
        "addressText": "Учебный адрес, дом 1",
        "victimsText": "пострадавших нет",
        "elapsedSeconds": 25,
    }
    body.update(overrides)
    response = client.post("/ai/text/review", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def finding(payload, code):
    return next(item for item in payload["findings"] if item["code"] == code)


# --- смысл --------------------------------------------------------------------


def test_full_description_passes(client, scenario_with_reference):
    payload = review(
        client,
        scenario_with_reference,
        description="В подъезде едкий дым из мусоропровода, открытого пламени не видно, угрозы людям нет",
    )

    assert finding(payload, "MEANING")["status"] == "PASSED"


def test_partial_description_is_partial(client, scenario_with_reference):
    """Пропущены обстоятельства - значит частично, а не провал."""
    payload = review(
        client, scenario_with_reference, description="Жильцы сообщают о дыме из мусоропровода"
    )

    meaning = finding(payload, "MEANING")
    assert meaning["status"] == "PARTIAL"
    assert meaning["details"], "надо перечислить, чего не хватает"


def test_wrong_description_fails(client, scenario_with_reference):
    payload = review(
        client, scenario_with_reference, description="Прорвало трубу в подвале, вода заливает помещение"
    )

    assert finding(payload, "MEANING")["status"] == "FAILED"


def test_empty_description_fails(client, scenario_with_reference):
    payload = review(client, scenario_with_reference, description="")

    assert finding(payload, "MEANING")["status"] == "FAILED"
    assert finding(payload, "REGULATION")["status"] == "FAILED"


def test_word_forms_do_not_cost_points(client, scenario_with_reference):
    """Падеж и порядок слов на вывод не влияют.

    Это и было причиной взяться за разбор: прежняя проверка сравнивала слова
    как есть, и "задымлении" не совпадало с "задымление".
    """
    same_meaning = review(
        client,
        scenario_with_reference,
        description="В подъезде едкий дым из мусоропровода, открытого пламени не видно, угрозы людям нет",
    )
    other_forms = review(
        client,
        scenario_with_reference,
        description="Едкого дыма в подъезде из мусоропровода, открытому пламени не видно, угрозы людям нет",
    )

    assert finding(same_meaning, "MEANING")["status"] == finding(other_forms, "MEANING")["status"]


def test_import_stub_reference_is_not_judged(client, scenario):
    """Эталон-заглушка не повод ругать правильное описание.

    Импорт кладёт в сценарий строку вида "Учебный пример: <тип>". Сравнение
    с ней ставило правильному описанию FAILED за отсутствие слов "учебный"
    и "пример", и преподаватель видел бы чушь.
    """
    payload = review(
        client,
        scenario,
        description="В подъезде едкий дым из мусоропровода, пламени не видно, угрозы людям нет",
    )

    assert finding(payload, "MEANING")["status"] == "NOT_CHECKED"
    assert any("заглушка" in limitation for limitation in payload["limitations"])


# --- грамотность и механика ---------------------------------------------------


def test_typos_are_found(client, scenario_with_reference):
    payload = review(
        client, scenario_with_reference, description="В подьезде едкий дым из мусаропровода"
    )

    spelling = finding(payload, "SPELLING")
    assert spelling["status"] == "FAILED"
    assert "мусаропровода" in spelling["details"]


def test_correct_words_are_not_called_typos(client, scenario_with_reference):
    payload = review(
        client,
        scenario_with_reference,
        description="Жильцы вышли на балкон, дым едкий, мусоропровод в подъезде",
    )

    assert finding(payload, "SPELLING")["status"] == "PASSED"


def test_reference_words_are_never_typos(client, scenario_with_reference):
    """Слова из эталона ошибкой не считаются.

    В эталоне встречаются названия улиц и организаций, которых в общем
    словаре нет. Без этой поблажки проверка ругалась бы на правильно
    списанный адрес.
    """
    prepared = deepcopy(scenario_with_reference)
    prepared["groundTruth"]["expectedInput"]["description"] = "Задымление у здания Спецэлектрод"

    payload = review(client, prepared, description="Задымление у здания Спецэлектрод")

    assert finding(payload, "SPELLING")["status"] == "PASSED"


@pytest.mark.parametrize(
    "description",
    [
        "В подъезде дым из мусoропровода",  # латинская o внутри русского слова
        "В подъезде дым дым из мусоропровода",
        "В подъезде дым из мусоропровода,, пламени нет",
        "В  подъезде  дым  из  мусоропровода",
        "В ПОДЪЕЗДЕ ДЫМ ИЗ МУСОРОПРОВОДА",
    ],
)
def test_manual_editing_defects_are_found(client, scenario_with_reference, description):
    payload = review(client, scenario_with_reference, description=description)

    assert finding(payload, "MECHANICS")["status"] == "FAILED"


# --- время и регламент --------------------------------------------------------


def test_time_over_limit_fails(client, scenario_with_reference):
    payload = review(client, scenario_with_reference, description=REFERENCE, elapsedSeconds=999)

    time = finding(payload, "TIME")
    assert time["status"] == "FAILED"
    assert "999" in time["explanation"]


def test_time_without_elapsed_is_not_checked(client, scenario_with_reference):
    payload = review(client, scenario_with_reference, description=REFERENCE, elapsedSeconds=None)

    assert finding(payload, "TIME")["status"] == "NOT_CHECKED"


def test_missing_fields_are_listed(client, scenario_with_reference):
    payload = review(client, scenario_with_reference, description=REFERENCE, victimsText="")

    regulation = finding(payload, "REGULATION")
    assert regulation["status"] == "FAILED"
    assert any("пострадавшие" in detail for detail in regulation["details"])


# --- честность вывода ---------------------------------------------------------


def test_meaning_always_goes_to_the_teacher(client, scenario_with_reference):
    """Суждение о смысле подтверждённым не объявляется.

    На разметке оно совпало с экспертом в 81 случае из 100. Этого мало,
    чтобы ставить оценку без человека, и ответ обязан это показывать.
    """
    payload = review(client, scenario_with_reference, description=REFERENCE)

    meaning = finding(payload, "MEANING")
    assert meaning["needsTeacherCheck"] is True
    assert 0 < meaning["confidence"] < 1


def test_factual_checks_are_trusted(client, scenario_with_reference):
    """Словарь, механика и время - это проверки факта, а не суждения."""
    payload = review(client, scenario_with_reference, description=REFERENCE)

    for code in ("SPELLING", "MECHANICS", "TIME"):
        assert finding(payload, code)["needsTeacherCheck"] is False, code


def test_limitations_are_never_empty(client, scenario_with_reference):
    """Про синонимы и отсутствие нейросети молчать нельзя."""
    payload = review(client, scenario_with_reference, description=REFERENCE)

    assert payload["limitations"]
    assert any("синоним" in limitation.lower() for limitation in payload["limitations"])
    assert any("нейросет" in limitation.lower() for limitation in payload["limitations"])


def test_same_text_gives_same_answer(client, scenario_with_reference):
    first = review(client, scenario_with_reference, description=REFERENCE)
    second = review(client, scenario_with_reference, description=REFERENCE)

    assert first == second


# --- работа без словаря -------------------------------------------------------


class NoDictionary:
    """Машина без pymorphy3: разбора нет, и врать об этом нельзя."""

    available = False

    def lemma(self, word):
        return word

    def known(self, word):
        return None


def test_without_dictionary_spelling_is_not_faked(client, scenario_with_reference):
    text_review.use_morphology(NoDictionary())

    payload = review(client, scenario_with_reference, description="В подьезде дым из мусаропровода")

    assert payload["method"] == "words"
    assert finding(payload, "SPELLING")["status"] == "NOT_CHECKED"
    assert any("словарь" in limitation.lower() for limitation in payload["limitations"])


def test_without_dictionary_answer_is_still_deterministic(client, scenario_with_reference):
    text_review.use_morphology(NoDictionary())

    first = review(client, scenario_with_reference, description=REFERENCE)
    second = review(client, scenario_with_reference, description=REFERENCE)

    assert first == second


def test_without_dictionary_mechanics_still_works(client, scenario_with_reference):
    """Механика словаря не требует: раскладку и дубли видно и без него."""
    text_review.use_morphology(NoDictionary())

    payload = review(client, scenario_with_reference, description="В подъезде дым дым из мусоропровода")

    assert finding(payload, "MECHANICS")["status"] == "FAILED"


# --- модель смысла ------------------------------------------------------------


class FakeSemantics:
    """Модель, которая считает синонимами заранее заданные пары."""

    available = True

    def __init__(self, pairs) -> None:
        self.pairs = {frozenset(pair) for pair in pairs}
        self.asked = []

    def closest(self, wanted, candidates):
        self.asked.append(wanted)
        for candidate in candidates:
            if frozenset((wanted, candidate)) in self.pairs:
                return 1.0
        return 0.0

    def similarity(self, first, second):
        return 0.0


def test_without_model_meaning_falls_back_to_forms(client, scenario_with_reference):
    """Модели нет - разбор работает на морфологии и не делает вид, что понял."""
    payload = review(
        client, scenario_with_reference, description="Жильцы сообщают о дыме из мусоропровода"
    )

    assert finding(payload, "MEANING")["status"] == "PARTIAL"
    assert any("синоним" in limitation.lower() for limitation in payload["limitations"])


def test_model_is_asked_only_about_missing_words():
    """Модель дорогая, и звать её на совпавшие слова незачем."""
    model = FakeSemantics([("автомобиль", "машина")])
    text_review.use_semantics(model)

    share, missing = text_review.cover({"автомобиль", "перекресток"}, {"машина", "перекресток"}, 0.5)

    assert model.asked == ["автомобиль"], "спрашивали лишнее: %s" % model.asked
    assert missing == []
    assert share == 1.0


def test_model_closes_a_synonym_gap():
    model = FakeSemantics([("пострадать", "раненый")])
    text_review.use_semantics(model)

    without = text_review.cover({"пострадать", "автомобиль"}, {"раненый", "автомобиль"}, 1.1)
    with_model = text_review.cover({"пострадать", "автомобиль"}, {"раненый", "автомобиль"}, 0.5)

    assert without[1] == ["пострадать"]
    assert with_model[1] == []


def test_unset_model_path_means_no_model(monkeypatch):
    """Пустая переменная окружения - это не ошибка, а штатный режим."""
    monkeypatch.delenv(text_review.Semantics.ENVIRONMENT_VARIABLE, raising=False)

    assert text_review.Semantics().available is False


def test_broken_model_path_does_not_break_the_service(monkeypatch):
    """Неверный путь к модели не должен ронять разбор."""
    monkeypatch.setenv(text_review.Semantics.ENVIRONMENT_VARIABLE, "/нет/такого/пути")

    assert text_review.Semantics().available is False


# --- рекомендации группе ------------------------------------------------------


def errors_for(code, count, start=0):
    return [{"sessionId": "s%d" % index, "criterionCode": code} for index in range(start, start + count)]


def recommend(client, **body):
    response = client.post("/ai/groups/recommendations", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_frequent_error_becomes_a_recommendation(client):
    payload = recommend(client, groupId="g1", sessionsTotal=10, errors=errors_for("ADDRESS", 6))

    assert [item["criterionCode"] for item in payload["recommendations"]] == ["ADDRESS"]
    assert payload["recommendations"][0]["sessionsAffected"] == 6
    assert payload["recommendations"][0]["editable"] is True


def test_rare_error_is_not_a_group_topic(client):
    """Ошибка одного обучающегося - не тема для занятия с группой."""
    payload = recommend(client, sessionsTotal=10, errors=errors_for("ADDRESS", 1))

    assert payload["recommendations"] == []


def test_same_criterion_twice_in_one_session_counts_once(client):
    """Иначе один старательно проваленный критерий перевесит всю группу."""
    errors = [{"sessionId": "s1", "criterionCode": "ADDRESS"} for _ in range(9)]

    payload = recommend(client, sessionsTotal=10, errors=errors)

    assert payload["recommendations"] == []


def test_recommendations_are_ordered_and_reproducible(client):
    errors = errors_for("ADDRESS", 6) + errors_for("VICTIMS", 8)

    first = recommend(client, sessionsTotal=10, errors=errors)
    second = recommend(client, sessionsTotal=10, errors=errors)

    assert first == second
    assert [item["criterionCode"] for item in first["recommendations"]] == ["VICTIMS", "ADDRESS"]


def test_unknown_criterion_does_not_invent_facts(client):
    payload = recommend(client, sessionsTotal=10, errors=errors_for("НЕИЗВЕСТНЫЙ", 5))

    assert payload["recommendations"][0]["criterionCode"] == "НЕИЗВЕСТНЫЙ"
    assert "НЕИЗВЕСТНЫЙ" in payload["recommendations"][0]["text"]


def test_no_history_says_so(client):
    payload = recommend(client, sessionsTotal=0, errors=[])

    assert payload["recommendations"] == []
    assert any("мало" in limitation.lower() for limitation in payload["limitations"])


def test_recommendations_always_carry_limitations(client):
    payload = recommend(client, sessionsTotal=10, errors=errors_for("ADDRESS", 6))

    assert payload["limitations"]


# --- никакой сети -------------------------------------------------------------


def test_review_makes_no_network_calls(client, scenario_with_reference, monkeypatch):
    """Разбор обязан работать без интернета.

    Проверяется грубо, но надёжно: любая попытка открыть сокет роняет тест.
    """
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("разбор текста попытался выйти в сеть")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    payload = card_text.review(
        __import__("app.schemas.text", fromlist=["TextReviewRequest"]).TextReviewRequest.model_validate(
            {
                "sessionId": "core-1",
                "scenario": scenario_with_reference,
                "description": REFERENCE,
                "elapsedSeconds": 20,
            }
        )
    )

    assert payload.findings


def test_benchmark_dataset_has_no_personal_data():
    """В наборе не должно быть настоящих адресов, телефонов и имён."""
    from pathlib import Path

    dataset = json.loads(
        (Path(__file__).resolve().parents[1] / "benchmarks" / "text_review" / "dataset.json").read_text(
            encoding="utf-8"
        )
    )

    assert dataset["cases"], "набор пуст"
    for case in dataset["cases"]:
        assert not any(character.isdigit() for character in case["submitted"]), case["id"]
        for check in ("meaning", "spelling", "mechanics"):
            assert case["expert"][check] in ("PASSED", "PARTIAL", "FAILED"), case["id"]
