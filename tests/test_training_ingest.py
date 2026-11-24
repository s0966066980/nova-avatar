# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Uploading recordings into a corpus: source declaration, validation, conversion, QC."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.tts.training.corpus import CorpusError, CorpusStore
from src.tts.training.ingest import (
    MAX_UPLOAD_BYTES,
    create_uploaded_corpus,
    ingest_audio,
)


def recording(seconds: float = 2.0, rate: int = 44100, fmt: str = "WAV", lead: float = 0.0, channels: int = 1) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    tone = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    samples = np.concatenate([np.zeros(int(lead * rate), dtype=np.float32), tone, np.zeros(int(lead * rate), dtype=np.float32)])
    if channels == 2:
        samples = np.stack([samples, samples], axis=1)
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def store(tmp_path: Path) -> CorpusStore:
    return CorpusStore(tmp_path / "training")


@pytest.fixture
def corpus(store) -> str:
    create_uploaded_corpus(store, "mine", "self-recorded", consent=True)
    return "mine"


# ------------------------------------------------------------------ source declaration


@pytest.mark.parametrize("source", ["self-recorded", "written-authorization"])
def test_authorised_sources_need_the_consent_statement(store, source):
    with pytest.raises(CorpusError) as excinfo:
        create_uploaded_corpus(store, "mine", source, consent=False)
    assert excinfo.value.status == 400
    assert "聲明" in excinfo.value.message
    assert store.list() == []

    created = create_uploaded_corpus(store, "mine", source, consent=True)
    assert created.source == source


def test_development_recordings_need_no_consent_and_stay_development_only(store):
    created = create_uploaded_corpus(store, "dev", "development-unlicensed", consent=False)

    assert created.source == "development-unlicensed"
    assert created.usage_label() == "Development only"


def test_authorised_recordings_are_research_non_commercial_never_commercial(store):
    created = create_uploaded_corpus(store, "mine", "written-authorization", consent=True)

    assert created.usage_label() == "Research / Non-commercial"


def test_the_edge_teacher_source_cannot_be_claimed_for_an_upload(store):
    with pytest.raises(CorpusError):
        create_uploaded_corpus(store, "fake", "edge-test-teacher", consent=True)


@pytest.mark.parametrize("source", [None, "", "commercial", 5])
def test_an_unknown_or_missing_source_is_refused(store, source):
    with pytest.raises(CorpusError):
        create_uploaded_corpus(store, "mine", source, consent=True)


def test_uploads_need_a_declared_source(store):
    store.create("undeclared")

    with pytest.raises(CorpusError) as excinfo:
        ingest_audio(store, "undeclared", recording(), "a.wav")

    assert excinfo.value.status == 409
    assert "來源" in excinfo.value.message
    assert store.get("undeclared").lines == ()


def test_an_upload_cannot_be_added_to_an_edge_teacher_corpus(store):
    store.create("edge", source="edge-test-teacher")

    with pytest.raises(CorpusError) as excinfo:
        ingest_audio(store, "edge", recording(), "a.wav")

    assert excinfo.value.status == 409


# ------------------------------------------------------------------ conversion and QC


def test_an_upload_is_stored_as_16k_mono_pcm16_wav_with_edge_silence_trimmed(store, corpus):
    result = ingest_audio(store, corpus, recording(2.0, 44100, lead=1.0, channels=2), "My Take.WAV")

    line = store.get(corpus).lines[0]
    assert line.id == result.line.id
    assert (line.ext, line.original_name, line.review, line.text) == (".wav", "My Take.WAV", "pending", "")
    with wave.open(str(store.audio_path(corpus, line.id))) as handle:
        assert (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) == (16000, 1, 2)
        seconds = handle.getnframes() / handle.getframerate()
    assert 2.0 <= seconds < 2.6
    assert result.duration == pytest.approx(seconds, abs=0.01)


def test_other_containers_are_converted_to_wav(store, corpus):
    ingest_audio(store, corpus, recording(2.0, 24000, fmt="FLAC"), "take.flac")

    assert store.get(corpus).lines[0].ext == ".wav"


