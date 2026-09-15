def test_missing_required_field_names_the_field(client):
    response = client.post("/ai/dialogue/respond", json={"aiSessionId": "ai-1"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["path"] == "/ai/dialogue/respond"
    fields = [item["field"] for item in body["details"]]
    assert "scenario" in fields
    assert "operatorUtterance" in fields


def test_unknown_field_is_rejected(client):
    response = client.post(
        "/ai/scenarios/generate",
        json={"count": 1, "unexpectedField": "value"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_out_of_range_value_is_rejected(client):
    response = client.post("/ai/scenarios/generate", json={"count": 0})

    assert response.status_code == 422
    assert [item["field"] for item in response.json()["details"]] == ["count"]


def test_error_keeps_request_id(client):
    response = client.post(
        "/ai/scenarios/generate",
        json={"count": 0},
        headers={"X-Request-ID": "req-err"},
    )

    assert response.json()["requestId"] == "req-err"


def test_unknown_route_returns_not_found(client):
    response = client.get("/ai/unknown")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
