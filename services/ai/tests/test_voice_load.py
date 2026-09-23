"""Голосовой поток под нагрузкой: очередь ограничена, поток не встаёт.

Тесты из tests/test_voice.py гоняют поток через TestClient и проверяют
контракт. Здесь другое: сервис поднимается настоящим uvicorn на свободном
порту в отдельном потоке, а клиенты живут в потоке теста. Иначе блокировку
обработчика не увидеть - если бы сервис и клиент делили один event loop,
встали бы оба сразу, и измерять было бы нечем.

Синтез здесь намеренно медленный и блокирующий, как настоящие Vosk и Piper:
они считают полсекунды внутри си-кода и event loop на это время не отдают.
"""

import asyncio
import contextlib
import json
import struct
import threading
import time

import httpx
import pytest
import websockets

from app.main import create_app
from app.voice import sessions, speech

FRAME = 640
SAMPLE_RATE = 16000

# Полсекунды речи оператора: содержимое подмене распознавания безразлично.
SPEECH = b"\x00\x00" * 8000

START = json.dumps(
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

# Сколько синтез "думает". Близко к настоящим моделям: по замерам #73 полный
# ход занимает около полусекунды.
SYNTHESIS_SECONDS = 1.0

# Во столько должен уложиться ответ второму клиенту, пока первый занят
# синтезом. С блокирующим обработчиком он ждёт весь синтез целиком, то есть
# секунду; без блокировки укладывается в единицы миллисекунд. Порог взят
# с большим запасом с обеих сторон: на общих раннерах CI бывают подвисания
# в сотни миллисекунд, и мигающий тест тут хуже, чем медленный.
RESPONSIVE_LIMIT = 0.35


class SlowSynthesizer:
    """Синтез, который честно занимает поток, как настоящая модель.

    time.sleep выбран намеренно вместо asyncio.sleep: Vosk и Piper считают
    внутри си-кода и event loop им не отдают. Замени на asyncio.sleep -
    и тест перестанет ловить ту поломку, ради которой написан.
    """

    name = "slow"
    real = False

    def __init__(self, seconds: float = SYNTHESIS_SECONDS, reply_seconds: float = 0.5) -> None:
        self.seconds = seconds
        self.reply_seconds = reply_seconds
        # Сообщает тесту, что работа в сервисе действительно началась.
        # Без этого пришлось бы угадывать момент замера.
        self.working = threading.Event()

    def synthesize(self, text: str, sample_rate: int = SAMPLE_RATE) -> bytes:
        self.working.set()
        time.sleep(self.seconds)
        samples = int(sample_rate * self.reply_seconds)
        return struct.pack("<%dh" % samples, *([0] * samples))


def use_slow_speech(**kwargs) -> SlowSynthesizer:
    synthesizer = SlowSynthesizer(**kwargs)
    speech.use_pipeline(
        speech.SpeechPipeline(speech.ScriptedRecognizer(("реплика оператора",)), synthesizer)
    )
    return synthesizer


@pytest.fixture(autouse=True)
def clean_store():
    sessions.store().clear()
    yield
    speech.use_pipeline(None)
    sessions.store().clear()


@contextlib.contextmanager
def running_service():
    """Настоящий uvicorn на свободном порту, в своём потоке."""
    import uvicorn

    config = uvicorn.Config(
        create_app(), host="127.0.0.1", port=0, log_level="error", ws_ping_interval=None
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.perf_counter() + 10
    while not server.started:
        if time.perf_counter() > deadline:
            raise RuntimeError("сервис не поднялся")
        time.sleep(0.01)

    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield "127.0.0.1:%d" % port
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def open_session(address: str, session_id: str) -> str:
    """Заводит голосовую сессию и возвращает адрес её потока."""
    async with httpx.AsyncClient(base_url="http://" + address, timeout=10.0) as http:
        scenarios = (await http.post("/ai/scenarios/generate", json={"count": 4})).json()
        created = await http.post(
            "/ai/voice/sessions",
            json={"sessionId": session_id, "scenario": scenarios["scenarios"][0]},
        )
        assert created.status_code == 201
        ai_session_id = created.json()["aiSessionId"]
    return "ws://%s/internal/v1/voice/%s?sessionId=%s" % (address, ai_session_id, session_id)


async def send_speech(connection, audio: bytes = SPEECH) -> None:
    for offset in range(0, len(audio), FRAME):
        await connection.send(audio[offset : offset + FRAME])
    await connection.send(json.dumps({"type": "input.flush"}))


async def read_until(connection, kinds, timeout: float = 10.0):
    """Читает до управляющего сообщения нужного типа, считая звук."""
    audio_bytes = 0
    while True:
        frame = await asyncio.wait_for(connection.recv(), timeout=timeout)
        if isinstance(frame, (bytes, bytearray)):
            audio_bytes += len(frame)
            continue
        payload = json.loads(frame)
        if payload["type"] in kinds:
            return payload, audio_bytes


async def connect_when_free(url: str, timeout: float):
    """Ждёт, пока сессия освободится, и подключается к ней.

    Занятость проверяется тем же способом, что и у Media - попыткой
    подключения: занятая сессия отказывает, свободная принимает. Лезть
    во внутренности хранилища ради этого не нужно.
    """
    deadline = time.perf_counter() + timeout
    while True:
        try:
            return await websockets.connect(url, proxy=None)
        except Exception:
            if time.perf_counter() > deadline:
                return None
            await asyncio.sleep(0.05)


# --- блокировка обработчика ---------------------------------------------------


def test_slow_synthesis_does_not_freeze_the_other_stream():
    """Пока один курсант ждёт синтеза, второй должен обслуживаться.

    Это главный риск задачи #74: обработчик зовёт синтез прямо в event loop,
    и на время работы модели сервис перестаёт отвечать всем остальным.
    На подменах этого не видно - они отвечают мгновенно.
    """
    synthesizer = use_slow_speech()

    async def scenario(address):
        busy_url = await open_session(address, "busy")
        other_url = await open_session(address, "other")

        async with websockets.connect(busy_url, proxy=None) as busy, websockets.connect(
            other_url, proxy=None
        ) as other:
            await busy.send(START)
            await other.send(START)

            # Занимаем сервис синтезом и не ждём его окончания.
            await send_speech(busy)
            answer = asyncio.create_task(read_until(busy, {"caller.state_changed", "error"}))

            # Меряем ровно тогда, когда сервис точно считает модель.
            assert await asyncio.to_thread(synthesizer.working.wait, 5.0), "синтез не начался"

            # Пустой флаш - самая дешёвая работа, какая есть: ответ на него
            # не требует ни распознавания, ни синтеза.
            started = time.perf_counter()
            await other.send(json.dumps({"type": "input.flush"}))
            payload, _ = await read_until(other, {"error"}, timeout=5.0)
            waited = time.perf_counter() - started

            await answer
        return payload, waited

    with running_service() as address:
        payload, waited = asyncio.run(scenario(address))

    assert payload["code"] == "input.empty"
    assert waited < RESPONSIVE_LIMIT, (
        "второй поток ждал %.2f с, пока первый синтезировал ответ: "
        "обработчик держит event loop" % waited
    )


# --- ограничение очереди ------------------------------------------------------


def test_queued_audio_is_bounded():
    """Длинный ответ не копится в памяти целиком.

    Очередь создаётся без предела, и весь ответ складывается в неё разом.
    Пока реплики короткие, это незаметно; при медленной Media или длинном
    ответе память растёт без границы.
    """
    from app.web import voice_routes

    limit = voice_routes.MAX_QUEUED_AUDIO_BYTES
    # Ответ вчетверо длиннее предела: обрезка обязана сработать.
    use_slow_speech(seconds=0.0, reply_seconds=(limit * 4) / (SAMPLE_RATE * 2))

    async def scenario(address):
        url = await open_session(address, "flooded")
        async with websockets.connect(url, proxy=None) as connection:
            await connection.send(START)
            await send_speech(connection)
            return await read_until(connection, {"caller.state_changed", "error"}, timeout=30.0)

    with running_service() as address:
        _, audio_bytes = asyncio.run(scenario(address))

    assert audio_bytes <= limit, "в очередь ушло %d байт при пределе %d" % (audio_bytes, limit)


def test_dropped_audio_is_reported_not_hidden():
    """Обрезанный ответ - это событие, о котором Media должна узнать.

    Молча недоотдать звук нельзя: Media решит, что абонент договорил, и
    занятие разберут по реплике, которой курсант не слышал.
    """
    from app.web import voice_routes

    limit = voice_routes.MAX_QUEUED_AUDIO_BYTES
    use_slow_speech(seconds=0.0, reply_seconds=(limit * 4) / (SAMPLE_RATE * 2))

    async def scenario(address):
        url = await open_session(address, "flooded")
        codes = []
        async with websockets.connect(url, proxy=None) as connection:
            await connection.send(START)
            await send_speech(connection)
            while True:
                frame = await asyncio.wait_for(connection.recv(), timeout=30.0)
                if isinstance(frame, (bytes, bytearray)):
                    continue
                payload = json.loads(frame)
                if payload["type"] == "error":
                    codes.append(payload["code"])
                if payload["type"] == "caller.state_changed":
                    return codes

    with running_service() as address:
        codes = asyncio.run(scenario(address))

    assert "output.overflow" in codes, "звук обрезали молча, кодов ошибок: %s" % codes


# --- завершение при медленном синтезе -----------------------------------------


def test_disconnect_during_synthesis_releases_the_session():
    """Клиент отвалился посреди синтеза - сессия обязана освободиться.

    Иначе занятая сессия останется занятой навсегда, и переподключиться
    к тому же звонку будет нельзя.
    """
    synthesizer = use_slow_speech()

    async def scenario(address):
        url = await open_session(address, "dropped")
        connection = await websockets.connect(url, proxy=None)
        await connection.send(START)
        await send_speech(connection)
        assert await asyncio.to_thread(synthesizer.working.wait, 5.0), "синтез не начался"
        await connection.close()

        # Ждём не дольше нескольких синтезов: оборвать счёт модели нельзя,
        # но и тянуть дольше неоткуда.
        again = await connect_when_free(url, SYNTHESIS_SECONDS * 5)
        if again is None:
            return False
        await again.close()
        return True

    with running_service() as address:
        assert asyncio.run(scenario(address)), "сессия осталась занятой после обрыва связи"


def test_reconnect_does_not_receive_the_previous_reply():
    """Ответ прерванного звонка не должен попасть в следующее подключение."""
    synthesizer = use_slow_speech()

    async def scenario(address):
        url = await open_session(address, "resumed")
        connection = await websockets.connect(url, proxy=None)
        await connection.send(START)
        await send_speech(connection)
        assert await asyncio.to_thread(synthesizer.working.wait, 5.0), "синтез не начался"
        await connection.close()

        again = await connect_when_free(url, SYNTHESIS_SECONDS * 5)
        assert again is not None, "сессия осталась занятой"
        async with again:
            await again.send(START)
            await again.send(json.dumps({"type": "input.flush"}))
            return await read_until(again, {"error", "transcript.final"}, 5.0)

    with running_service() as address:
        payload, audio_bytes = asyncio.run(scenario(address))

    assert payload["type"] == "error" and payload["code"] == "input.empty"
    assert audio_bytes == 0, "в новое подключение утёк звук прошлого ответа"
