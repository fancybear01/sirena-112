#!/usr/bin/env python3
"""Нагрузка и задержки AI: HTTP, голосовые сессии, поведение за пределом.

Часть задачи #91. Меряется только AI. Задержка голосового тракта в телефоне
здесь не измеряется и подменять ей VoIP one-way latency нельзя: до трубки
звук идёт через Media и Asterisk, а они тут вообще не участвуют.

Что делает:

1. Прогрев. Первые обращения всегда медленнее: модели дочитывают веса,
   Python догревает импорты. Без прогрева числа получаются мусорные, на этом
   уже трижды спотыкались в замерах #13.
2. Отдельно печатает холодную задержку - она нужна честности ради.
3. HTTP: p95 отклика на генерацию сценариев и на оценку занятия.
4. Голос: 5, 10, 20 одновременных сессий, задержка полного хода реплики.
5. Предел: что происходит, когда сессий просят больше, чем разрешено.

Запуск (сервис должен быть поднят, желательно с настоящими моделями):

    .venv/bin/python scripts/ai_load.py
    .venv/bin/python scripts/ai_load.py --sessions 5,10,20 --turns 2 --pid <pid>

Код возврата 0 - все замеры сняты, 1 - что-то не сняли, причина напечатана.
"""

import argparse
import asyncio
import contextlib
import json
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
import websockets

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "voice"
FRAME_BYTES = 640
SAMPLE_RATE = 16000

# Норматив ТЗ на отклик интерфейса и API.
API_BUDGET_SECONDS = 2.0

# Бюджет паузы в разговоре: столько абонент может молчать, прежде чем это
# станет заметно. Обоснование в docs/ai-benchmark.md.
TURN_BUDGET_SECONDS = 1.2

STREAM_START = {
    "type": "stream.start",
    "audio": {
        "encoding": "pcm_s16le",
        "sampleRate": SAMPLE_RATE,
        "channels": 1,
        "frameDurationMs": 20,
    },
}


