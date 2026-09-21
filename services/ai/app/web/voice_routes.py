"""Голосовой маршрут: создание AI-сессии и поток PCM.

Разделение ответственности прежнее. Core заводит сессию и передаёт
разрешённый контекст сценария, Media держит звонок и гоняет звук, AI только
отвечает за абонента. Ни SIP, ни маршрутизацией служб здесь не пахнет.
"""

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.schemas.voice import IncomingType, VoiceSessionRequest, VoiceSessionResponse
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


def _drop_queued_audio(queue: "asyncio.Queue[Frame]") -> None:
    """Снимает недоигранный ответ при перебивании.

    Управляющие сообщения при этом сохраняются: Media должна узнать, чем
    закончилась прерванная реплика.
    """
    kept: List[Frame] = []
    while not queue.empty():
        frame = queue.get_nowait()
        if not frame.is_audio:
            kept.append(frame)
    for frame in kept:
        queue.put_nowait(frame)


@stream_router.websocket("/internal/v1/voice/{ai_session_id}")
async def voice_stream(
    websocket: WebSocket,
    ai_session_id: str,
    sessionId: str = Query(..., description="Идентификатор учебной сессии в Core"),
) -> None:
    session = store().resolve(ai_session_id, sessionId)
    if session is None:
        await websocket.close(code=CLOSE_UNKNOWN_SESSION)
        return

    with session.lock:
        if session.attached:
            await websocket.close(code=CLOSE_SESSION_BUSY)
            return
        session.attached = True

    await websocket.accept()
    stream = VoiceStream(session, get_pipeline())
    outgoing: "asyncio.Queue[Frame]" = asyncio.Queue()

    async def sender() -> None:
        while True:
            frame = await outgoing.get()
            if frame.is_audio:
                await websocket.send_bytes(frame.audio)
            else:
                await websocket.send_json(frame.payload)

    sender_task = asyncio.create_task(sender())

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if message.get("bytes") is not None:
                frames = stream.handle_audio(message["bytes"])
            else:
                payload = _decode(message.get("text"))
                if payload is None:
                    frames = [stream.error_frame("message.invalid", "Ожидался JSON в текстовом фрейме.")]
                else:
                    if payload.get("type") == IncomingType.RESPONSE_CANCEL.value:
                        _drop_queued_audio(outgoing)
                    frames = stream.handle_message(payload)

            for frame in frames:
                outgoing.put_nowait(frame)

            if stream.stopped:
                # Даём отправителю дослать управляющие сообщения перед закрытием:
                # иначе Media не узнает, что абонент бросил трубку.
                while not outgoing.empty():
                    await asyncio.sleep(0)
                break
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
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
