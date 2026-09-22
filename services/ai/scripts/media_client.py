#!/usr/bin/env python3
"""Клиент, имитирующий Go Media: проверяет голосовой поток снаружи.

В отличие от smoke_voice.py этот скрипт не поднимает приложение внутри себя,
а стучится в запущенный сервис по сети - ровно так, как это будет делать
Go Media. Поэтому он годится и как проверка после изменений, и как образец
протокола для задачи #53.

Что делает: создаёт голосовую сессию, открывает WebSocket, отправляет два
отдельных фрагмента речи с input.flush между ними, проверяет имена и порядок
кадров по contracts/media-ai.md, пробует response.cancel и штатно закрывает
поток.

Запуск (сервис должен быть уже поднят на 8090):

    .venv/bin/python -m uvicorn app.main:app --port 8090   # в другом терминале
    .venv/bin/python scripts/media_client.py

С настоящими моделями:

    AI_STT=vosk AI_STT_MODEL=... AI_TTS=piper AI_TTS_MODEL=... \\
      .venv/bin/python -m uvicorn app.main:app --port 8090
    .venv/bin/python scripts/media_client.py --expect-real

Код возврата 0 - протокол соблюдён, 1 - есть расхождения.
"""

import argparse
import asyncio
import json
import sys
import wave
from pathlib import Path
from typing import List, Tuple

import httpx
import websockets

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "voice"
FRAME_BYTES = 640
GOLDEN_CODE = "1050602"

# Порядок кадров после input.flush по contracts/media-ai.md.
EXPECTED_AFTER_FLUSH = [
    "transcript.final",
    "response.started",
    "response.completed",
    "caller.state_changed",
]

STREAM_START = {
    "type": "stream.start",
    "audio": {
        "encoding": "pcm_s16le",
        "sampleRate": 16000,
        "channels": 1,
        "frameDurationMs": 20,
    },
}


class Report:
    """Собирает расхождения, чтобы показать их все разом, а не по одному."""

    def __init__(self) -> None:
        self.problems: List[str] = []

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            self.problems.append(message)

    def ok(self) -> bool:
        return not self.problems


def load_fixture(name: str) -> bytes:
    with wave.open(str(FIXTURES / name), "rb") as reader:
        if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) != (1, 2, 16000):
            raise SystemExit("Фикстура %s не в формате PCM16 mono 16 кГц" % name)
        return reader.readframes(reader.getnframes())


async def send_fragment(connection, audio: bytes) -> None:
    """Отправляет речь кадрами по 20 мс и просит распознать её."""
    for offset in range(0, len(audio), FRAME_BYTES):
        await connection.send(audio[offset : offset + FRAME_BYTES])
    await connection.send(json.dumps({"type": "input.flush"}))


async def collect_turn(connection, timeout: float = 30.0) -> Tuple[List[dict], int]:
    """Читает кадры до конца реплики абонента.

    Возвращает управляющие сообщения и число полученных аудиокадров.
    """
    messages: List[dict] = []
    audio_frames = 0

    while True:
        frame = await asyncio.wait_for(connection.recv(), timeout=timeout)
        if isinstance(frame, (bytes, bytearray)):
            audio_frames += 1
            continue
        payload = json.loads(frame)
        messages.append(payload)
        if payload["type"] in ("caller.state_changed", "error"):
            return messages, audio_frames


def describe_turn(messages: List[dict], audio_frames: int) -> None:
    for message in messages:
        kind = message["type"]
        if kind == "transcript.final":
            print("   оператор : %s" % message["text"])
            print("              simulated=%s, %d-%d мс"
                  % (message["simulated"], message["startedAtMs"], message["endedAtMs"]))
        elif kind == "response.started":
            print("   абонент  : %s" % message["text"])
        elif kind == "response.completed":
            print("   ответ    : %d кадров, %d мс" % (audio_frames, message["durationMs"]))
        elif kind == "caller.state_changed":
            print("   состояние: паника %.2f, доверие %.2f, терпение %.2f, раскрыто %s"
                  % (message["panic"], message["trust"], message["patience"],
                     ", ".join(message["revealedFacts"]) or "-"))
        elif kind == "error":
            print("   ОШИБКА   : %s - %s" % (message["code"], message["message"]))


