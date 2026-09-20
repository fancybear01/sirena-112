"""Сценарии приходят из общего каталога, а не из копии внутри сервиса."""

import json

from jsonschema import Draft202012Validator, FormatChecker

from tests.conftest import CONTRACTS_DIR, GOLDEN_CODE


def test_scenarios_come_from_shared_examples(client):
    response = client.post("/ai/scenarios/generate", json={"count": 4})

    assert response.status_code == 200
    codes = {s["groundTruth"]["classifierCode"] for s in response.json()["scenarios"]}
    assert GOLDEN_CODE in codes


def test_generated_scenario_matches_contract(client, scenario_schema):
    """Сценарий обязан проходить contracts/scenario.schema.json без правок."""
    response = client.post("/ai/scenarios/generate", json={"count": 4})
    validator = Draft202012Validator(scenario_schema, format_checker=FormatChecker())

    for item in response.json()["scenarios"]:
        errors = sorted(validator.iter_errors(item), key=lambda error: error.path)
        assert errors == [], [error.message for error in errors]


def test_golden_scenario_is_identical_to_shared_file(client, scenario):
    """Классификационные данные сервис не переписывает: они общие с Core."""
    shared = json.loads(
        (CONTRACTS_DIR / "examples" / "scenario-1050602.json").read_text(encoding="utf-8")
    )

    assert scenario["id"] == shared["id"]
    for field in (
        "classifierVersion",
        "classifierCode",
        "incidentType",
        "ekp35IncidentType",
        "responseScenarioCode",
        "responseScenarioStatus",
        "requiredServices",
        "mainServices",
        "expectedInput",
    ):
        assert scenario["groundTruth"][field] == shared["groundTruth"][field]


def test_generate_is_reproducible(client):
    payload = {"category": "FIRE", "count": 2, "seed": 7}

    first = client.post("/ai/scenarios/generate", json=payload)
    second = client.post("/ai/scenarios/generate", json=payload)

    assert first.json() == second.json()


def test_filter_by_category(client):
    response = client.post("/ai/scenarios/generate", json={"category": "MEDICAL", "count": 1})

    assert [s["category"] for s in response.json()["scenarios"]] == ["MEDICAL"]


def test_caller_persona_is_added_by_service(client, scenario):
    """Каталог не знает про характер звонящего, его задаёт сервис."""
    assert scenario["caller"]["persona"]
    assert 0.0 <= scenario["caller"]["panic"] <= 1.0


def test_rubric_covers_required_criteria(client, scenario):
    """Рубрика - методика обучения, в классификаторе её нет."""
    codes = {item["code"] for item in scenario["rubric"]["criteria"]}

    assert {"SIGNS", "QUESTIONS", "ADDRESS", "VICTIMS", "DESCRIPTION", "SERVICES"} <= codes
