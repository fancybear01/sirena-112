"""Голосовой маршрут: создание AI-сессии и поток PCM.

Разделение ответственности прежнее. Core заводит сессию и передаёт
разрешённый контекст сценария, Media держит звонок и гоняет звук, AI только
отвечает за абонента. Ни SIP, ни маршрутизацией служб здесь не пахнет.
"""

import asyncio
import contextlib
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from starlette.concurrency import run_in_threadpool

from app.web import auth
from app.schemas.voice import (
    IncomingType,
    OutgoingType,
    VoiceSessionRequest,
    VoiceSessionResponse,
)
from app.voice.sessions import TooManySessions, store
from app.voice.speech import get_pipeline
from app.voice.stream import Frame, VoiceStream

log = logging.getLogger(__name__)

voice_router = APIRouter(prefix="/ai/voice", tags=["voice"])
stream_router = APIRouter(tags=["voice"])

# Коды закрытия соединения. Контракт требует отказывать по неизвестной или
# несовпадающей паре идентификаторов, а причину надо различать на стороне Media.
CLOSE_UNKNOWN_SESSION = 4404
CLOSE_SESSION_BUSY = 4409
# Поток без сервисного токена. Media должна отличать это от неверной сессии:
# лечится не переподключением, а настройкой.
CLOSE_UNAUTHORIZED = 4401

# Сколько звука разрешено держать в очереди на отправку - десять секунд речи.
# Реплика абонента занимает секунды три-четыре, так что предел не мешает
# обычному разговору. Он нужен на случай, когда Media перестала читать:
# без него ответы копятся в памяти без всякой границы.
MAX_QUEUED_AUDIO_BYTES = 16000 * 2 * 10

# Сколько ждём, пока отправитель дошлёт хвост перед закрытием потока.
# Если Media уже не читает, ждать вечно нельзя.
DRAIN_SECONDS = 5.0


@voice_router.post(
    "/sessions",
    response_model=VoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать голосовую AI-сессию",
)
def create_voice_session(request: VoiceSessionRequest) -> VoiceSessionResponse:
    """Заводит сессию под будущий звонок и выдаёт aiSessionId."""
    try:
        session = store().create(request.session_id, request.scenario)
    except TooManySessions as overflow:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(overflow))

    pipeline = get_pipeline()
    return VoiceSessionResponse(
        ai_session_id=session.ai_session_id,
        session_id=session.session_id,
        scenario_id=str(request.scenario.id),
        speech=pipeline.describe(),
        speech_available=pipeline.available,
        speech_simulated=pipeline.simulated,
        notice=_speech_notice(pipeline),
    )


