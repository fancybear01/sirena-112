#!/usr/bin/env python3
"""Локальная проверка голосового потока без телефонии и без моделей.

Поднимает приложение в этом же процессе, создаёт голосовую AI-сессию,
прогоняет через WebSocket сгенерированный PCM и печатает обмен сообщениями.
Нужна, чтобы убедиться, что транспорт цел, до того как подключать Go Media.

Запуск из services/ai:

    .venv/bin/python scripts/smoke_voice.py

По умолчанию работают детерминированные подмены речи: транскрипт синтетический
и помечен как simulated. Чтобы прогнать с настоящими моделями, задайте
AI_STT=vosk, AI_STT_MODEL, AI_TTS=piper, AI_TTS_MODEL и добавьте --real.
"""

import argparse
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.voice import speech  # noqa: E402

SAMPLE_RATE = 16000
FRAME_BYTES = 640
GOLDEN_CODE = "1050602"

OPERATOR_LINES = (
    "Служба 112, здравствуйте, слушаю вас",
    "Назовите адрес происшествия",
    "Пострадавшие есть?",
)


def pcm_fixture(seconds: float = 0.5, frequency: int = 220) -> bytes:
    """Простой тон вместо записи: содержимое важно только настоящим моделям."""
    samples = int(SAMPLE_RATE * seconds)
    values = [
        int(12000 * math.sin(2 * math.pi * frequency * index / SAMPLE_RATE))
        for index in range(samples)
    ]
    return struct.pack("<%dh" % samples, *values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real",
        action="store_true",
        help="использовать модели из переменных окружения вместо подмен",
    )
    arguments = parser.parse_args()

    if not arguments.real:
        speech.use_pipeline(
            speech.SpeechPipeline(
                speech.ScriptedRecognizer(OPERATOR_LINES), speech.SilenceSynthesizer()
            )
        )

    client = TestClient(create_app())
    scenarios = client.post("/ai/scenarios/generate", json={"count": 4}).json()["scenarios"]
    scenario = next(s for s in scenarios if s["groundTruth"]["classifierCode"] == GOLDEN_CODE)

    created = client.post(
        "/ai/voice/sessions", json={"sessionId": "smoke-1", "scenario": scenario}
    )
    if created.status_code != 201:
        print("не удалось создать сессию:", created.status_code, created.text)
        return 1

    session = created.json()
    print("сценарий   :", scenario["groundTruth"]["incidentType"])
    print("речь       :", session["speech"], "| настоящая:", not session["speechSimulated"])
    if session.get("notice"):
        print("внимание   :", session["notice"])
    print("-" * 70)

    audio = pcm_fixture()
    url = "/internal/v1/voice/%s?sessionId=smoke-1" % session["aiSessionId"]

    with client.websocket_connect(url) as websocket:
        websocket.send_json(
            {
                "type": "stream.start",
                "audio": {
                    "encoding": "pcm_s16le",
                    "sampleRate": SAMPLE_RATE,
                    "channels": 1,
                    "frameDurationMs": 20,
                },
            }
        )

        for _ in OPERATOR_LINES:
            for offset in range(0, len(audio), FRAME_BYTES):
                websocket.send_bytes(audio[offset : offset + FRAME_BYTES])
            websocket.send_json({"type": "input.flush"})

            received = 0
            while True:
                frame = websocket.receive()
                if frame.get("bytes") is not None:
                    received += 1
                    continue
                message = json.loads(frame["text"])
                kind = message["type"]
                if kind == "transcript.final":
                    print("оператор   :", message["text"])
                elif kind == "response.started":
                    print("абонент    :", message["text"])
                elif kind == "error":
                    print("ошибка     :", message["code"], "-", message["message"])
                    break
                elif kind == "caller.state_changed":
                    print(
                        "            паника %.2f  доверие %.2f  терпение %.2f  звук %d кадров"
                        % (message["panic"], message["trust"], message["patience"], received)
                    )
                    print()
                    break

        websocket.send_json({"type": "stream.stop"})

    client.delete("/ai/voice/sessions/%s" % session["aiSessionId"])
    print("поток закрыт, сессия освобождена")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
