# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Decode an upload to 16 kHz mono and run the audio QC for a training line.

The QC rules are those of ``tools/tts-distill/audio_qc.py`` on the
``jetson-orin`` branch, rewritten here as pure functions: trim leading and
trailing silence (keeping a short onset and tail guard), keep 0.5 to 15 seconds,
reject clips that are silent or too quiet, then calibrate the loudness to
about 0.11 RMS with the peak capped at 0.75 (the level the 16 kHz vocoder was
trained on). The Whisper similarity check lives in ``similarity_ratio`` and is
applied by the caller with an injected recognizer; nothing here loads a model.

Decoding names its FFmpeg demuxer from the file's magic bytes
(``src.utils.audio_container``), because letting FFmpeg probe could follow
playlist formats to other files on the host. Everything here is CPU work that
can take longer than 50 ms: async callers run it in ``asyncio.to_thread``
(CODING_STANDARDS 3).
"""

from __future__ import annotations

import difflib
import io
import wave
from dataclasses import dataclass

import numpy as np

from src.tts.training.corpus import CorpusError
from src.utils.audio_container import HEADER_BYTES, demuxer_for

SAMPLE_RATE = 16000
MIN_SECONDS = 0.5
MAX_SECONDS = 15.0
MIN_RMS = 0.005
TARGET_RMS = 0.11
PEAK_CAP = 0.75
SILENCE_TOP_DB = 40.0
# A recording this much longer than a training line is refused before it is
# decoded in full, so a 20 MB upload cannot become hours of samples in memory.
MAX_DECODE_SECONDS = 60.0
# Similarity (0 to 1) below which a transcript is said not to match its audio.
MIN_SIMILARITY = 0.65
SUPPORTED_FORMATS = "WAV、MP3、FLAC、OGG、M4A、WebM"

_REASON_MESSAGES = {
    "silent": "音檔幾乎沒有聲音",
    "too_short": f"音檔太短，修剪頭尾靜音後至少需要 {MIN_SECONDS:g} 秒",
    "too_long": f"音檔太長，修剪頭尾靜音後不可超過 {MAX_SECONDS:g} 秒；請切成較短的句子再上傳",
    "too_quiet": "音檔音量太小，請提高錄音音量後重新上傳",
}


@dataclass(frozen=True)
class QcResult:
    """The outcome of ``normalize_utterance``; ``samples`` is set only when ``ok``."""

    reason: str | None
    duration: float
    samples: np.ndarray | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None

    @property
    def message(self) -> str:
        return _REASON_MESSAGES.get(self.reason or "", "")


# ------------------------------------------------------------------ decoding


def decode_to_16k_mono(data: bytes) -> np.ndarray:
    """Decode audio bytes to mono float32 samples at 16 kHz, or raise ``CorpusError``."""
    import av

    demuxer = demuxer_for(bytes(data[:HEADER_BYTES]))
    if demuxer is None:
        raise CorpusError(f"不是支援的音檔，請上傳 {SUPPORTED_FORMATS}", status=415)
    try:
        container = av.open(io.BytesIO(data), format=demuxer)
    except Exception as exc:
        raise CorpusError(f"無法解析音檔，請上傳 {SUPPORTED_FORMATS}", status=422) from exc
    limit = int(MAX_DECODE_SECONDS * SAMPLE_RATE)
    too_long = CorpusError(
        f"音檔太長，每句不可超過 {MAX_SECONDS:g} 秒；請切成較短的句子再上傳", status=422
    )
    try:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None or not stream.rate:
            raise CorpusError("檔案沒有可用的音訊軌", status=422)
        if container.duration and container.duration / 1_000_000 > MAX_DECODE_SECONDS + 0.5:
            raise too_long
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        chunks: list[np.ndarray] = []
        total = 0

        def keep(frames) -> None:
            nonlocal total
            for frame in frames:
                part = frame.to_ndarray().reshape(-1).astype(np.int16)
                total += part.size
                if total > limit:
                    raise too_long
                chunks.append(part)

        for frame in container.decode(stream):
            keep(resampler.resample(frame))
        keep(resampler.resample(None))
    except CorpusError:
        raise
    except Exception as exc:
        raise CorpusError(f"無法解碼音檔，請上傳 {SUPPORTED_FORMATS}", status=422) from exc
    finally:
        container.close()
    if not chunks:
        raise CorpusError("音檔沒有任何聲音資料", status=422)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


# ------------------------------------------------------------------ QC


def trim_silence(wav: np.ndarray, rate: int = SAMPLE_RATE, top_db: float = SILENCE_TOP_DB) -> np.ndarray:
    """Cut leading and trailing silence, keeping a 40 ms onset and 60 ms tail guard."""
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    if wav.size == 0:
        return wav
    peak = float(np.max(np.abs(wav)))
    if peak < 1e-6:
        return np.empty(0, dtype=np.float32)
    active = np.flatnonzero(np.abs(wav) > peak * 10.0 ** (-top_db / 20.0))
    frame = max(1, int(rate * 0.01))
    start = max(0, int(active[0]) - frame * 4)
    end = min(wav.size, int(active[-1]) + frame * 6)
    return wav[start:end]


def normalize_utterance(wav: np.ndarray) -> QcResult:
    """Trim, check the length and level, and calibrate the loudness of one clip."""
    trimmed = trim_silence(wav)
    if trimmed.size == 0:
        return QcResult("silent", 0.0)
    duration = trimmed.size / SAMPLE_RATE
    if duration < MIN_SECONDS:
        return QcResult("too_short", duration)
    if duration > MAX_SECONDS:
        return QcResult("too_long", duration)
    rms = float(np.sqrt(np.mean(trimmed.astype(np.float64) ** 2)))
    if rms < MIN_RMS:
        return QcResult("too_quiet", duration)
    gain = TARGET_RMS / rms
    peak = float(np.max(np.abs(trimmed))) * gain
    if peak > PEAK_CAP:
        gain *= PEAK_CAP / peak
    return QcResult(None, duration, (trimmed * gain).astype(np.float32))


def to_wav_bytes(samples: np.ndarray) -> bytes:
    """A 16 kHz mono PCM16 WAV file of float samples in [-1, 1]."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


# ------------------------------------------------------------------ similarity


def similarity_ratio(expected: str, recognized: str, *, converter=None) -> float:
    """Alphanumeric similarity (0 to 1) of two texts compared in simplified script.

    ``converter`` is an object with ``convert`` (OpenCC ``t2s`` by default) so a
    test or caller can avoid loading the dictionary.
    """
    if converter is None:
        from opencc import OpenCC

        converter = OpenCC("t2s")

    def clean(text: str) -> str:
        return "".join(ch for ch in converter.convert(text).lower() if ch.isalnum())

    left, right = clean(expected), clean(recognized)
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()
