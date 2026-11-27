# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Decoding uploads to 16 kHz mono and wording the QC verdict."""

from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf

from nova_tts.training.audio_decode import MAX_DECODE_SECONDS, decode_to_16k_mono, quality_message
from nova_tts.training.audio_quality import SAMPLE_RATE
from nova_tts.training.corpus import CorpusError


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


# ------------------------------------------------------------------ messages


def test_every_rejection_reason_has_a_traditional_chinese_sentence():
    for reason in ("silent", "too_short", "too_long", "too_quiet", "clipped"):
        assert quality_message((reason,)), reason
    assert "太短" in quality_message(("too_short",))
    assert "；" in quality_message(("too_quiet", "clipped"))
