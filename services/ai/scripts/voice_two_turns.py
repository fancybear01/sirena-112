#!/usr/bin/env python3
"""Двухходовой разговор с настоящими моделями на человеческой речи.

Проверка по задаче #73. От media_client.py отличается тем, что подмены речи
здесь запрещены: если модели не подключены, скрипт не делает вид, что всё
хорошо, а печатает блокер и возвращает ненулевой код.

Подаёт две записанные человеческие реплики в работающий сервис, сохраняет
ответы абонента в wav - чтобы их можно было послушать и убедиться, что звук
пригоден для проигрывания в RTP.

Запуск:

    AI_STT=vosk AI_STT_MODEL=<path> AI_TTS=piper AI_TTS_MODEL=<path> \\
      .venv/bin/python -m uvicorn app.main:app --port 8090

    .venv/bin/python scripts/voice_two_turns.py --input <каталог с wav>

Код возврата 0 - живой голос подтверждён, 1 - есть блокер.
"""

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path
from typing import List, Tuple

import httpx
import websockets

FRAME_BYTES = 640
SAMPLE_RATE = 16000
GOLDEN_CODE = "1050602"
DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "voice"
DEFAULT_OUTPUT = Path("/tmp/voice-two-turns")

STREAM_START = {
    "type": "stream.start",
    "audio": {
        "encoding": "pcm_s16le",
        "sampleRate": SAMPLE_RATE,
        "channels": 1,
        "frameDurationMs": 20,
    },
}


def read_pcm(path: Path) -> Tuple[bytes, float]:
    with wave.open(str(path), "rb") as reader:
        if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) != (
            1,
            2,
            SAMPLE_RATE,
        ):
            raise SystemExit("%s не в формате PCM16 mono 16 кГц" % path.name)
        frames = reader.getnframes()
        return reader.readframes(frames), frames / SAMPLE_RATE


def write_pcm(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm)


async def one_turn(connection, audio: bytes) -> Tuple[List[dict], bytes, float]:
    """Отдаёт одну реплику и собирает ответ целиком."""
    started = time.perf_counter()
    for offset in range(0, len(audio), FRAME_BYTES):
        await connection.send(audio[offset : offset + FRAME_BYTES])
    await connection.send(json.dumps({"type": "input.flush"}))

    messages: List[dict] = []
    reply = bytearray()
    while True:
        frame = await asyncio.wait_for(connection.recv(), timeout=60.0)
        if isinstance(frame, (bytes, bytearray)):
            reply.extend(frame)
            continue
        payload = json.loads(frame)
        messages.append(payload)
        if payload["type"] in ("caller.state_changed", "error"):
            return messages, bytes(reply), time.perf_counter() - started


