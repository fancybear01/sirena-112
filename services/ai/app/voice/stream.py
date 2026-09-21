"""Состояние одного голосового потока.

Класс намеренно синхронный и ничего не знает про WebSocket: на вход события,
на выход кадры. Так его можно проверять тестами без сети и без моделей.

Время в сообщениях считается от количества принятого звука, а не по часам.
Поэтому один и тот же разговор даёт одинаковые отметки времени, и занятие
можно разобрать с преподавателем.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.engines.rule_dialogue import respond
from app.schemas.dialogue import CallerState, DialogueRequest
from app.schemas.voice import (
    AudioFormat,
    CallerStateChanged,
    IncomingType,
    ResponseCompleted,
    ResponseStarted,
    StreamError,
    TranscriptFinal,
)
from app.voice.sessions import AiSession
from app.voice.speech import SpeechPipeline, SpeechUnavailable

# Двадцать миллисекунд при 16 кГц PCM16 - рекомендация контракта.
FRAME_BYTES = 640

# Фрагмент длиннее тридцати секунд - это не реплика, а сбой на стороне Media.
MAX_FRAGMENT_SECONDS = 30
MAX_FRAGMENT_BYTES = 16000 * 2 * MAX_FRAGMENT_SECONDS


@dataclass
class Frame:
    """Кадр наружу: либо JSON, либо звук."""

    payload: Optional[Dict[str, Any]] = None
    audio: Optional[bytes] = None

    @property
    def is_audio(self) -> bool:
        return self.audio is not None


class VoiceStream:
    """Разбирает события потока и готовит ответы AI-абонента."""

    def __init__(self, session: AiSession, pipeline: SpeechPipeline) -> None:
        self.session = session
        self.pipeline = pipeline
        self.audio_format = AudioFormat()
        self.started = False
        self.stopped = False

        self._buffer = bytearray()
        self._consumed_ms = 0
        self._sequence = 0
        self._overflow = False

    # --- вспомогательное ------------------------------------------------------

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _frame(self, message) -> Frame:
        return Frame(payload=message.model_dump(by_alias=True))

    def _error(self, code: str, message: str) -> Frame:
        return self._frame(StreamError(sequence=self._next_sequence(), code=code, message=message))

    @property
    def consumed_ms(self) -> int:
        """Сколько миллисекунд речи принято за поток. Для логов и метрик."""
        return self._consumed_ms

    def error_frame(self, code: str, message: str) -> Frame:
        """Ошибка потока наружу. Используется и маршрутом, и самим потоком."""
        return self._error(code, message)

    def _bytes_to_ms(self, size: int) -> int:
        bytes_per_ms = self.audio_format.sample_rate * 2 * self.audio_format.channels / 1000
        return int(size / bytes_per_ms) if bytes_per_ms else 0

    def _caller_state(self) -> Optional[CallerState]:
        return self.session.caller_state

    # --- вход -----------------------------------------------------------------

    def handle_audio(self, chunk: bytes) -> List[Frame]:
        """Накапливает звук до команды на распознавание."""
        if not self.started:
            return [self._error("stream.not_started", "Звук пришёл до сообщения stream.start.")]
        if self.stopped:
            return [self._error("stream.stopped", "Поток уже завершён.")]

        if len(self._buffer) + len(chunk) > MAX_FRAGMENT_BYTES:
            # Буфер не растим: иначе сбой на стороне Media съест память.
            if not self._overflow:
                self._overflow = True
                return [
                    self._error(
                        "input.too_long",
                        "Фрагмент длиннее {seconds} с отброшен.".format(
                            seconds=MAX_FRAGMENT_SECONDS
                        ),
                    )
                ]
            return []

        self._buffer.extend(chunk)
        return []

    def handle_message(self, message: Dict[str, Any]) -> List[Frame]:
        kind = message.get("type")

        if kind == IncomingType.STREAM_START.value:
            return self._start(message)
        if not self.started:
            return [self._error("stream.not_started", "Ожидается сообщение stream.start.")]
        if kind == IncomingType.INPUT_FLUSH.value:
            return self._flush()
        if kind == IncomingType.RESPONSE_CANCEL.value:
            return self._cancel()
        if kind == IncomingType.STREAM_STOP.value:
            self.stopped = True
            return []
        return [self._error("message.unknown", "Неизвестный тип сообщения: {kind}".format(kind=kind))]

    def _start(self, message: Dict[str, Any]) -> List[Frame]:
        if self.started:
            return [self._error("stream.already_started", "Поток уже начат.")]

        audio = message.get("audio") or {}
        try:
            self.audio_format = AudioFormat.model_validate(audio)
        except Exception:  # noqa: BLE001 - формат объясняем сообщением, а не трассировкой
            return [self._error("audio.invalid", "Неподдерживаемые параметры аудио.")]

        if self.audio_format.encoding != "pcm_s16le" or self.audio_format.channels != 1:
            return [
                self._error(
                    "audio.unsupported",
                    "Поддерживается только pcm_s16le, моно. Пришло: {encoding}, каналов {channels}.".format(
                        encoding=self.audio_format.encoding, channels=self.audio_format.channels
                    ),
                )
            ]

        self.started = True
        return []

    def _cancel(self) -> List[Frame]:
        """Оператор перебил абонента: недоигранный ответ снимается."""
        return [
            self._frame(
                ResponseCompleted(sequence=self._next_sequence(), duration_ms=0, cancelled=True)
            )
        ]

    def _flush(self) -> List[Frame]:
        """Фрагмент речи закончился: распознаём, отвечаем, озвучиваем."""
        fragment = bytes(self._buffer)
        self._buffer.clear()
        self._overflow = False

        if not fragment:
            return [self._error("input.empty", "Фрагмент речи пуст, распознавать нечего.")]

        started_at = self._consumed_ms
        duration = self._bytes_to_ms(len(fragment))
        self._consumed_ms += duration

        try:
            text = self.pipeline.recognizer.transcribe(fragment, self.audio_format.sample_rate)
        except SpeechUnavailable as unavailable:
            return [self._error("speech.unavailable", str(unavailable))]

        if not text:
            return [self._error("transcript.empty", "Речь в фрагменте не распознана.")]

        frames = [
            self._frame(
                TranscriptFinal(
                    sequence=self._next_sequence(),
                    text=text,
                    started_at_ms=started_at,
                    ended_at_ms=started_at + duration,
                    simulated=self.pipeline.simulated,
                )
            )
        ]

        answer = respond(
            DialogueRequest(
                ai_session_id=self.session.ai_session_id,
                scenario=self.session.scenario,
                caller_state=self._caller_state(),
                operator_utterance=text,
            )
        )
        self.session.caller_state = answer.caller_state

        frames.append(
            self._frame(ResponseStarted(sequence=self._next_sequence(), text=answer.reply))
        )

        try:
            audio = self.pipeline.synthesizer.synthesize(
                answer.reply, self.audio_format.sample_rate
            )
        except SpeechUnavailable as unavailable:
            frames.append(self._error("speech.unavailable", str(unavailable)))
            audio = b""

        for offset in range(0, len(audio), FRAME_BYTES):
            frames.append(Frame(audio=audio[offset : offset + FRAME_BYTES]))

        frames.append(
            self._frame(
                ResponseCompleted(
                    sequence=self._next_sequence(), duration_ms=self._bytes_to_ms(len(audio))
                )
            )
        )
        frames.append(
            self._frame(
                CallerStateChanged(
                    sequence=self._next_sequence(),
                    panic=answer.caller_state.panic,
                    trust=answer.caller_state.trust,
                    patience=answer.caller_state.patience,
                    revealed_facts=answer.revealed_facts,
                    hang_up=answer.hang_up,
                )
            )
        )

        if answer.hang_up:
            self.stopped = True

        return frames
