"""Речевые адаптеры: формат выдачи и режим без моделей.

Сами модели здесь не нужны: проверяется то, что от них не зависит -
пересчёт частоты и поведение заглушек.
"""

import struct
import threading
import time

import pytest

from app.voice.speech import (
    PiperSynthesizer,
    SpeechPipeline,
    SpeechUnavailable,
    UnavailableRecognizer,
    UnavailableSynthesizer,
    resample_pcm16,
)


def tone(samples: int, rate: int) -> bytes:
    """Простой сигнал: важна только длина, а не звучание."""
    return struct.pack("<%dh" % samples, *[(index % 100) * 300 - 15000 for index in range(samples)])


def test_downsampling_keeps_duration():
    """Голоса Piper звучат на 22050, контракт требует 16000.

    Длительность при пересчёте обязана сохраниться: иначе Media проиграет
    реплику не на той скорости и голос поплывёт по тону.
    """
    one_second = tone(22050, 22050)

    result = resample_pcm16(one_second, 22050, 16000)

    assert len(result) // 2 == pytest.approx(16000, abs=2)


def test_same_rate_is_returned_untouched():
    audio = tone(1600, 16000)

    assert resample_pcm16(audio, 16000, 16000) is audio


def test_empty_audio_survives_resampling():
    assert resample_pcm16(b"", 22050, 16000) == b""


def test_resampled_audio_is_valid_pcm16():
    result = resample_pcm16(tone(4410, 22050), 22050, 16000)

    assert len(result) % 2 == 0
    values = struct.unpack("<%dh" % (len(result) // 2), result)
    assert all(-32768 <= value <= 32767 for value in values)


# --- синтез отдаёт частоту контракта, а не свою -------------------------------


class FakeVoice:
    """Голос, который поёт на своей частоте - как настоящие голоса Piper.

    Нужен, чтобы проверить адаптер без загрузки модели на 60 мегабайт.
    """

    def __init__(self, rate: int, seconds: float = 1.0) -> None:
        self.rate = rate
        self._samples = int(rate * seconds)

    def synthesize_wav(self, text: str, writer) -> None:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(self.rate)
        writer.writeframes(tone(self._samples, self.rate))


def piper_with(voice: FakeVoice) -> PiperSynthesizer:
    """Собирает адаптер в обход __init__: он там грузит настоящую модель."""
    synthesizer = object.__new__(PiperSynthesizer)
    synthesizer._voice = voice
    synthesizer._native_rate = voice.rate
    synthesizer._lock = threading.Lock()
    return synthesizer


def test_piper_converts_its_own_rate_to_the_requested_one():
    """Ошибка из #72: адаптер отдавал звук на 22050, а поток обещал 16000.

    Кадры при этом шли исправно, длительность считалась по байтам, и всё
    выглядело здоровым - реплика просто звучала не с той скоростью и не тем
    голосом. Ловится только сравнением с запрошенной частотой.
    """
    audio = piper_with(FakeVoice(22050)).synthesize("реплика", 16000)

    assert len(audio) // 2 == pytest.approx(16000, abs=2)


def test_piper_leaves_audio_alone_when_rates_already_match():
    audio = piper_with(FakeVoice(16000)).synthesize("реплика", 16000)

    assert len(audio) // 2 == 16000


class CountingVoice(FakeVoice):
    """Голос, который замечает, что в него вошли вдвоём."""

    def __init__(self, rate: int = 22050) -> None:
        super().__init__(rate, seconds=0.05)
        self.inside = 0
        self.overlapped = False

    def synthesize_wav(self, text: str, writer) -> None:
        self.inside += 1
        self.overlapped = self.overlapped or self.inside > 1
        time.sleep(0.05)
        super().synthesize_wav(text, writer)
        self.inside -= 1


def test_piper_does_not_let_two_calls_in_at_once():
    """Два звонка не должны синтезировать одновременно.

    После #74 распознавание и синтез уехали из event loop в рабочие потоки,
    и одну и ту же модель теперь дёргают разные звонки. Фонемизатор Piper
    живёт в глобальной переменной модуля, одной на процесс, поэтому вход
    в синтез закрыт замком.
    """
    voice = CountingVoice()
    synthesizer = piper_with(voice)
    threads = [
        threading.Thread(target=synthesizer.synthesize, args=("реплика", 16000)) for _ in range(4)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not voice.overlapped, "два потока вошли в синтез одновременно"


# --- режим без моделей --------------------------------------------------------


def test_unavailable_recognizer_explains_what_to_configure():
    with pytest.raises(SpeechUnavailable) as error:
        UnavailableRecognizer().transcribe(b"")

    assert "AI_STT" in str(error.value)


def test_unavailable_synthesizer_explains_what_to_configure():
    with pytest.raises(SpeechUnavailable) as error:
        UnavailableSynthesizer().synthesize("текст")

    assert "AI_TTS" in str(error.value)


def test_pipeline_without_models_is_not_available():
    pipeline = SpeechPipeline(UnavailableRecognizer(), UnavailableSynthesizer())

    assert pipeline.available is False
    assert pipeline.simulated is True