@voice_router.delete(
    "/sessions/{ai_session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Освободить голосовую AI-сессию",
)
def close_voice_session(ai_session_id: str) -> None:
    if not store().close(ai_session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Голосовая сессия не найдена")


def _speech_notice(pipeline) -> Optional[str]:
    """Предупреждение о режиме работы речи, если он не настоящий."""
    if not pipeline.available:
        return (
            "Речевые модели не настроены: поток годится только для проверки "
            "транспорта, транскрипта не будет."
        )
    if pipeline.simulated:
        return (
            "Работают подмены вместо моделей: транскрипт синтетический "
            "и для разбора занятия не годится."
        )
    return None


def _is_turn_end(frame: Frame) -> bool:
    """Кадр, которым заканчивается реплика абонента."""
    return (
        not frame.is_audio
        and frame.payload is not None
        and frame.payload.get("type") == OutgoingType.CALLER_STATE_CHANGED.value
    )


class OutgoingQueue:
    """Очередь на отправку с ограничением по объёму звука.

    Управляющие сообщения кладутся всегда: их мало, и по ним Media понимает,
    чем закончилась реплика. Ограничивается только звук - именно он способен
    занять память, если Media читает медленнее, чем AI синтезирует.
    """

    def __init__(self, limit: int = MAX_QUEUED_AUDIO_BYTES) -> None:
        self._queue: "asyncio.Queue[Frame]" = asyncio.Queue()
        self._limit = limit
        self._audio_bytes = 0
        self._dropped_bytes = 0

    def put(self, frame: Frame) -> bool:
        """Кладёт кадр. Возвращает False, если звук пришлось отбросить."""
        if frame.is_audio:
            size = len(frame.audio)
            if self._audio_bytes + size > self._limit:
                self._dropped_bytes += size
                return False
            self._audio_bytes += size
        self._queue.put_nowait(frame)
        return True

    async def get(self) -> Frame:
        frame = await self._queue.get()
        if frame.is_audio:
            self._audio_bytes -= len(frame.audio)
        return frame

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    def take_dropped(self) -> int:
        """Сколько звука отбросили с прошлого раза. Счётчик обнуляется."""
        dropped, self._dropped_bytes = self._dropped_bytes, 0
        return dropped

    def drop_audio(self) -> None:
        """Снимает недоигранный ответ при перебивании.

        Управляющие сообщения при этом сохраняются: Media должна узнать, чем
        закончилась прерванная реплика. Отброшенное здесь не считается потерей -
        его сняли намеренно, по команде Media.
        """
        kept: List[Frame] = []
        while not self._queue.empty():
            frame = self._queue.get_nowait()
            self._queue.task_done()
            if not frame.is_audio:
                kept.append(frame)
        self._audio_bytes = 0
        for frame in kept:
            self._queue.put_nowait(frame)


@stream_router.websocket("/internal/v1/voice/{ai_session_id}")
async def voice_stream(
    websocket: WebSocket,
    ai_session_id: str,
    sessionId: str = Query(..., description="Идентификатор учебной сессии в Core"),
) -> None:
    async def refuse(code: int, reason: str) -> None:
        """Отказывает в потоке и пишет причину в лог.

        Причину надо писать обязательно. Соединение закрывается до
        рукопожатия, поэтому все отказы выглядят для Media одинаково -
        как HTTP 403, а код закрытия до неё не доходит. Без записи в логе
        разобраться, чего не хватило, на демонстрации будет нечем.
        """
        log.warning("Голосовой поток %s отклонён: %s (код %d)", ai_session_id, reason, code)
        await websocket.close(code=code)

    if not auth.accepted(websocket.headers.get(auth.HEADER)):
        await refuse(CLOSE_UNAUTHORIZED, "нет сервисного токена или он не тот")
        return

    session = store().resolve(ai_session_id, sessionId)
    if session is None:
        await refuse(CLOSE_UNKNOWN_SESSION, "сессия не найдена или sessionId не совпал")
        return

    with session.lock:
        if session.attached:
            await refuse(CLOSE_SESSION_BUSY, "к сессии уже подключён другой поток")
            return
        session.attached = True

    await websocket.accept()
    stream = VoiceStream(session, get_pipeline())
    outgoing = OutgoingQueue()

    async def sender() -> None:
        while True:
            frame = await outgoing.get()
            try:
                if frame.is_audio:
                    await websocket.send_bytes(frame.audio)
                else:
                    await websocket.send_json(frame.payload)
            finally:
                outgoing.task_done()

    sender_task = asyncio.create_task(sender())

    def report_overflow() -> None:
        """Сообщает об отброшенном звуке, пока реплика не закрыта.

        Молчать нельзя: Media решит, что абонент договорил, и занятие
        разберут по реплике, которой курсант не слышал.
        """
        dropped = outgoing.take_dropped()
        if not dropped:
            return
        log.warning(
            "Голосовой поток %s: отброшено %d байт звука, Media не успевает читать",
            ai_session_id,
            dropped,
        )
        outgoing.put(
            stream.error_frame(
                "output.overflow",
                "Очередь отправки переполнена, часть звука ответа отброшена.",
            )
        )

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if message.get("bytes") is not None:
                # Приём звука - это дописать в буфер, считать тут нечего.
                frames = stream.handle_audio(message["bytes"])
            else:
                payload = _decode(message.get("text"))
                if payload is None:
                    frames = [stream.error_frame("message.invalid", "Ожидался JSON в текстовом фрейме.")]
                else:
                    if payload.get("type") == IncomingType.RESPONSE_CANCEL.value:
                        outgoing.drop_audio()
                    # Распознавание и синтез уходят в отдельный поток.
                    # Внутри них работают Vosk и Piper: они считают в си-коде
                    # по полсекунды и event loop не отдают. Оставь вызов здесь -
                    # и на это время встанут все остальные звонки разом.
                    frames = await run_in_threadpool(stream.handle_message, payload)

            for frame in frames:
                # caller.state_changed завершает реплику, и на нём читающая
                # сторона останавливается. Про потерю звука надо успеть
                # сказать до него, иначе сообщение никто не увидит.
                if _is_turn_end(frame):
                    report_overflow()
                outgoing.put(frame)

            report_overflow()

            if stream.stopped:
                # Даём отправителю дослать управляющие сообщения перед закрытием:
                # иначе Media не узнает, что абонент бросил трубку.
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(outgoing.join(), timeout=DRAIN_SECONDS)
                break
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender_task
        with session.lock:
            session.attached = False
        # Сырой звук в логи не пишем: только сколько его было.
        log.info(
            "Голосовой поток %s закрыт, принято %d мс речи",
            ai_session_id,
            stream.consumed_ms,
        )


def _decode(text):
    import json

    if not text:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None