def percentile(values: List[float], share: float) -> float:
    """Процентиль по ближайшему рангу. Numpy ради трёх чисел не нужен."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(share * len(ordered) + 0.5)) - 1))
    return ordered[index]


def load_fixtures() -> List[bytes]:
    """Речь оператора из репозитория: одни и те же файлы у всех."""
    recordings = []
    for path in sorted(FIXTURES.glob("*.wav")):
        with wave.open(str(path), "rb") as reader:
            if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) != (
                1,
                2,
                SAMPLE_RATE,
            ):
                raise SystemExit("%s не в формате PCM16 mono 16 кГц" % path.name)
            recordings.append(reader.readframes(reader.getnframes()))
    if not recordings:
        raise SystemExit("в %s нет записей" % FIXTURES)
    return recordings


def read_process(pid: int) -> Optional[Tuple[float, float]]:
    """Память в мегабайтах и потраченное процессорное время в секундах."""
    try:
        output = subprocess.run(
            ["ps", "-o", "rss=,cputime=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.split()
        memory = float(output[0]) / 1024
        parts = [float(part) for part in output[1].replace("-", ":").split(":")]
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return memory, seconds
    except Exception:  # noqa: BLE001 - замер не должен ронять прогон
        return None


class Usage:
    """Расход ресурсов за отрезок времени.

    Процессор считается по приросту процессорного времени, а не через
    ps pcpu: тот даёт среднее за всю жизнь процесса, и под конец прогона
    показывает погоду на Марсе. Память берётся пиковая из подглядываний.
    """

    def __init__(self, pid: Optional[int]) -> None:
        self.pid = pid
        self.peak_memory = 0.0
        self.cpu_share = 0.0
        self._cpu_at_start = 0.0
        self._wall_at_start = 0.0
        self._running = False

    async def watch(self) -> None:
        """Подглядывает за процессом, пока прогон не закончится."""
        if self.pid is None:
            return
        first = read_process(self.pid)
        if first is None:
            self.pid = None
            return
        self.peak_memory, self._cpu_at_start = first
        self._wall_at_start = time.perf_counter()
        self._running = True
        while self._running:
            await asyncio.sleep(0.2)
            current = read_process(self.pid)
            if current is not None:
                self.peak_memory = max(self.peak_memory, current[0])

    def stop(self) -> None:
        self._running = False
        if self.pid is None:
            return
        current = read_process(self.pid)
        wall = time.perf_counter() - self._wall_at_start
        if current is not None and wall > 0:
            self.cpu_share = (current[1] - self._cpu_at_start) / wall * 100

    def describe(self) -> str:
        if self.pid is None:
            return "-"
        return "%.0f МБ / %.0f%%" % (self.peak_memory, self.cpu_share)


class Load:
    """Общий контекст прогона: адрес сервиса, токен, фикстуры."""

    def __init__(self, base_url: str, token: Optional[str], turns: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": "Bearer " + token} if token else {}
        self.turns = turns
        self.recordings = load_fixtures()
        self.problems: List[str] = []
        self._scenario: Optional[dict] = None

    def http(self, timeout: float = 60.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=self.headers)

    async def scenario(self) -> dict:
        if self._scenario is None:
            async with self.http() as http:
                response = await http.post("/ai/scenarios/generate", json={"count": 4})
                response.raise_for_status()
                self._scenario = response.json()["scenarios"][0]
        return self._scenario

    def ws_url(self, ai_session_id: str, session_id: str) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[1]
        return "%s://%s/internal/v1/voice/%s?sessionId=%s" % (
            scheme,
            host,
            ai_session_id,
            session_id,
        )

    async def open_session(self, session_id: str) -> Optional[str]:
        scenario = await self.scenario()
        async with self.http() as http:
            created = await http.post(
                "/ai/voice/sessions", json={"sessionId": session_id, "scenario": scenario}
            )
        if created.status_code != 201:
            return None
        return created.json()["aiSessionId"]

    async def release(self, ai_session_id: str) -> None:
        async with self.http(timeout=10.0) as http:
            await http.delete("/ai/voice/sessions/%s" % ai_session_id)

    async def one_call(self, session_id: str, delay: float = 0.0) -> Dict[str, object]:
        """Один звонок: несколько ходов, задержка каждого хода."""
        if delay:
            await asyncio.sleep(delay)
        ai_session_id = await self.open_session(session_id)
        if ai_session_id is None:
            return {"session": session_id, "turns": [], "errors": ["сессия не создалась"]}

        latencies: List[float] = []
        errors: List[str] = []
        try:
            extra = self.headers or None
            async with websockets.connect(
                self.ws_url(ai_session_id, session_id), proxy=None, additional_headers=extra
            ) as connection:
                await connection.send(json.dumps(STREAM_START))

                for number in range(self.turns):
                    audio = self.recordings[number % len(self.recordings)]
                    began = time.perf_counter()
                    for offset in range(0, len(audio), FRAME_BYTES):
                        await connection.send(audio[offset : offset + FRAME_BYTES])
                    await connection.send(json.dumps({"type": "input.flush"}))

                    while True:
                        frame = await asyncio.wait_for(connection.recv(), timeout=120.0)
                        if isinstance(frame, (bytes, bytearray)):
                            continue
                        payload = json.loads(frame)
                        if payload["type"] == "error":
                            errors.append(payload["code"])
                        if payload["type"] == "caller.state_changed":
                            latencies.append(time.perf_counter() - began)
                            break
                        if payload["type"] == "error" and payload["code"] == "speech.unavailable":
                            break

                await connection.send(json.dumps({"type": "stream.stop"}))
        except Exception as error:  # noqa: BLE001
            errors.append("%s: %s" % (type(error).__name__, error))
        finally:
            await self.release(ai_session_id)

        return {"session": session_id, "turns": latencies, "errors": errors}


async def warm_up(load: Load) -> float:
    """Два холостых звонка. Возвращает задержку самого первого хода.

    Холодное число печатается отдельно: на демонстрации первый звонок будет
    именно таким, и прятать это нельзя.
    """
    first = await load.one_call("warmup-1")
    await load.one_call("warmup-2")
    turns = first["turns"]
    return turns[0] if turns else 0.0


async def measure_http(load: Load, concurrency: int = 10, rounds: int = 3) -> Dict[str, float]:
    """p95 отклика HTTP под одновременными запросами."""
    scenario = await load.scenario()
    measurements: Dict[str, List[float]] = {"scenarios/generate": [], "sessions/score": []}

    score_request = {
        "sessionId": "load-http",
        "scenario": scenario,
        "transcript": [],
        "submittedCard": scenario["groundTruth"]["expectedInput"],
        "calculation": {
            "status": "RESOLVED",
            "classifierVersion": scenario["groundTruth"]["classifierVersion"],
            "classifierCode": scenario["groundTruth"]["classifierCode"],
            "incidentType": scenario["groundTruth"]["incidentType"],
            "ekp35IncidentType": scenario["groundTruth"]["ekp35IncidentType"],
            "responseScenarioCode": scenario["groundTruth"]["responseScenarioCode"],
            "responseScenarioStatus": scenario["groundTruth"]["responseScenarioStatus"],
            "mainServices": scenario["groundTruth"]["mainServices"],
            "services": scenario["groundTruth"]["requiredServices"],
        },
    }

    async def timed(http, path: str, body: dict, key: str) -> None:
        began = time.perf_counter()
        response = await http.post(path, json=body)
        measurements[key].append(time.perf_counter() - began)
        if response.status_code != 200:
            load.problems.append("%s ответил %s" % (path, response.status_code))

    async with load.http() as http:
        for _ in range(rounds):
            batch = []
            for _ in range(concurrency):
                batch.append(timed(http, "/ai/scenarios/generate", {"count": 4}, "scenarios/generate"))
                batch.append(timed(http, "/ai/sessions/score", score_request, "sessions/score"))
            await asyncio.gather(*batch)

    return {key: percentile(values, 0.95) for key, values in measurements.items()}


async def measure_sessions(
    load: Load, count: int, pid: Optional[int], spread: float = 0.0, label: str = "залп"
) -> Dict[str, object]:
    """Одновременные голосовые сессии: задержка хода и ресурсы.

    spread - за сколько секунд разъезжаются начала звонков. Ноль означает,
    что все курсанты домолчали ровно в одно мгновение: это худший случай,
    а не учебный класс. Настоящие занятия идут вразнобой, и это надо мерить
    отдельно, иначе вывод получится пессимистичнее правды.
    """
    usage = Usage(pid)
    watcher = asyncio.create_task(usage.watch())

    began = time.perf_counter()
    results = await asyncio.gather(
        *(
            load.one_call(
                "load-%d-%d" % (count, index),
                delay=spread * index / count if spread else 0.0,
            )
            for index in range(count)
        )
    )
    elapsed = time.perf_counter() - began

    usage.stop()
    watcher.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await watcher

    latencies = [value for result in results for value in result["turns"]]
    errors = [code for result in results for code in result["errors"]]

    return {
        "label": label,
        "sessions": count,
        "turns": len(latencies),
        "p50": percentile(latencies, 0.50),
        "p95": percentile(latencies, 0.95),
        "max": max(latencies) if latencies else 0.0,
        "elapsed": elapsed,
        "errors": errors,
        "usage": usage.describe(),
    }


async def measure_limit(load: Load, beyond: int = 6) -> Dict[str, object]:
    """Что происходит, когда сессий просят больше разрешённого.

    Отказ обязан быть внятным и не ронять сервис: иначе на демонстрации
    лишний звонок уложит занятия всех остальных.
    """
    scenario = await load.scenario()
    created: List[str] = []
    refused = 0
    codes = set()

    async with load.http() as http:
        for index in range(128):
            response = await http.post(
                "/ai/voice/sessions",
                json={"sessionId": "limit-%d" % index, "scenario": scenario},
            )
            if response.status_code == 201:
                created.append(response.json()["aiSessionId"])
                continue
            codes.add(response.status_code)
            refused += 1
            if refused >= beyond:
                break

    # Сервис обязан остаться живым и после отказов.
    async with load.http(timeout=10.0) as http:
        health = (await http.get("/health")).status_code
        for ai_session_id in created:
            await http.delete("/ai/voice/sessions/%s" % ai_session_id)

    return {"accepted": len(created), "refused": refused, "codes": sorted(codes), "health": health}


async def run(arguments) -> int:
    load = Load(arguments.base_url, arguments.token, arguments.turns)

    async with load.http(timeout=15.0) as http:
        try:
            health = (await http.get("/health")).json()
        except Exception as error:  # noqa: BLE001
            print("сервис не отвечает на %s: %s" % (arguments.base_url, error))
            return 1

    print("=" * 78)
    print("речь: %s | доступна: %s | подмена: %s"
          % (health["speech"], health["speechAvailable"], health["speechSimulated"]))
    if health["speechSimulated"]:
        print("ВНИМАНИЕ: работают подмены. Числа показывают транспорт, а не модели.")
    print("ходов в звонке: %d | записи: %d" % (load.turns, len(load.recordings)))
    print("=" * 78)

    cold = await warm_up(load)
    print("\nхолодный первый ход: %.2f с (дальше числа после прогрева)" % cold)

    print("\nHTTP, по 10 одновременных запросов в три круга")
    for path, value in (await measure_http(load)).items():
        verdict = "в норме" if value <= API_BUDGET_SECONDS else "ВЫШЕ НОРМАТИВА"
        print("   %-20s p95 %.3f с   норматив %.1f с   %s"
              % (path, value, API_BUDGET_SECONDS, verdict))

    print("\nГолосовые сессии. Залп - все домолчали разом, вразнобой - как в классе")
    print("   %-10s %-8s %-7s %-8s %-8s %-8s %-8s %s"
          % ("режим", "сессий", "ходов", "p50", "p95", "макс", "всего", "пик памяти/цпу"))
    rows = []
    modes = [("залп", 0.0)]
    if arguments.spread > 0:
        modes.append(("вразнобой", arguments.spread))
    for label, spread in modes:
        for count in arguments.sessions:
            row = await measure_sessions(load, count, arguments.pid, spread, label)
            rows.append(row)
            print("   %-10s %-8d %-7d %-8.2f %-8.2f %-8.2f %-8.2f %s"
                  % (label, count, row["turns"], row["p50"], row["p95"], row["max"],
                     row["elapsed"], row["usage"]))
            if row["errors"]:
                print("      ошибки: %s" % ", ".join(sorted(set(row["errors"]))))

    print("\nЗа пределом числа сессий")
    limit = await measure_limit(load)
    print("   принято %d, отказано %d, коды ответа %s, health после отказов %s"
          % (limit["accepted"], limit["refused"], limit["codes"], limit["health"]))
    if limit["health"] != 200:
        load.problems.append("после отказов сервис перестал отвечать на /health")
    if limit["codes"] and limit["codes"] != [503]:
        load.problems.append("отказ по пределу сессий пришёл с кодом %s, ожидался 503" % limit["codes"])

    print("\n" + "=" * 78)
    print("Бюджет паузы в разговоре %.1f с. Уложились на:" % TURN_BUDGET_SECONDS)
    for row in rows:
        if not row["turns"]:
            # Ноль измеренных ходов - это не успех. Без этой ветки отчёт
            # писал бы "p95 0.00 - да" там, где мерить было нечего.
            print("   %-10s %2d сессий: НЕЧЕГО МЕРИТЬ, ни один ход не прошёл"
                  % (row["label"], row["sessions"]))
            load.problems.append(
                "на %d сессиях (%s) не прошло ни одного хода" % (row["sessions"], row["label"])
            )
            continue
        verdict = "да" if row["p95"] <= TURN_BUDGET_SECONDS else "НЕТ"
        print("   %-10s %2d сессий: p95 %.2f с - %s"
              % (row["label"], row["sessions"], row["p95"], verdict))
    print("\nЭто задержка AI, не VoIP. One-way latency до трубки здесь не измеряется.")

    if load.problems:
        print("\nПРОБЛЕМЫ:")
        # Одна и та же беда на сотне запросов - это одна строка, а не сотня.
        for problem in sorted(set(load.problems)):
            print("  - %s (раз: %d)" % (problem, load.problems.count(problem)))
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--sessions", default="5,10,20",
                        help="сколько одновременных сессий мерить, через запятую")
    parser.add_argument("--turns", type=int, default=2, help="ходов в каждом звонке")
    parser.add_argument("--spread", type=float, default=10.0,
                        help="за сколько секунд разъезжаются начала звонков в режиме вразнобой")
    parser.add_argument("--pid", type=int, default=None,
                        help="процесс сервиса, чтобы снять память и процессор")
    parser.add_argument("--token", default=None, help="сервисный токен, если он настроен")
    arguments = parser.parse_args()
    arguments.sessions = [int(part) for part in arguments.sessions.split(",") if part.strip()]
    return asyncio.run(run(arguments))


if __name__ == "__main__":
    sys.exit(main())