def check_turn(report: Report, number: int, messages: List[dict], audio_frames: int,
               expect_real: bool) -> None:
    kinds = [message["type"] for message in messages]

    if kinds == ["error"]:
        code = messages[0]["code"]
        if code == "speech.unavailable" and not expect_real:
            print("   (режим без моделей: транскрипта нет, это ожидаемо)")
            return
        report.check(False, "ход %d: поток ответил ошибкой %s" % (number, code))
        return

    report.check(
        kinds == EXPECTED_AFTER_FLUSH,
        "ход %d: порядок кадров %s, ожидался %s" % (number, kinds, EXPECTED_AFTER_FLUSH),
    )
    report.check(audio_frames > 0, "ход %d: не пришло ни одного аудиокадра" % number)

    transcript = next((m for m in messages if m["type"] == "transcript.final"), None)
    if transcript is not None:
        report.check(bool(transcript["text"]), "ход %d: пустой транскрипт" % number)
        if expect_real:
            report.check(
                transcript["simulated"] is False,
                "ход %d: ожидалась настоящая речь, а транскрипт помечен simulated" % number,
            )


async def run(base_url: str, expect_real: bool) -> int:
    report = Report()

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as http:
        health = await http.get("/health")
        if health.status_code != 200:
            print("сервис не отвечает на %s/health" % base_url)
            return 1

        scenarios = (await http.post("/ai/scenarios/generate", json={"count": 4})).json()["scenarios"]
        scenario = next(s for s in scenarios if s["groundTruth"]["classifierCode"] == GOLDEN_CODE)

        created = await http.post(
            "/ai/voice/sessions", json={"sessionId": "media-smoke", "scenario": scenario}
        )
        if created.status_code != 201:
            print("сессия не создалась: %s %s" % (created.status_code, created.text))
            return 1
        session = created.json()

    print("сценарий : %s (%s)" % (scenario["groundTruth"]["incidentType"], GOLDEN_CODE))
    print("речь     : %s | настоящая: %s" % (session["speech"], not session["speechSimulated"]))
    if session.get("notice"):
        print("внимание : %s" % session["notice"])
    print("-" * 74)

    report.check(
        session["sessionId"] == "media-smoke",
        "сервис вернул чужой sessionId: %s" % session["sessionId"],
    )
    if expect_real:
        report.check(
            session["speechSimulated"] is False,
            "ожидались настоящие модели, а сервис работает на подменах",
        )

    ws_url = "%s/internal/v1/voice/%s?sessionId=media-smoke" % (
        base_url.replace("http://", "ws://").replace("https://", "wss://"),
        session["aiSessionId"],
    )

    # proxy=None: локальное соединение не должно уходить в прокси из окружения.
    async with websockets.connect(ws_url, proxy=None) as connection:
        await connection.send(json.dumps(STREAM_START))

        for number, name in enumerate(("operator-01-address.wav", "operator-02-victims.wav"), 1):
            print("ход %d: %s" % (number, name))
            await send_fragment(connection, load_fixture(name))
            messages, audio_frames = await collect_turn(connection)
            describe_turn(messages, audio_frames)
            check_turn(report, number, messages, audio_frames, expect_real)
            print()

        # Перебивание: недоигранный ответ должен сниматься.
        print("проверка перебивания")
        await send_fragment(connection, load_fixture("operator-01-address.wav"))
        await connection.send(json.dumps({"type": "response.cancel"}))
        cancelled = await wait_for_cancelled(connection)
        report.check(cancelled, "после response.cancel не пришло response.completed с cancelled")
        print("   %s\n" % ("ответ снят" if cancelled else "ОТМЕНА НЕ ПОДТВЕРЖДЕНА"))

        await connection.send(json.dumps({"type": "stream.stop"}))

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        released = await http.delete("/ai/voice/sessions/%s" % session["aiSessionId"])
        report.check(
            released.status_code in (204, 404),
            "сессия не освободилась: %s" % released.status_code,
        )

    if report.ok():
        print("протокол соблюдён, два хода прошли, поток закрыт штатно")
        return 0

    print("РАСХОЖДЕНИЯ С КОНТРАКТОМ:")
    for problem in report.problems:
        print("  -", problem)
    return 1


async def wait_for_cancelled(connection, timeout: float = 30.0) -> bool:
    """Ждёт подтверждения отмены, пропуская всё остальное."""
    try:
        while True:
            frame = await asyncio.wait_for(connection.recv(), timeout=timeout)
            if isinstance(frame, (bytes, bytearray)):
                continue
            payload = json.loads(frame)
            if payload["type"] == "response.completed" and payload.get("cancelled"):
                return True
            if payload["type"] == "error" and payload["code"] == "speech.unavailable":
                # Без моделей реплики нет, снимать нечего.
                return True
    except asyncio.TimeoutError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument(
        "--expect-real",
        action="store_true",
        help="требовать настоящие модели: транскрипт с simulated=false",
    )
    arguments = parser.parse_args()
    return asyncio.run(run(arguments.base_url, arguments.expect_real))


if __name__ == "__main__":
    sys.exit(main())