async def run(base_url: str, input_dir: Path, output_dir: Path) -> int:
    blockers: List[str] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as http:
        try:
            health = (await http.get("/health")).json()
        except Exception as error:  # noqa: BLE001
            print("сервис не отвечает на %s: %s" % (base_url, error))
            return 1

        print("речь: %s | доступна: %s | подмена: %s"
              % (health["speech"], health["speechAvailable"], health["speechSimulated"]))

        if not health["speechAvailable"] or health["speechSimulated"]:
            print("\nБЛОКЕР: настоящие модели не подключены.")
            print("Задайте AI_STT/AI_STT_MODEL и AI_TTS/AI_TTS_MODEL и перезапустите сервис.")
            print("Подменами этот отчёт подтверждать нельзя: см. docs/voice-readiness.md")
            return 1

        scenarios = (await http.post("/ai/scenarios/generate", json={"count": 4})).json()["scenarios"]
        scenario = next(s for s in scenarios if s["groundTruth"]["classifierCode"] == GOLDEN_CODE)
        session = (
            await http.post(
                "/ai/voice/sessions", json={"sessionId": "two-turns", "scenario": scenario}
            )
        ).json()

    recordings = sorted(input_dir.glob("*.wav"))[:2]
    if len(recordings) < 2:
        print("в %s меньше двух записей" % input_dir)
        return 1

    print("сценарий: %s (%s)" % (scenario["groundTruth"]["incidentType"], GOLDEN_CODE))
    print("записи  : %s" % ", ".join(r.name for r in recordings))
    print("=" * 76)

    ws_url = "%s/internal/v1/voice/%s?sessionId=two-turns" % (
        base_url.replace("http://", "ws://"),
        session["aiSessionId"],
    )

    transcripts: List[str] = []
    replies: List[str] = []
    revealed: List[List[str]] = []

    async with websockets.connect(ws_url, proxy=None) as connection:
        await connection.send(json.dumps(STREAM_START))

        for number, recording in enumerate(recordings, 1):
            audio, seconds = read_pcm(recording)
            messages, reply_pcm, elapsed = await one_turn(connection, audio)

            kinds = [m["type"] for m in messages]
            if "error" in kinds:
                problem = next(m for m in messages if m["type"] == "error")
                blockers.append("ход %d: %s - %s" % (number, problem["code"], problem["message"]))
                print("ход %d: ОШИБКА %s" % (number, problem["code"]))
                continue

            transcript = next(m for m in messages if m["type"] == "transcript.final")
            started = next(m for m in messages if m["type"] == "response.started")
            completed = next(m for m in messages if m["type"] == "response.completed")
            state = next(m for m in messages if m["type"] == "caller.state_changed")

            transcripts.append(transcript["text"])
            replies.append(started["text"])
            revealed.append(state["revealedFacts"])

            out = output_dir / ("reply-%d.wav" % number)
            write_pcm(out, reply_pcm)

            print("ход %d: %s (%.2f с речи)" % (number, recording.name, seconds))
            print("   распознано : %s" % transcript["text"])
            print("   simulated  : %s" % transcript["simulated"])
            print("   ответ      : %s" % started["text"])
            print("   звук ответа: %d байт = %.2f с, сохранён в %s"
                  % (len(reply_pcm), len(reply_pcm) / 2 / SAMPLE_RATE, out))
            print("   обработка  : %.2f с от конца реплики до полного ответа" % elapsed)
            print("   состояние  : паника %.2f, доверие %.2f, терпение %.2f"
                  % (state["panic"], state["trust"], state["patience"]))
            print("   раскрыто   : %s" % (", ".join(state["revealedFacts"]) or "-"))
            print()

            if transcript["simulated"]:
                blockers.append("ход %d: транскрипт помечен simulated" % number)
            if not transcript["text"]:
                blockers.append("ход %d: пустой транскрипт" % number)
            if completed["durationMs"] <= 0:
                blockers.append("ход %d: ответ без звука" % number)

        await connection.send(json.dumps({"type": "stream.stop"}))

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        await http.delete("/ai/voice/sessions/%s" % session["aiSessionId"])

    # Состояние обязано накапливаться: второй ответ знает про первый.
    if len(revealed) == 2 and not set(revealed[0]) < set(revealed[1]):
        blockers.append(
            "состояние не накопилось между ходами: %s -> %s" % (revealed[0], revealed[1])
        )
    if len(replies) == 2 and replies[0] == replies[1]:
        blockers.append("абонент ответил одинаково на разные реплики")

    print("=" * 76)
    if blockers:
        print("БЛОКЕРЫ:")
        for blocker in blockers:
            print("  -", blocker)
        return 1

    print("живой голосовой AI подтверждён: два настоящих транскрипта, разные ответы,")
    print("состояние копится между ходами, звук сохранён и пригоден для проигрывания")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="каталог с двумя wav: PCM16 mono 16 кГц")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="куда сохранить ответы абонента")
    arguments = parser.parse_args()
    return asyncio.run(run(arguments.base_url, arguments.input, arguments.output))


if __name__ == "__main__":
    sys.exit(main())
