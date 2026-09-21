"""Голосовой поток Media <-> AI.

Проверяется жизненный цикл по contracts/media-ai.md и то, что сервис
не выдаёт подмену за настоящее распознавание.

Речевые модели здесь не используются: вместо них детерминированные подмены,
поэтому тесты не требуют ни интернета, ни загрузки моделей.
"""

import json

import pytest

from app.voice import sessions, speech

# Полсекунды тишины: содержимое звука подмене распознавания безразлично.
SILENCE = b"\x00\x00" * 8000
FRAME = 640

START = {
    "type": "stream.start",
    "audio": {
        "encoding": "pcm_s16le",
        "sampleRate": 16000,
        "channels": 1,
        "frameDurationMs": 20,
    },
}


@pytest.fixture(autouse=True)
def scripted_speech():
    """Детерминированные подмены вместо моделей, и чистое хранилище сессий."""
    speech.use_pipeline(
        speech.SpeechPipeline(
            speech.ScriptedRecognizer(
                ("Служба 112, слушаю вас", "Назовите адрес происшествия")
            ),
            speech.SilenceSynthesizer(),
        )
    )
    sessions.store().clear()
    yield
    speech.use_pipeline(None)
    sessions.store().clear()


@pytest.fixture()
def voice_session(client, scenario):
    response = client.post(
        "/ai/voice/sessions", json={"sessionId": "core-1", "scenario": scenario}
    )
    assert response.status_code == 201
    return response.json()


def send_speech(websocket, chunks=SILENCE):
    for offset in range(0, len(chunks), FRAME):
        websocket.send_bytes(chunks[offset : offset + FRAME])
    websocket.send_json({"type": "input.flush"})


def collect(websocket, until, limit=200):
    """Читает кадры до сообщения нужного типа. Звук считает, но не хранит."""
    messages, audio_frames = [], 0
    for _ in range(limit):
        frame = websocket.receive()
        if frame.get("bytes") is not None:
            audio_frames += 1
            continue
        payload = json.loads(frame["text"])
        messages.append(payload)
        if payload["type"] == until:
            break
    return messages, audio_frames


# --- создание сессии ----------------------------------------------------------


def test_session_reports_speech_mode(voice_session):
    """Режим речи виден сразу, а не после первой реплики."""
    assert voice_session["aiSessionId"].startswith("ai-")
    assert voice_session["speech"] == "scripted+silence"
    assert voice_session["speechSimulated"] is True
    assert "подмен" in voice_session["notice"]


def test_session_can_be_released(client, voice_session):
    assert client.delete("/ai/voice/sessions/%s" % voice_session["aiSessionId"]).status_code == 204
    assert client.delete("/ai/voice/sessions/%s" % voice_session["aiSessionId"]).status_code == 404


def test_session_limit_is_enforced(client, scenario):
    sessions.store()._limit = 1  # noqa: SLF001 - предел проверяем напрямую
    try:
        first = client.post("/ai/voice/sessions", json={"sessionId": "a", "scenario": scenario})
        second = client.post("/ai/voice/sessions", json={"sessionId": "b", "scenario": scenario})

        assert first.status_code == 201
        assert second.status_code == 503
    finally:
        sessions.store()._limit = sessions.MAX_SESSIONS  # noqa: SLF001


# --- открытие потока ----------------------------------------------------------


def test_unknown_session_is_rejected(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/internal/v1/voice/ai-unknown?sessionId=core-1"):
            pass


def test_mismatched_session_id_is_rejected(client, voice_session):
    """Пара идентификаторов должна совпасть: это требование контракта."""
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/internal/v1/voice/%s?sessionId=чужая" % voice_session["aiSessionId"]
        ):
            pass


def test_second_connection_to_same_session_is_rejected(client, voice_session):
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]
    with client.websocket_connect(url):
        with pytest.raises(Exception):
            with client.websocket_connect(url):
                pass


# --- жизненный цикл -----------------------------------------------------------


def test_full_lifecycle_returns_transcript_reply_and_audio(client, voice_session):
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
        send_speech(websocket)
        messages, audio_frames = collect(websocket, until="caller.state_changed")
        websocket.send_json({"type": "stream.stop"})

    kinds = [message["type"] for message in messages]
    assert kinds == [
        "transcript.final",
        "response.started",
        "response.completed",
        "caller.state_changed",
    ]
    assert messages[0]["text"] == "Служба 112, слушаю вас"
    assert messages[0]["simulated"] is True
    assert messages[1]["text"]
    assert audio_frames > 0