def test_text_given_with_the_audio_becomes_the_pending_transcript(store, corpus):
    ingest_audio(store, corpus, recording(), "a.wav", text="你好世界")

    line = store.get(corpus).lines[0]
    assert (line.text, line.review) == ("你好世界", "pending")


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"seconds": 0.3}, "太短"),
        ({"seconds": 16.0}, "太長"),
    ],
)
def test_qc_failures_store_nothing_and_say_why(store, corpus, kwargs, fragment):
    with pytest.raises(CorpusError) as excinfo:
        ingest_audio(store, corpus, recording(rate=16000, **kwargs), "a.wav")

    assert excinfo.value.status == 422
    assert fragment in excinfo.value.message
    assert store.get(corpus).lines == ()
    assert list((store.root / corpus / "audio").glob("*")) == []


def test_silent_audio_is_refused(store, corpus):
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(32000, dtype=np.float32), 16000, format="WAV")

    with pytest.raises(CorpusError) as excinfo:
        ingest_audio(store, corpus, buffer.getvalue(), "a.wav")

    assert "沒有聲音" in excinfo.value.message


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize("name", ["a.txt", "a.exe", "a", "a.wav.sh", "", "a.WAVX"])
def test_the_extension_must_be_a_supported_audio_format(store, corpus, name):
    with pytest.raises(CorpusError) as excinfo:
        ingest_audio(store, corpus, recording(), name)

    assert excinfo.value.status == 415


def test_the_content_must_really_decode_whatever_the_name_says(store, corpus):
    with pytest.raises(CorpusError):
        ingest_audio(store, corpus, b"MZ this is a program, not a recording" * 100, "a.wav")
    with pytest.raises(CorpusError):
        ingest_audio(store, corpus, b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40, "a.wav")

    assert store.get(corpus).lines == ()


def test_playlist_content_is_never_probed(store, corpus):
    with pytest.raises(CorpusError):
        ingest_audio(store, corpus, b"#EXTM3U\nfile:///etc/passwd\n", "a.mp3")


def test_an_oversized_upload_is_refused_before_decoding(store, corpus):
    with pytest.raises(CorpusError) as excinfo:
        ingest_audio(store, corpus, b"\x00" * (MAX_UPLOAD_BYTES + 1), "a.wav")

    assert excinfo.value.status == 413


def test_an_empty_upload_is_refused(store, corpus):
    with pytest.raises(CorpusError):
        ingest_audio(store, corpus, b"", "a.wav")


def test_the_client_file_name_never_reaches_the_path(store, corpus):
    result = ingest_audio(store, corpus, recording(), "../../etc/evil.wav")

    assert result.line.original_name == "evil.wav"
    assert store.audio_path(corpus, result.line.id).parent == store.root / corpus / "audio"


# ------------------------------------------------------------------ optional similarity check


def test_a_transcript_that_the_recognizer_does_not_hear_is_refused(store, corpus):
    heard = []

    def recognizer(samples: np.ndarray) -> str:
        heard.append(samples.size)
        return "完全不同的一句話"

    with pytest.raises(CorpusError) as excinfo:
        ingest_audio(store, corpus, recording(), "a.wav", text="今天天氣很好", recognizer=recognizer)

    assert heard and excinfo.value.status == 422
    assert "不符" in excinfo.value.message
    assert store.get(corpus).lines == ()


def test_a_matching_transcript_passes_the_similarity_check(store, corpus):
    ingest_audio(store, corpus, recording(), "a.wav", text="今天天氣很好", recognizer=lambda _s: "今天天氣很好。")

    assert store.get(corpus).lines[0].text == "今天天氣很好"


def test_the_similarity_check_is_skipped_without_text_or_recognizer(store, corpus):
    def boom(_samples):
        raise AssertionError("must not be called")

    ingest_audio(store, corpus, recording(), "a.wav", recognizer=boom)  # no text
    ingest_audio(store, corpus, recording(), "b.wav", text="你好")  # no recognizer

    assert len(store.get(corpus).lines) == 2
