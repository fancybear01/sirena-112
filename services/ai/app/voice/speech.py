"""Распознавание и синтез речи через заменяемые адаптеры.

Модели выбраны замерами из docs/ai-benchmark.md: Vosk для распознавания
в разговоре и Piper для синтеза. Оба работают на процессоре без видеокарты
и имеют разрешительные лицензии.

Главное правило этого модуля: **заглушка не выдаётся за настоящую
транскрипцию.** Если модели не настроены, поток отвечает понятной ошибкой,
а не придуманным текстом. Иначе преподаватель увидит осмысленный разбор
занятия, которого на самом деле не было.

Модели не скачиваются сами. Путь задаётся переменными окружения, и в CI
адаптеры не подключаются вовсе - там работают детерминированные подмены.
"""

import os
import struct
import threading
from array import array
from typing import Optional, Protocol, Tuple

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # PCM16


class SpeechUnavailable(RuntimeError):
    """Речевые модели не настроены. Текст сообщения уходит в поток как есть."""


class SpeechRecognizer(Protocol):
    """Переводит накопленный фрагмент речи в текст."""

    name: str
    real: bool

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str: ...


class SpeechSynthesizer(Protocol):
    """Озвучивает реплику абонента."""

    name: str
    real: bool

    def synthesize(self, text: str, sample_rate: int = SAMPLE_RATE) -> bytes: ...


class UnavailableRecognizer:
    """Заглушка по умолчанию: честно сообщает, что распознавать нечем."""

    name = "unavailable"
    real = False

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        raise SpeechUnavailable(
            "Распознавание речи не настроено. Задайте AI_STT=vosk и AI_STT_MODEL "
            "с путём к модели, иначе голосовой режим работает только как проверка "
            "транспорта."
        )


class UnavailableSynthesizer:
    """Заглушка по умолчанию: молчит вместо того, чтобы выдать чужой голос."""

    name = "unavailable"
    real = False

    def synthesize(self, text: str, sample_rate: int = SAMPLE_RATE) -> bytes:
        raise SpeechUnavailable(
            "Синтез речи не настроен. Задайте AI_TTS=piper и AI_TTS_MODEL "
            "с путём к голосу."
        )


class VoskRecognizer:
    """Потоковое распознавание Vosk.

    Выбран за скорость: по замерам работает впятеро быстрее реального времени
    на четырёх ядрах, а ключевые слова вопросов оператора разбирает уверенно.
    """

    name = "vosk"
    real = True

    def __init__(self, model_path: str) -> None:
        from vosk import Model  # импорт внутри: пакет нужен только в этом режиме

        self._model = Model(model_path)

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        import json

        from vosk import KaldiRecognizer

        recognizer = KaldiRecognizer(self._model, sample_rate)
        recognizer.AcceptWaveform(pcm)
        return json.loads(recognizer.FinalResult()).get("text", "").strip()


