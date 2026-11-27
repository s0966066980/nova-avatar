# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Quality check and normalisation of synthesised teacher audio.

``assess_audio`` takes 16 kHz mono float samples in [-1, 1], trims leading and
trailing silence (keeping a short guard at both ends), checks the length, the
level and clipping, and returns the loudness-normalised samples. The Whisper
comparison is not done here: it needs a heavy model, so ``edge_teacher`` offers
a hook (``check_transcripts``) that the training job calls.

The thresholds follow the inherited distillation tooling (jetson-orin
``audio_qc.py``): 0.5 to 15 seconds, RMS at least 0.005, loudness calibrated to
about 0.11 RMS with the peak capped at 0.75.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
MIN_SECONDS = 0.5
MAX_SECONDS = 15.0
MIN_RMS = 0.005
MIN_PEAK = 1e-3
TARGET_RMS = 0.11
PEAK_CAP = 0.75
CLIP_LEVEL = 0.999
MAX_CLIPPED_FRACTION = 0.001
TRIM_BELOW_PEAK_DB = 40.0
GUARD_BEFORE_SECONDS = 0.04
GUARD_AFTER_SECONDS = 0.06

REASON_SILENT = "silent"
REASON_TOO_QUIET = "too_quiet"
REASON_TOO_SHORT = "too_short"
REASON_TOO_LONG = "too_long"
REASON_CLIPPED = "clipped"


@dataclass(frozen=True)
class QualityResult:
    """Measurements of the trimmed audio before normalisation, and the normalised samples.

    ``reasons`` is empty exactly when ``ok``. A rejected result carries the
    trimmed (not normalised) samples and whatever could be measured.
    """

    ok: bool
    reasons: tuple[str, ...]
    duration: float
    rms: float
    peak: float
    samples: np.ndarray


def assess_audio(samples: np.ndarray) -> QualityResult:
    """Check ``samples`` (16 kHz mono float) and return them trimmed and normalised."""
    wave_data = np.asarray(samples, dtype=np.float32).reshape(-1)
    if wave_data.size == 0 or not np.all(np.isfinite(wave_data)):
        return _rejected((REASON_SILENT,), np.empty(0, dtype=np.float32))
    wave_data = _trim_silence(wave_data)
    if wave_data.size == 0:
        return _rejected((REASON_SILENT,), wave_data)
    duration = wave_data.size / SAMPLE_RATE
    rms = float(np.sqrt(np.mean(np.square(wave_data, dtype=np.float64))))
    peak = float(np.max(np.abs(wave_data)))
    reasons: list[str] = []
    if duration < MIN_SECONDS:
        reasons.append(REASON_TOO_SHORT)
    if duration > MAX_SECONDS:
        reasons.append(REASON_TOO_LONG)
    if rms < MIN_RMS:
        reasons.append(REASON_TOO_QUIET)
    if np.mean(np.abs(wave_data) >= CLIP_LEVEL) > MAX_CLIPPED_FRACTION:
        reasons.append(REASON_CLIPPED)
    if reasons:
        return QualityResult(False, tuple(reasons), duration, rms, peak, wave_data)
    gain = TARGET_RMS / rms
    if peak * gain > PEAK_CAP:
        gain = PEAK_CAP / peak
    return QualityResult(True, (), duration, rms, peak, (wave_data * gain).astype(np.float32))


def to_wav_bytes(samples: np.ndarray) -> bytes:
    """16 kHz mono PCM16 WAV bytes of float ``samples``."""
    pcm = np.round(np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _rejected(reasons: tuple[str, ...], samples: np.ndarray) -> QualityResult:
    return QualityResult(False, reasons, samples.size / SAMPLE_RATE, 0.0, 0.0, samples)


def _trim_silence(samples: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(samples)))
    if peak < MIN_PEAK:
        return np.empty(0, dtype=np.float32)
    active = np.flatnonzero(np.abs(samples) > peak * 10.0 ** (-TRIM_BELOW_PEAK_DB / 20.0))
    start = max(0, int(active[0]) - int(GUARD_BEFORE_SECONDS * SAMPLE_RATE))
    end = min(samples.size, int(active[-1]) + int(GUARD_AFTER_SECONDS * SAMPLE_RATE))
    return samples[start:end]