def test_two_consecutive_replies_keep_caller_state(client, voice_session):
    """Состояние абонента живёт между репликами: адрес называется один раз."""
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
        send_speech(websocket)
        first, _ = collect(websocket, until="caller.state_changed")
        send_speech(websocket)
        second, _ = collect(websocket, until="caller.state_changed")
        websocket.send_json({"type": "stream.stop"})

    assert first[0]["text"] == "Служба 112, слушаю вас"
    assert second[0]["text"] == "Назовите адрес происшествия"
    # Второй вопрос про адрес - значит адрес и раскрылся.
    assert "address" in second[-1]["revealedFacts"]
    # Отметки времени идут подряд: вторая реплика начинается там, где кончилась первая.
    assert second[0]["startedAtMs"] == first[0]["endedAtMs"]


def test_timestamps_are_measured_by_audio_not_by_clock(client, voice_session):
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
        send_speech(websocket)
        messages, _ = collect(websocket, until="transcript.final")
        websocket.send_json({"type": "stream.stop"})

    assert messages[0]["startedAtMs"] == 0
    assert messages[0]["endedAtMs"] == 500


def test_response_is_reproducible(client, scenario):
    """Один и тот же разговор даёт тот же ответ и то же число кадров."""

    def run():
        speech.use_pipeline(
            speech.SpeechPipeline(
                speech.ScriptedRecognizer(("Назовите адрес происшествия",)),
                speech.SilenceSynthesizer(),
            )
        )
        created = client.post(
            "/ai/voice/sessions", json={"sessionId": "core-2", "scenario": scenario}
        ).json()
        url = "/internal/v1/voice/%s?sessionId=core-2" % created["aiSessionId"]
        with client.websocket_connect(url) as websocket:
            websocket.send_json(START)
            send_speech(websocket)
            messages, audio_frames = collect(websocket, until="caller.state_changed")
            websocket.send_json({"type": "stream.stop"})
        return [{k: v for k, v in m.items() if k != "sequence"} for m in messages], audio_frames

    assert run() == run()


# --- управление потоком -------------------------------------------------------


def test_cancel_stops_pending_reply(client, voice_session):
    """Перебивание снимает недоигранный ответ.

    Штатное завершение реплики приходит первым, поэтому ищем именно
    сообщение с пометкой отмены.
    """
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]
    cancelled = False

    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
        send_speech(websocket)
        websocket.send_json({"type": "response.cancel"})
        for _ in range(200):
            frame = websocket.receive()
            if frame.get("bytes") is not None:
                continue
            payload = json.loads(frame["text"])
            if payload["type"] == "response.completed" and payload.get("cancelled"):
                cancelled = True
                break
        websocket.send_json({"type": "stream.stop"})

    assert cancelled


def test_audio_before_stream_start_is_an_error(client, voice_session):
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_bytes(SILENCE[:FRAME])
        messages, _ = collect(websocket, until="error")

    assert messages[0]["code"] == "stream.not_started"


def test_unsupported_audio_format_is_rejected(client, voice_session):
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json({"type": "stream.start", "audio": {"encoding": "opus", "channels": 2}})
        messages, _ = collect(websocket, until="error")

    assert messages[0]["code"] == "audio.unsupported"


def test_flush_without_audio_is_an_error(client, voice_session):
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
        websocket.send_json({"type": "input.flush"})
        messages, _ = collect(websocket, until="error")

    assert messages[0]["code"] == "input.empty"


def test_unknown_message_type_is_reported(client, voice_session):
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
        websocket.send_json({"type": "чего-то такого"})
        messages, _ = collect(websocket, until="error")

    assert messages[0]["code"] == "message.unknown"


def test_session_is_released_after_disconnect(client, voice_session):
    """После обрыва сессию можно занять снова."""
    url = "/internal/v1/voice/%s?sessionId=core-1" % voice_session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)


# --- режим без моделей --------------------------------------------------------


def test_without_models_transcription_is_refused_not_faked(client, scenario):
    """Главное требование: заглушка не выдаётся за распознанную речь."""
    speech.use_pipeline(
        speech.SpeechPipeline(speech.UnavailableRecognizer(), speech.UnavailableSynthesizer())
    )
    created = client.post(
        "/ai/voice/sessions", json={"sessionId": "core-3", "scenario": scenario}
    ).json()

    assert created["speechAvailable"] is False
    assert "не настроены" in created["notice"]

    url = "/internal/v1/voice/%s?sessionId=core-3" % created["aiSessionId"]
    with client.websocket_connect(url) as websocket:
        websocket.send_json(START)
        send_speech(websocket)
        messages, audio_frames = collect(websocket, until="error")

    assert messages[0]["code"] == "speech.unavailable"
    assert "AI_STT" in messages[0]["message"]
    assert audio_frames == 0
    assert all(message["type"] != "transcript.final" for message in messages)
