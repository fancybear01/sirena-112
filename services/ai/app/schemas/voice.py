"""Сообщения голосового потока Media <-> AI.

Имена и состав полей заданы contracts/media-ai.md. Текстовые фреймы несут
JSON, бинарные - сырой PCM16 mono 16 кГц.
"""

from enum import Enum
from typing import List, Optional

from pydantic import Field

from app.schemas.common import CamelModel
from app.schemas.scenario import Scenario


class AudioFormat(CamelModel):
    encoding: str = "pcm_s16le"
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=2)
    frame_duration_ms: int = Field(default=20, ge=10, le=100)


# --- создание сессии ----------------------------------------------------------


class VoiceSessionRequest(CamelModel):
    """Core создаёт AI-сессию и передаёт разрешённый контекст сценария."""

    session_id: str = Field(min_length=1)
    scenario: Scenario


class VoiceSessionResponse(CamelModel):
    ai_session_id: str
    session_id: str
    scenario_id: str
    # По какой паре моделей будет работать поток. Если речь не настроена
    # или подменена, это видно сразу, а не после первой реплики.
    speech: str
    speech_available: bool
    speech_simulated: bool
    notice: Optional[str] = None


# --- поток --------------------------------------------------------------------


class IncomingType(str, Enum):
    STREAM_START = "stream.start"
    INPUT_FLUSH = "input.flush"
    RESPONSE_CANCEL = "response.cancel"
    STREAM_STOP = "stream.stop"


class OutgoingType(str, Enum):
    TRANSCRIPT_FINAL = "transcript.final"
    CALLER_STATE_CHANGED = "caller.state_changed"
    RESPONSE_STARTED = "response.started"
    RESPONSE_COMPLETED = "response.completed"
    ERROR = "error"


class StreamStart(CamelModel):
    type: IncomingType
    session_id: Optional[str] = None
    ai_session_id: Optional[str] = None
    audio: AudioFormat = Field(default_factory=AudioFormat)


class ControlMessage(CamelModel):
    """input.flush, response.cancel и stream.stop отличаются только типом."""

    type: IncomingType
    sequence: Optional[int] = None
    timestamp: Optional[str] = None


class TranscriptFinal(CamelModel):
    type: OutgoingType = OutgoingType.TRANSCRIPT_FINAL
    sequence: int
    text: str
    started_at_ms: int
    ended_at_ms: int
    # Признак того, что текст получен подменой, а не распознаванием.
    # Без него разбор занятия опирался бы на несуществующую речь.
    simulated: bool = False


class ResponseStarted(CamelModel):
    type: OutgoingType = OutgoingType.RESPONSE_STARTED
    sequence: int
    text: str


class ResponseCompleted(CamelModel):
    type: OutgoingType = OutgoingType.RESPONSE_COMPLETED
    sequence: int
    duration_ms: int
    cancelled: bool = False


class CallerStateChanged(CamelModel):
    type: OutgoingType = OutgoingType.CALLER_STATE_CHANGED
    sequence: int
    panic: float
    trust: float
    patience: float
    revealed_facts: List[str] = Field(default_factory=list)
    hang_up: bool = False


class StreamError(CamelModel):
    type: OutgoingType = OutgoingType.ERROR
    sequence: int
    code: str
    message: str