def resample_pcm16(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """Приводит звук к нужной частоте линейной интерполяцией.

    Нужна потому, что голоса Piper звучат на своей частоте - у ru_RU-irina
    это 22050 Гц, а контракт с Media требует 16000. Без пересчёта Media
    проиграла бы реплику не на той скорости: голос поплыл бы по тону.

    Интерполяция самая простая, без фильтра: для речи в телефонном качестве
    этого достаточно, а лишней зависимости не появляется.
    """
    if source_rate == target_rate or not pcm:
        return pcm

    source = memoryview(pcm).cast("h")
    target_length = int(len(source) * target_rate / source_rate)
    result = array("h", bytes(target_length * 2))

    step = len(source) / target_length
    for index in range(target_length):
        position = index * step
        left = int(position)
        right = min(left + 1, len(source) - 1)
        weight = position - left
        result[index] = int(source[left] * (1 - weight) + source[right] * weight)

    return result.tobytes()


class PiperSynthesizer:
    """Синтез Piper. Лицензия MIT, поэтому пригоден для поставки заказчику."""

    name = "piper"
    real = True

    def __init__(self, model_path: str) -> None:
        from piper import PiperVoice

        self._voice = PiperVoice.load(model_path)
        self._native_rate = self._voice.config.sample_rate
        self._lock = threading.Lock()

    def synthesize(self, text: str, sample_rate: int = SAMPLE_RATE) -> bytes:
        import io
        import wave

        buffer = io.BytesIO()
        # Синтез идёт под замком намеренно. Голосовые потоки работают в разных
        # потоках, а фонемизатор Piper лежит в глобальной переменной модуля -
        # одной на весь процесс. Пускать в неё два звонка разом нельзя.
        # Event loop замок не держит: он в рабочем потоке, а не в обработчике.
        with self._lock:
            with wave.open(buffer, "wb") as writer:
                self._voice.synthesize_wav(text, writer)
        buffer.seek(0)
        with wave.open(buffer, "rb") as reader:
            audio = reader.readframes(reader.getnframes())
            native_rate = reader.getframerate()

        return resample_pcm16(audio, native_rate, sample_rate)


class ScriptedRecognizer:
    """Детерминированная подмена для тестов и локальной проверки транспорта.

    Возвращает заранее заданные реплики по очереди. Ничего не распознаёт
    и не притворяется, что распознаёт: используется только там, где проверяется
    сам поток, а не качество речи.
    """

    name = "scripted"
    real = False

    def __init__(self, phrases: Tuple[str, ...]) -> None:
        self._phrases = phrases
        self._index = 0

    def transcribe(self, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> str:
        if not self._phrases:
            return ""
        phrase = self._phrases[self._index % len(self._phrases)]
        self._index += 1
        return phrase


class SilenceSynthesizer:
    """Детерминированная подмена синтеза: тишина нужной длительности.

    Длительность считается от длины текста, поэтому один и тот же ответ даёт
    одинаковое число байт - на этом держится проверка воспроизводимости.
    """

    name = "silence"
    real = False

    MS_PER_CHARACTER = 60

    def synthesize(self, text: str, sample_rate: int = SAMPLE_RATE) -> bytes:
        milliseconds = max(1, len(text)) * self.MS_PER_CHARACTER
        samples = int(sample_rate * milliseconds / 1000)
        return struct.pack("<%dh" % samples, *([0] * samples))


class SpeechPipeline:
    """Пара моделей, используемая голосовым потоком."""

    def __init__(self, recognizer: SpeechRecognizer, synthesizer: SpeechSynthesizer) -> None:
        self.recognizer = recognizer
        self.synthesizer = synthesizer

    @property
    def available(self) -> bool:
        """Поток вообще способен выдать транскрипт и звук."""
        return self.recognizer.name != "unavailable" and self.synthesizer.name != "unavailable"

    @property
    def simulated(self) -> bool:
        """Работают подмены, а не настоящие модели.

        Признак уходит и в ответ на создание сессии, и в каждый транскрипт:
        выдавать заглушку за распознанную речь нельзя, иначе преподаватель
        разберёт занятие, которого не было.
        """
        return not (getattr(self.recognizer, "real", False) and getattr(self.synthesizer, "real", False))

    def describe(self) -> str:
        return "{stt}+{tts}".format(stt=self.recognizer.name, tts=self.synthesizer.name)


_pipeline: Optional[SpeechPipeline] = None


def _build_from_environment() -> SpeechPipeline:
    """Собирает пару моделей по переменным окружения.

    Ошибка загрузки не роняет сервис: карточный режим не должен страдать
    из-за неверно указанного пути к голосовой модели.
    """
    recognizer: SpeechRecognizer = UnavailableRecognizer()
    synthesizer: SpeechSynthesizer = UnavailableSynthesizer()

    if os.getenv("AI_STT") == "vosk" and os.getenv("AI_STT_MODEL"):
        try:
            recognizer = VoskRecognizer(os.environ["AI_STT_MODEL"])
        except Exception:  # noqa: BLE001 - причина уходит в сообщение заглушки
            recognizer = UnavailableRecognizer()

    if os.getenv("AI_TTS") == "piper" and os.getenv("AI_TTS_MODEL"):
        try:
            synthesizer = PiperSynthesizer(os.environ["AI_TTS_MODEL"])
        except Exception:  # noqa: BLE001
            synthesizer = UnavailableSynthesizer()

    return SpeechPipeline(recognizer, synthesizer)


def get_pipeline() -> SpeechPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = _build_from_environment()
    return _pipeline


def use_pipeline(pipeline: Optional[SpeechPipeline]) -> None:
    """Подменяет пару моделей. Нужно тестам и локальной проверке транспорта."""
    global _pipeline
    _pipeline = pipeline
