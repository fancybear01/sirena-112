def test_health_reports_service_identity(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "sirena-ai"
    assert body["engine"] == "mock"


def test_request_id_is_returned_back(client):
    response = client.get("/health", headers={"X-Request-ID": "req-42"})

    assert response.headers["X-Request-ID"] == "req-42"


def test_request_id_is_generated_when_absent(client):
    response = client.get("/health")

    assert response.headers.get("X-Request-ID")


def test_health_reports_speech_mode(client):
    """Режим речи виден в health: на демо это первое, что проверяют."""
    body = client.get("/health").json()

    assert "speech" in body
    assert isinstance(body["speechAvailable"], bool)
    assert isinstance(body["speechSimulated"], bool)
