from jsonschema import Draft202012Validator


def test_generate_returns_requested_count(client):
    response = client.post(
        "/ai/scenarios/generate",
        json={"category": "FIRE", "difficulty": "BASIC", "count": 2, "seed": 7},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["scenarios"]) == 2
    assert body["meta"]["deterministic"] is True


def test_generate_is_reproducible(client):
    payload = {"category": "ACCIDENT", "difficulty": "ADVANCED", "count": 3, "seed": 99}

    first = client.post("/ai/scenarios/generate", json=payload)
    second = client.post("/ai/scenarios/generate", json=payload)

    assert first.json() == second.json()


def test_different_seed_gives_different_ids(client):
    base = {"count": 1, "difficulty": "BASIC"}

    first = client.post("/ai/scenarios/generate", json=dict(base, seed=1)).json()
    second = client.post("/ai/scenarios/generate", json=dict(base, seed=2)).json()

    assert first["scenarios"][0]["id"] != second["scenarios"][0]["id"]


def test_generated_scenario_matches_contract(client, scenario_schema):
    """Сценарий обязан проходить contracts/scenario.schema.json без правок."""
    response = client.post("/ai/scenarios/generate", json={"count": 3, "seed": 5})
    validator = Draft202012Validator(scenario_schema)

    for item in response.json()["scenarios"]:
        errors = sorted(validator.iter_errors(item), key=lambda error: error.path)
        assert errors == [], [error.message for error in errors]


def test_requested_time_limit_is_applied(client):
    response = client.post("/ai/scenarios/generate", json={"count": 1, "timeLimitSeconds": 45})

    assert response.json()["scenarios"][0]["timeLimitSeconds"] == 45
