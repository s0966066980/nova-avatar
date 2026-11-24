# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Audio preparation of a training job: conversion of uploads and the quality check."""

from __future__ import annotations

import io
import threading

import numpy as np
import pytest
import soundfile as sf

from src.tts.training.audio_quality import MAX_SECONDS, SAMPLE_RATE
from src.tts.training.corpus import REVIEW_CONFIRMED, REVIEW_EXCLUDED, CorpusStore
from src.tts.training.preparation import (
    DecodeError,
    check_quality,
    convert_uploads,
    decode_audio_file,
    prepared_path,
)
from src.tts.training.usage import SOURCE_SELF_RECORDED


def tone(seconds: float, rate: int = SAMPLE_RATE, channels: int = 1, amplitude: float = 0.3, lead: float = 0.3) -> bytes:
    """A WAV holding silence, a 220 Hz tone and silence: it trims to the tone."""
    t = np.arange(int(rate * seconds)) / rate
    body = amplitude * np.sin(2 * np.pi * 220 * t)
    silence = np.zeros(int(rate * lead))
    mono = np.concatenate([silence, body, silence]).astype("float32")
    data = np.stack([mono] * channels, axis=1) if channels > 1 else mono
    buffer = io.BytesIO()
    sf.write(buffer, data, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@pytest.fixture
def store(tmp_path):
    store = CorpusStore(tmp_path / "corpora")
    store.create("voice", SOURCE_SELF_RECORDED)
    return store


def add(store, audio: bytes, text: str = "你好", ext: str = ".wav"):
    line = store.add_line("voice", audio, ext, text)
    return store.set_review("voice", line.id, REVIEW_CONFIRMED)


def review_of(store, line_id: str) -> str:
    return next(line.review for line in store.get("voice").lines if line.id == line_id)


def test_decode_converts_any_rate_and_channel_count_to_16k_mono(tmp_path):
    path = tmp_path / "in.wav"
    path.write_bytes(tone(1.0, rate=44100, channels=2))
    samples = decode_audio_file(path)
    assert samples.dtype == np.float32 and samples.ndim == 1
    assert len(samples) == pytest.approx((1.0 + 0.6) * SAMPLE_RATE, abs=400)


def test_decode_refuses_files_that_are_not_audio(tmp_path):
    path = tmp_path / "in.wav"
    path.write_bytes(b"this is not audio at all")
    with pytest.raises(DecodeError):
        decode_audio_file(path)


def test_uploads_are_converted_and_undecodable_lines_are_excluded(store, tmp_path):
    good = add(store, tone(1.0, rate=44100, channels=2))
    bad = add(store, b"garbage that av cannot read", text="壞")
    progress = []
    report = convert_uploads(store, "voice", tmp_path / "work", on_progress=lambda done, total: progress.append((done, total)))
    assert (report.total, report.done) == (2, 1)
    assert [(e.line_id, e.reasons) for e in report.excluded] == [(bad.id, ("decode_failed",))]
    assert (tmp_path / "work" / "converted" / f"{good.id}.wav").is_file()
    assert review_of(store, bad.id) == REVIEW_EXCLUDED and review_of(store, good.id) == REVIEW_CONFIRMED
    assert progress[-1] == (2, 2)


def test_quality_check_writes_normalised_audio_and_excludes_failures(store, tmp_path):
    work = tmp_path / "work"
    ok = add(store, tone(1.5))
    quiet = add(store, tone(1.5, amplitude=0.001), text="小聲")
    short = add(store, tone(0.2), text="短")
    long = add(store, tone(MAX_SECONDS + 2), text="長")
    report = check_quality(store, "voice", work)
    assert report.done == 1 and not report.cancelled
    reasons = {e.line_id: set(e.reasons) for e in report.excluded}
    assert reasons[quiet.id] == {"too_quiet"}
    assert "too_short" in reasons[short.id] and "too_long" in reasons[long.id]
    prepared, _ = sf.read(prepared_path(work, ok.id), dtype="float32")
    assert 0.09 < float(np.sqrt(np.mean(prepared**2))) < 0.13  # normalised to the target level
    assert not prepared_path(work, quiet.id).exists()
    assert [review_of(store, i) for i in (ok.id, quiet.id, short.id, long.id)] == [
        REVIEW_CONFIRMED, REVIEW_EXCLUDED, REVIEW_EXCLUDED, REVIEW_EXCLUDED,
    ]


def test_quality_check_reads_the_converted_audio_when_there_is_one(store, tmp_path):
    work = tmp_path / "work"
    line = add(store, tone(1.5, rate=44100, channels=2))
    convert_uploads(store, "voice", work)
    assert check_quality(store, "voice", work).done == 1
    assert prepared_path(work, line.id).is_file()


def test_the_corpus_audio_is_never_modified(store, tmp_path):
    line = add(store, tone(1.5))
    original = store.audio_path("voice", line.id).read_bytes()
    check_quality(store, "voice", tmp_path / "work")
    assert store.audio_path("voice", line.id).read_bytes() == original


def test_only_confirmed_lines_are_checked(store, tmp_path):
    pending = store.add_line("voice", tone(1.5), ".wav", "待確認")
    report = check_quality(store, "voice", tmp_path / "work")
    assert report.total == 0 and not report.excluded
    assert review_of(store, pending.id) == "pending"


def test_cancel_stops_between_lines(store, tmp_path):
    for _ in range(3):
        add(store, tone(1.5))
    cancel = threading.Event()
    report = check_quality(store, "voice", tmp_path / "work", cancel=cancel, on_progress=lambda *_: cancel.set())
    assert report.cancelled and report.done == 1
