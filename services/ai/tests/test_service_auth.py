from fastapi.testclient import TestClient

from app.main import create_app


def test_ai_http_requires_service_token_when_configured(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test-service-token")
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/ai/scenarios/generate", json={}).status_code == 401
        assert client.post(
            "/ai/scenarios/generate",
            json={"category": "FIRE", "count": 1},
            headers={"Authorization": "Bearer test-service-token"},
        ).status_code == 200
