"""Проверка главного требования задачи: у AI нет своей копии каталога.

Раньше сервис хранил собственный список сценариев с руками выписанными
службами. Core считал маршрутизацию по классификатору, AI сверял с копией -
и расхождение было вопросом времени. Эти тесты следят, чтобы копия
не завелась снова.
"""

import re
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Названия и идентификаторы служб не имеют права быть в коде: они приходят
# из каталога и из расчёта Core.
SERVICE_MARKERS = (
    "Служба 10",
    "МЧС",
    "СМП",
    "МОСБЕЗ",
    "ЦОДД",
    "Мослифт",
    "MCHS",
    "AMBULANCE",
    "POLICE",
)

# Коды классификатора в коде тоже недопустимы: сценарии приходят файлами.
CLASSIFIER_CODE = re.compile(r"\b\d{6,9}\b")

SOURCES = sorted(APP_DIR.rglob("*.py"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_has_no_service_names(path):
    text = path.read_text(encoding="utf-8")

    found = [marker for marker in SERVICE_MARKERS if marker in text]
    assert found == [], "в {name} найдены названия служб: {found}".format(
        name=path.name, found=found
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_has_no_classifier_codes(path):
    """Коды вида 1050602 должны приходить из каталога, а не лежать в коде."""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        # Ограничения длины полей и регулярные выражения к каталогу
        # отношения не имеют.
        if CLASSIFIER_CODE.search(line) and "max_length" not in line and "pattern" not in line
    ]

    assert lines == [], "в {name} найдены коды классификатора: {lines}".format(
        name=path.name, lines=lines
    )


def test_services_come_only_from_scenario_and_calculation(client, scenario):
    """Службы в отчёте берутся из эталона, а не откуда-то ещё."""
    from tests.conftest import core_calculation, perfect_card

    response = client.post(
        "/ai/sessions/score",
        json={
            "sessionId": "s",
            "scenario": scenario,
            "submittedCard": perfect_card(scenario),
            "calculation": core_calculation(scenario, services=[]),
        },
    )

    message = next(
        item["message"] for item in response.json()["errors"] if "SERVICES" in item["code"]
    )
    expected_names = {s["displayName"] for s in scenario["groundTruth"]["requiredServices"]}
    assert any(name in message for name in expected_names)
