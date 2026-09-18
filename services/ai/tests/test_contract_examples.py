import json
from pathlib import Path
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPOSITORY_ROOT / "contracts"


def test_scenario_1050602_matches_current_scenario_schema() -> None:
    schema = json.loads((CONTRACTS_DIR / "scenario.schema.json").read_text(encoding="utf-8"))
    example = json.loads(
        (CONTRACTS_DIR / "examples" / "scenario-1050602.json").read_text(encoding="utf-8")
    )

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors(example)) == []


def test_scenario_1050602_preserves_classifier_semantics() -> None:
    example = json.loads(
        (CONTRACTS_DIR / "examples" / "scenario-1050602.json").read_text(encoding="utf-8")
    )
    truth = example["groundTruth"]

    assert truth["classifierCode"] == "1050602"
    assert truth["incidentType"] == "задымление: мусоропровод"
    assert truth["ekp35IncidentType"] == "пожар: мусоропровод"
    assert truth["responseScenarioCode"] == "1_9"
    assert truth["mainService"]["id"] == "MCHS"
    assert truth["requiredServices"][0]["reasons"][0]["ruleId"].startswith("classifier.")


def test_operator_input_rejects_client_supplied_routing_result() -> None:
    schema = json.loads((CONTRACTS_DIR / "scenario.schema.json").read_text(encoding="utf-8"))
    example = json.loads(
        (CONTRACTS_DIR / "examples" / "scenario-1050602.json").read_text(encoding="utf-8")
    )
    invalid = deepcopy(example)
    invalid["groundTruth"]["expectedInput"]["incidentType"] = "подменённый тип"

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    messages = [error.message for error in validator.iter_errors(invalid)]

    assert any("incidentType" in message for message in messages)
