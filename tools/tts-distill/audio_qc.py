# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Shared 16 kHz audio normalization and faster-whisper QA helpers."""

from __future__ import annotations

import difflib
from pathlib import Path

import numpy as np
import soundfile as sf


def similarity_ratio(expected: str, recognized: str, *, converter=None) -> float:
    """Compute normalized alphanumeric similarity after optional T2S conversion."""
    if converter is None:
        from opencc import OpenCC

        converter = OpenCC("t2s")
    clean = lambda s: "".join(ch for ch in converter.convert(s).lower() if ch.isalnum())
    a = clean(expected)
    b = clean(recognized)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def trim_silence(wav: np.ndarray, sr: int, top_db: float = 40.0) -> np.ndarray:
    """Trim leading and trailing silence while preserving short onset/tail guard."""
    if wav.size == 0:
        return wav
    peak = float(np.max(np.abs(wav)))
    if peak < 1e-6:
        return np.empty(0, dtype=np.float32)
    thresh = peak * (10.0 ** (-top_db / 20.0))
    frame = max(1, int(sr * 0.01))
    active = np.where(np.abs(wav) > thresh)[0]
    if active.size == 0:
        return np.empty(0, dtype=np.float32)
    start = max(0, int(active[0]) - frame * 4)
    end = min(wav.size, int(active[-1]) + frame * 6)
    return wav[start:end].astype(np.float32, copy=False)


def process_and_verify_utterance(
    *,
    wav_16k: np.ndarray,
    uid: str,
    text: str,
    language: str,
    phoneme_ids: list[int],
    wav_dir: Path,
    whisper=None,
    min_asr_sim: float = 0.65,
    converter=None,
) -> dict | None:
    """Trim, peak-normalize, save PCM_16 WAV, optionally ASR-verify, and return manifest record."""
    wav_np = trim_silence(np.asarray(wav_16k, dtype=np.float32).reshape(-1), 16000)
    dur = float(wav_np.size) / 16000.0
    rms = float(np.sqrt(np.mean(wav_np**2))) if wav_np.size else 0.0
    if dur < 0.5 or dur > 15.0 or rms < 0.005:
        return None
    # Calibrate loudness (~0.11 RMS, capped below 0.75 peak) to match Vocos-16kHz mel dynamic range
    gain = 0.11 / rms
    peak_after = float(np.max(np.abs(wav_np))) * gain
    if peak_after > 0.75:
        gain *= 0.75 / peak_after
    wav_np = wav_np * gain

    wav_path = wav_dir / f"{uid}.wav"
    sf.write(
        wav_path,
        (np.clip(wav_np, -1.0, 1.0) * 32767.0).astype(np.int16),
        16000,
        subtype="PCM_16",
    )

    asr_text = ""
    asr_sim = 1.0
    if whisper is not None:
        segs, _ = whisper.transcribe(str(wav_path), beam_size=3, vad_filter=False)
        asr_text = "".join(s.text for s in segs).strip()
        asr_sim = similarity_ratio(text, asr_text, converter=converter)
        if asr_sim < min_asr_sim:
            wav_path.unlink(missing_ok=True)
            return None

    return {
        "id": uid,
        "text": text,
        "language": language,
        "wav": str(wav_path),
        "duration": round(dur, 3),
        "asr_text": asr_text,
        "asr_sim": round(asr_sim, 3),
        "phoneme_ids": phoneme_ids,
    }
