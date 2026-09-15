def _request(scenario, utterance="Служба 112, назовите адрес происшествия"):
    return {
        "aiSessionId": "ai-test-1",
        "scenario": scenario,
        "history": [],
        "operatorUtterance": utterance,
    }


def test_respond_returns_contract_fields(client, scenario):
    response = client.post("/ai/dialogue/respond", json=_request(scenario))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"reply", "callerState", "revealedFacts", "hangUp", "meta"}
    assert isinstance(body["reply"], str) and body["reply"]
    assert body["hangUp"] is False


def test_caller_state_is_taken_from_scenario_profile(client, scenario):
    response = client.post("/ai/dialogue/respond", json=_request(scenario))

    state = response.json()["callerState"]
    assert state["panic"] == scenario["caller"]["panic"]
    assert state["trust"] == scenario["caller"]["trust"]
    assert state["revealedFacts"] == []


def test_caller_state_from_request_wins(client, scenario):
    payload = _request(scenario)
    payload["callerState"] = {
        "panic": 0.9,
        "trust": 0.1,
        "patience": 0.2,
        "revealedFacts": ["callerName"],
    }

    body = client.post("/ai/dialogue/respond", json=payload).json()

    assert body["callerState"]["panic"] == 0.9
    assert body["revealedFacts"] == ["callerName"]


def test_reply_does_not_invent_scenario_facts(client, scenario):
    """Заглушка не должна называть адрес или имя: их обязан выяснить оператор."""
    body = client.post("/ai/dialogue/respond", json=_request(scenario)).json()

    address = scenario["groundTruth"]["address"]
    caller_name = scenario["groundTruth"]["facts"]["callerName"]
    assert address not in body["reply"]
    assert caller_name not in body["reply"]


def test_respond_is_reproducible(client, scenario):
    payload = _request(scenario)

    first = client.post("/ai/dialogue/respond", json=payload)
    second = client.post("/ai/dialogue/respond", json=payload)

    assert first.json() == second.json()
