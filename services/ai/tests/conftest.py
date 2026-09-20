"""Общие фикстуры тестов.

Сценарии берутся из contracts/examples - тех же файлов, что использует Core.
Своих копий классификационных данных в тестах нет.
"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPOSITORY_ROOT / "contracts"

# Эталонный сценарий сквозного MVP: задымление мусоропровода в жилом доме.
GOLDEN_CODE = "1050602"


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="session")
def scenario_schema() -> Dict[str, Any]:
    """Схема сценария из contracts, единый источник истины для всей команды."""
    return json.loads((CONTRACTS_DIR / "scenario.schema.json").read_text(encoding="utf-8"))


@pytest.fixture()
def scenario(client: TestClient) -> Dict[str, Any]:
    """Эталонный сценарий 1050602 в том виде, в котором его отдаёт сервис."""
    response = client.post("/ai/scenarios/generate", json={"category": "FIRE", "count": 4})
    assert response.status_code == 200
    scenarios = response.json()["scenarios"]
    return next(s for s in scenarios if s["groundTruth"]["classifierCode"] == GOLDEN_CODE)


def perfect_card(scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Карточка обучающегося, полностью совпадающая с ожидаемым вводом."""
    return deepcopy(scenario["groundTruth"]["expectedInput"])


def core_calculation(scenario: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Расчёт Core, совпадающий с эталоном сценария.

    В жизни его считает Core по карточке обучающегося. В тестах мы подставляем
    ожидаемый результат, а отклонения задаём через overrides.
    """
    truth = scenario["groundTruth"]
    calculation = {
        "status": "RESOLVED",
        "classifierVersion": truth["classifierVersion"],
        "classifierCode": truth["classifierCode"],
        "incidentType": truth["incidentType"],
        "ekp35IncidentType": truth["ekp35IncidentType"],
        "responseScenarioCode": truth["responseScenarioCode"],
        "responseScenarioStatus": truth["responseScenarioStatus"],
        "mainServices": deepcopy(truth["mainServices"]),
        "services": deepcopy(truth["requiredServices"]),
    }
    calculation.update(overrides)
    return calculation
