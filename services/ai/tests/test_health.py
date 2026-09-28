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


def test_ready_allows_card_mode_without_real_speech(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_rejects_missing_models_when_real_speech_is_required(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "require_real_speech", True)
    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["speechAvailable"] is False
