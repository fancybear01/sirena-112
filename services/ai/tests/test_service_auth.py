"""Сервисный токен: кого пускаем и как отказываем.

Проверка включается переменной AI_SERVICE_TOKEN. Отказ обязан быть понятным:
401 на HTTP и осмысленный код закрытия на голосовом потоке. Падение вместо
отказа - это способ уронить сервис одним запросом.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

TOKEN = "test-service-token"
GOLDEN_CODE = "1050602"


@pytest.fixture()
def guarded(monkeypatch) -> TestClient:
    monkeypatch.setenv("AI_SERVICE_TOKEN", TOKEN)
    with TestClient(create_app()) as client:
        yield client


def test_health_stays_open(guarded):
    """По /health проверяют живость контейнера, токена у healthcheck нет."""
    assert guarded.get("/health").status_code == 200


def test_ai_http_requires_service_token_when_configured(guarded):
    assert guarded.post("/ai/scenarios/generate", json={}).status_code == 401
    assert (
        guarded.post(
            "/ai/scenarios/generate",
            json={"category": "FIRE", "count": 1},
            headers={"Authorization": "Bearer " + TOKEN},
        ).status_code
        == 200
    )


def test_wrong_token_is_refused(guarded):
    response = guarded.post(
        "/ai/scenarios/generate",
        json={"category": "FIRE", "count": 1},
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


# Заголовки задаём байтами намеренно: по сети они и приходят байтами,
# а httpx не даёт положить не-ASCII в строку заголовка.
BROKEN_HEADERS = [
    "Bearer парол".encode("utf-8"),
    b"Bearer \x80\xff",
    "мусор".encode("utf-8"),
    b"",
    b"Bearer",
]


@pytest.mark.parametrize("header", BROKEN_HEADERS)
def test_broken_header_is_refused_not_crashed(guarded, header):
    """Кривой заголовок - это отказ, а не падение сервиса.

    hmac.compare_digest со строками бросает TypeError на не-ASCII символах,
    а Authorization приходит от клиента: туда можно положить что угодно.
    Раньше такой запрос отвечал 500, то есть сервис валился с одного
    обращения. Сравнение идёт по байтам именно поэтому.
    """
    response = guarded.post(
        "/ai/scenarios/generate",
        json={"category": "FIRE", "count": 1},
        headers={"Authorization": header},
    )

    assert response.status_code == 401


def test_without_configured_token_everything_is_open(monkeypatch):
    """Без переменной проверка выключена: в разработке она только мешает."""
    monkeypatch.delenv("AI_SERVICE_TOKEN", raising=False)
    with TestClient(create_app()) as client:
        response = client.post("/ai/scenarios/generate", json={"category": "FIRE", "count": 1})

    assert response.status_code == 200


# --- голосовой поток ----------------------------------------------------------


def voice_session(client: TestClient, session_id: str = "core-auth") -> str:
    scenarios = client.post(
        "/ai/scenarios/generate",
        json={"category": "FIRE", "count": 4},
        headers={"Authorization": "Bearer " + TOKEN},
    ).json()["scenarios"]
    scenario = next(s for s in scenarios if s["groundTruth"]["classifierCode"] == GOLDEN_CODE)
    created = client.post(
        "/ai/voice/sessions",
        json={"sessionId": session_id, "scenario": scenario},
        headers={"Authorization": "Bearer " + TOKEN},
    )
    assert created.status_code == 201
    return created.json()["aiSessionId"]


def test_voice_stream_requires_the_token(guarded):
    """Поток без токена закрывается, и Media должна это заметить."""
    ai_session_id = voice_session(guarded)
    url = "/internal/v1/voice/%s?sessionId=core-auth" % ai_session_id

    with pytest.raises(Exception):
        with guarded.websocket_connect(url):
            pass


def test_voice_stream_opens_with_the_token(guarded):
    ai_session_id = voice_session(guarded, "core-auth-ok")
    url = "/internal/v1/voice/%s?sessionId=core-auth-ok" % ai_session_id

    with guarded.websocket_connect(
        url, headers={"Authorization": "Bearer " + TOKEN}
    ) as websocket:
        websocket.send_json({"type": "stream.stop"})


def test_refusal_reason_goes_to_the_log(guarded, caplog):
    """Причина отказа обязана быть в логе.

    Соединение закрывается до рукопожатия, поэтому Media видит просто
    HTTP 403 и код закрытия до неё не доходит - ни 4401, ни 4404, ни 4409.
    Если причину не записать, на демонстрации разбираться будет нечем.
    """
    ai_session_id = voice_session(guarded, "core-auth-log")
    url = "/internal/v1/voice/%s?sessionId=core-auth-log" % ai_session_id

    with caplog.at_level("WARNING"):
        with pytest.raises(Exception):
            with guarded.websocket_connect(url):
                pass

    messages = [record.getMessage() for record in caplog.records]

    assert any("токен" in message for message in messages), (
        "в логе нет причины отказа: %s" % messages
    )
