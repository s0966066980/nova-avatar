# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Decoding uploads to 16 kHz mono and the audio QC every training line passes."""

from __future__ import annotations

import io
import wave

import numpy as np
import pytest
import soundfile as sf

from src.tts.training.audio_qc import (
    MAX_DECODE_SECONDS,
    SAMPLE_RATE,
    decode_to_16k_mono,
    normalize_utterance,
    similarity_ratio,
    to_wav_bytes,
)
from src.tts.training.corpus import CorpusError


def tone(seconds: float, rate: int = SAMPLE_RATE, amplitude: float = 0.2, freq: float = 220.0) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def encode(samples: np.ndarray, rate: int = SAMPLE_RATE, fmt: str = "WAV", subtype: str | None = None) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format=fmt, subtype=subtype)
    return buffer.getvalue()


# ------------------------------------------------------------------ decoding


def test_decoding_resamples_and_downmixes_to_16k_mono_float():
    stereo = np.stack([tone(1.0, 44100), tone(1.0, 44100, freq=330.0)], axis=1)

    samples = decode_to_16k_mono(encode(stereo, 44100))

    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert abs(samples.size - SAMPLE_RATE) <= 400
    assert 0.1 < float(np.max(np.abs(samples))) <= 1.0


def test_flac_uploads_decode_too():
    samples = decode_to_16k_mono(encode(tone(1.0, 24000), 24000, fmt="FLAC"))

    assert abs(samples.size - SAMPLE_RATE) <= 400


@pytest.mark.parametrize(
    "data",
    [b"", b"just some text, not audio", b"RIFF\x00\x00\x00\x00WAVEfmt garbage", b"#EXTM3U\nfile:///etc/passwd\n"],
)
def test_bytes_that_are_not_decodable_audio_are_refused(data):
    with pytest.raises(CorpusError) as excinfo:
        decode_to_16k_mono(data)
    assert excinfo.value.status in (400, 415, 422)
    assert excinfo.value.message


def test_a_recording_far_longer_than_a_training_line_is_refused_before_decoding_all_of_it():
    long = encode(np.zeros(int((MAX_DECODE_SECONDS + 5) * 8000), dtype=np.float32) + 0.1, 8000)

    with pytest.raises(CorpusError) as excinfo:
        decode_to_16k_mono(long)

    assert "15" in excinfo.value.message


# ------------------------------------------------------------------ QC


def test_edge_silence_is_trimmed_and_the_level_is_normalised():
    padded = np.concatenate([np.zeros(SAMPLE_RATE), tone(2.0), np.zeros(SAMPLE_RATE)])

    result = normalize_utterance(padded)

    assert result.ok
    assert 2.0 <= result.duration < 2.6  # guard frames stay, the seconds of silence do not
    rms = float(np.sqrt(np.mean(result.samples**2)))
    assert rms == pytest.approx(0.11, abs=0.01)
    assert float(np.max(np.abs(result.samples))) <= 0.75 + 1e-6


def test_loud_peaks_cap_the_gain_instead_of_clipping():
    spiky = tone(1.0, amplitude=0.02)
    spiky[::800] = 0.9

    result = normalize_utterance(spiky)

    assert result.ok
    assert float(np.max(np.abs(result.samples))) == pytest.approx(0.75, abs=0.01)


@pytest.mark.parametrize(
    ("samples", "reason"),
    [
        (tone(0.3), "too_short"),
        (tone(16.0), "too_long"),
        (np.zeros(SAMPLE_RATE * 2, dtype=np.float32), "silent"),
        (tone(2.0, amplitude=0.003), "too_quiet"),
    ],
)
def test_clips_outside_the_limits_are_rejected_with_a_reason(samples, reason):
    result = normalize_utterance(samples)

    assert not result.ok
    assert result.reason == reason
    assert result.message  # Traditional Chinese text for the administrator
    assert result.samples is None


def test_the_length_limits_are_those_of_the_distillation_tool():
    assert normalize_utterance(tone(0.55)).ok
    assert normalize_utterance(tone(14.5)).ok
    assert not normalize_utterance(tone(15.5)).ok


def test_the_stored_wav_is_16k_mono_pcm16():
    wav = to_wav_bytes(normalize_utterance(tone(1.0)).samples)

    with wave.open(io.BytesIO(wav)) as handle:
        assert (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) == (16000, 1, 2)


# ------------------------------------------------------------------ similarity


def test_similarity_ignores_punctuation_case_and_script_variant():
    assert similarity_ratio("你好，世界！", "你好世界") == 1.0
    assert similarity_ratio("你們好", "你们好") == 1.0  # compared in one script
    assert similarity_ratio("Hello World", "hello world.") == 1.0


def test_similarity_is_low_for_a_different_sentence_and_zero_for_nothing():
    assert similarity_ratio("今天天氣很好", "我想吃牛肉麵") < 0.65
    assert similarity_ratio("你好", "") == 0.0
