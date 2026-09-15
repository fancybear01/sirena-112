"""Общие фикстуры тестов."""

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

# contracts лежит в корне репозитория, на три уровня выше services/ai/tests
CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="session")
def scenario_schema() -> Dict[str, Any]:
    """Схема сценария из contracts, единый источник истины для всей команды."""
    path = CONTRACTS_DIR / "scenario.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def scenario(client: TestClient) -> Dict[str, Any]:
    """Валидный сценарий, полученный из сервиса."""
    response = client.post("/ai/scenarios/generate", json={"count": 1, "seed": 1})
    assert response.status_code == 200
    return response.json()["scenarios"][0]
