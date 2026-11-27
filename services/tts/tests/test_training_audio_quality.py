# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Quality check and normalisation of synthesised teacher audio (16 kHz mono)."""

from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from nova_tts.training.audio_quality import (
    REASON_CLIPPED,
    REASON_SILENT,
    REASON_TOO_LONG,
    REASON_TOO_QUIET,
    REASON_TOO_SHORT,
    SAMPLE_RATE,
    TARGET_RMS,
    assess_audio,
    to_wav_bytes,
)


def tone(seconds: float, amplitude: float = 0.3, *, lead: float = 0.0, tail: float = 0.0) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    body = amplitude * np.sin(2 * np.pi * 220 * t)
    return np.concatenate(
        [np.zeros(int(lead * SAMPLE_RATE)), body, np.zeros(int(tail * SAMPLE_RATE))]
    ).astype(np.float32)


def test_clean_speech_like_audio_passes_and_is_normalised_to_the_target_loudness():
    result = assess_audio(tone(2.0, amplitude=0.05))

    assert result.ok
    assert result.reasons == ()
    assert float(np.sqrt(np.mean(result.samples**2))) == pytest.approx(TARGET_RMS, rel=0.02)
    assert result.rms == pytest.approx(0.05 / 2**0.5, rel=0.02)  # measured before normalising
    assert result.duration == pytest.approx(2.0, abs=0.35)
    assert float(np.max(np.abs(result.samples))) <= 0.75 + 1e-6


def test_a_peaky_signal_is_limited_by_the_peak_cap_before_the_loudness_target():
    quiet_body = tone(2.0, amplitude=0.02)
    quiet_body[1000] = 0.5  # one transient far above the body

    result = assess_audio(quiet_body)

    assert float(np.max(np.abs(result.samples))) <= 0.75 + 1e-6
    assert float(np.sqrt(np.mean(result.samples**2))) < TARGET_RMS


def test_leading_and_trailing_silence_is_trimmed_but_keeps_a_short_guard():
    result = assess_audio(tone(1.0, lead=1.0, tail=1.0))

    assert 1.0 < result.duration < 1.5


@pytest.mark.parametrize(
    ("seconds", "reason"),
    [(0.3, REASON_TOO_SHORT), (15.5, REASON_TOO_LONG)],
)
def test_duration_must_be_between_half_a_second_and_fifteen_seconds(seconds, reason):
    result = assess_audio(tone(seconds))

    assert not result.ok
    assert reason in result.reasons


@pytest.mark.parametrize("seconds", [0.6, 14.5])
def test_durations_just_inside_the_range_pass(seconds):
    assert assess_audio(tone(seconds)).ok


def test_silence_and_empty_audio_are_rejected():
    assert assess_audio(np.zeros(SAMPLE_RATE, dtype=np.float32)).reasons == (REASON_SILENT,)
    assert assess_audio(np.zeros(0, dtype=np.float32)).reasons == (REASON_SILENT,)


def test_a_near_silent_signal_is_rejected_as_too_quiet():
    result = assess_audio(tone(2.0, amplitude=0.006))

    assert not result.ok
    assert REASON_TOO_QUIET in result.reasons


def test_clipped_audio_is_rejected():
    result = assess_audio(np.clip(tone(2.0, amplitude=3.0), -1.0, 1.0))

    assert not result.ok
    assert REASON_CLIPPED in result.reasons


def test_non_finite_samples_are_rejected_as_silent():
    samples = tone(1.0)
    samples[10] = np.nan

    assert assess_audio(samples).reasons == (REASON_SILENT,)


def test_a_rejected_result_still_reports_its_measurements():
    result = assess_audio(tone(0.3))

    assert result.duration == pytest.approx(0.3, abs=0.2)
    assert result.rms > 0


def test_wav_bytes_are_16_khz_mono_pcm16_that_round_trip():
    result = assess_audio(tone(1.0, amplitude=0.2))

    with wave.open(io.BytesIO(to_wav_bytes(result.samples)), "rb") as handle:
        assert handle.getframerate() == 16000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        frames = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")

    assert frames.size == result.samples.size
    assert np.max(np.abs(frames.astype(np.float32) / 32768.0 - result.samples)) < 1e-3
