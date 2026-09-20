"""Рубрика дополняется, когда в сценарии лежит заглушка импорта.

Сценарии приходят из каталога, а каталог про методику обучения ничего
не знает: импорт кладёт в рубрику один критерий. Если считать по ней,
преподаватель увидит "сто баллов, критерий один" - разбирать нечего.
"""

import json
from copy import deepcopy

from tests.conftest import CONTRACTS_DIR, core_calculation, perfect_card


def placeholder_scenario():
    """Сценарий прямо из общего файла, с рубрикой-заглушкой импорта."""
    return json.loads(
        (CONTRACTS_DIR / "examples" / "scenario-1050602.json").read_text(encoding="utf-8")
    )


def test_shared_example_really_has_placeholder_rubric():
    """Если импорт начнёт класть полную рубрику, этот тест напомнит убрать костыль."""
    codes = {item["code"] for item in placeholder_scenario()["rubric"]["criteria"]}

    assert len(codes) < 6


def test_scenario_from_catalog_gets_full_rubric(client, scenario):
    codes = {item["code"] for item in scenario["rubric"]["criteria"]}

    assert {"SIGNS", "QUESTIONS", "ADDRESS", "VICTIMS", "DESCRIPTION", "SERVICES"} <= codes


def test_scoring_completes_rubric_from_core_scenario(client):
    """Core присылает сценарий как есть, и оценка всё равно должна быть разбором."""
    raw = placeholder_scenario()

    report = client.post(
        "/ai/sessions/score",
        json={
            "sessionId": "s",
            "scenario": raw,
            "submittedCard": perfect_card(raw),
            "calculation": core_calculation(raw),
        },
    ).json()
    codes = {item["code"] for item in report["criteria"]}

    assert len(codes) >= 6
    assert "ADDRESS" in codes and "SERVICES" in codes


def test_teacher_rubric_is_respected(client):
    """Полную рубрику преподавателя сервис не переписывает."""
    raw = placeholder_scenario()
    raw["rubric"] = {
        "criteria": [
            {"code": code, "description": code, "weight": 1.0}
            for code in ("SIGNS", "QUESTIONS", "ADDRESS", "VICTIMS", "DESCRIPTION", "SERVICES")
        ]
    }

    report = client.post(
        "/ai/sessions/score",
        json={
            "sessionId": "s",
            "scenario": raw,
            "submittedCard": perfect_card(raw),
            "calculation": core_calculation(raw),
        },
    ).json()

    # GREETING и CLASSIFICATION есть в наборе сервиса, но их преподаватель
    # не выбрал - значит их и не должно быть в отчёте.
    assert {item["code"] for item in report["criteria"]} == {
        "SIGNS",
        "QUESTIONS",
        "ADDRESS",
        "VICTIMS",
        "DESCRIPTION",
        "SERVICES",
    }


def test_completed_rubric_produces_meaningful_report(client):
    """Ошибка в карточке должна быть видна, а не тонуть в единственном критерии."""
    raw = placeholder_scenario()
    card = deepcopy(raw["groundTruth"]["expectedInput"])
    card["address"]["displayAddress"] = "Совсем другая улица"

    report = client.post(
        "/ai/sessions/score",
        json={
            "sessionId": "s",
            "scenario": raw,
            "submittedCard": card,
            "calculation": core_calculation(raw),
        },
    ).json()

    assert report["passed"] is False
    assert any("ADDRESS" in item["code"] for item in report["errors"])
