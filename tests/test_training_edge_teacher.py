# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Edge test-teacher synthesis service: fake Edge connection, no network, no model."""

from __future__ import annotations

import io
import threading
import wave
from pathlib import Path

import numpy as np
import pytest

from src.server.runtime_settings import EDGE_TTS_ZH_TW_VOICE_IDS
from src.tts.training import edge_teacher
from src.tts.training.audio_quality import SAMPLE_RATE
from src.tts.training.corpus import REVIEW_CONFIRMED, REVIEW_PENDING, CorpusError, CorpusStore
from src.tts.training.edge_acknowledgement import MSA_CLAUSE, record_acknowledgement
from src.tts.training.edge_teacher import (
    BASE_BACKOFF_SECONDS,
    DEFAULT_VOICE,
    EDGE_ZH_TW_VOICES,
    MAX_ATTEMPTS,
    MAX_BACKOFF_SECONDS,
    MAX_CONSECUTIVE_FAILURES,
    SENTENCE_DELAY_SECONDS,
    DecodeError,
    decode_mp3_to_float,
    run_synthesis,
)

SLUG = "edge-test"
NAMES = ("甲", "乙", "丙", "丁", "戊", "己", "庚", "辛")  # digit-free, so the spoken text equals the input


def tone_bytes(seconds: float) -> bytes:
    """What the fake Edge connection sends; ``fake_decode`` turns it into samples."""
    return f"tone:{seconds}".encode()


def fake_decode(data: bytes) -> np.ndarray:
    if not data.startswith(b"tone:"):
        raise DecodeError("not audio")
    count = int(float(data[5:]) * SAMPLE_RATE)
    t = np.arange(count) / SAMPLE_RATE
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class FakePool:
    """Stands in for EdgeConnectionPool: ``script[text]`` lists one behaviour per call."""

    def __init__(self, script: dict[str, list] | None = None, default=tone_bytes(2.0)) -> None:
        self.script = {text: list(items) for text, items in (script or {}).items()}
        self.default = default
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def stream(self, text: str, voice: str):
        self.calls.append((text, voice))
        queue = self.script.get(text)
        behaviour = queue.pop(0) if queue else self.default
        if isinstance(behaviour, BaseException):
            raise behaviour
        for chunk in behaviour if isinstance(behaviour, list) else [behaviour]:
            yield {"type": "audio", "data": chunk}

    async def close(self) -> None:
        self.closed = True


class Sleeps:
    """Records every pause instead of waiting."""

    def __init__(self, on_sleep=None) -> None:
        self.durations: list[float] = []
        self._on_sleep = on_sleep

    async def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)
        if self._on_sleep:
            self._on_sleep(self)

    @property
    def total(self) -> float:
        return sum(self.durations)


@pytest.fixture
def store(tmp_path: Path) -> CorpusStore:
    return CorpusStore(tmp_path / "training")


@pytest.fixture
def corpus(store: CorpusStore) -> str:
    store.create(SLUG, source="edge-test-teacher")
    record_acknowledgement(store, SLUG, MSA_CLAUSE.text)
    return SLUG


def synthesize(store, sentences, *, pool=None, sleeps=None, **kwargs):
    pool = pool if pool is not None else FakePool()
    sleeps = sleeps if sleeps is not None else Sleeps()
    kwargs.setdefault("delay_seconds", 0.0)
    report = run_synthesis(
        store, SLUG, sentences, pool=pool, decode=fake_decode, sleep=sleeps, **kwargs
    )
    return report, pool, sleeps


# ------------------------------------------------------------------ the gate


def test_it_refuses_to_start_without_the_acknowledgement_and_sends_nothing(store):
    store.create("no-ack", source="edge-test-teacher")
    pool = FakePool()

    with pytest.raises(CorpusError) as caught:
        run_synthesis(store, "no-ack", ["你好"], pool=pool, decode=fake_decode)

    assert caught.value.status == 403
    assert pool.calls == []
    assert store.get("no-ack").lines == ()


def test_it_never_records_the_acknowledgement_itself(store):
    store.create("no-ack", source="edge-test-teacher")

    with pytest.raises(CorpusError):
        run_synthesis(store, "no-ack", ["你好"], pool=FakePool(), decode=fake_decode)

    assert not (store.root / "no-ack" / "msa-acknowledgement.json").exists()


def test_it_refuses_a_corpus_that_is_not_an_edge_corpus(store):
    store.create("mine", source="self-recorded")

    with pytest.raises(CorpusError):
        run_synthesis(store, "mine", ["你好"], pool=FakePool(), decode=fake_decode)


# ------------------------------------------------------------------ voices and input


def test_the_voices_are_the_edge_zh_tw_voices_and_hsiaochen_is_the_default():
    assert DEFAULT_VOICE == "zh-TW-HsiaoChenNeural"
    assert set(EDGE_ZH_TW_VOICES) == set(EDGE_TTS_ZH_TW_VOICE_IDS)
    assert EDGE_ZH_TW_VOICES[0] == DEFAULT_VOICE


def test_an_unknown_voice_is_refused_before_any_request(store, corpus):
    pool = FakePool()

    with pytest.raises(CorpusError):
        synthesize(store, ["你好"], pool=pool, voice="en-US-JennyNeural")

    assert pool.calls == []


def test_an_empty_or_invalid_sentence_list_is_refused(store, corpus):
    with pytest.raises(CorpusError):
        synthesize(store, [])
    with pytest.raises(CorpusError):
        synthesize(store, ["字" * 501])


# ------------------------------------------------------------------ the happy path


def test_each_sentence_becomes_a_confirmed_16k_mono_wav_line_with_its_text(store, corpus):
    report, pool, _ = synthesize(store, ["你好，歡迎光臨。", "今天天氣很好。"])

    lines = store.get(SLUG).lines
    assert [line.text for line in lines] == ["你好，歡迎光臨。", "今天天氣很好。"]
    assert all(line.review == REVIEW_CONFIRMED and line.ext == ".wav" for line in lines)
    with wave.open(str(store.audio_path(SLUG, lines[0].id)), "rb") as handle:
        assert (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) == (16000, 1, 2)
    assert (report.stored, report.rejected, report.failed, report.total) == (2, 0, 0, 2)
    assert pool.calls == [("你好，歡迎光臨。", DEFAULT_VOICE), ("今天天氣很好。", DEFAULT_VOICE)]


def test_english_lines_are_read_by_the_same_voice(store, corpus):
    _, pool, _ = synthesize(
        store, ["你好。", "Welcome to the exhibition.", "請打開 Wi-Fi。"], voice="zh-TW-YunJheNeural"
    )

    assert {voice for _text, voice in pool.calls} == {"zh-TW-YunJheNeural"}
    assert len(pool.calls) == 3


def test_the_corpus_stays_an_edge_corpus_labelled_development_only(store, corpus):
    synthesize(store, ["你好。"])

    assert store.get(SLUG).source == "edge-test-teacher"
    assert store.get(SLUG).usage_label() == "Development only"
    assert store.get(SLUG).trainability().trainable


def test_audio_is_loudness_normalised_before_it_is_stored(store, corpus):
    synthesize(store, ["你好。"])

    line = store.get(SLUG).lines[0]
    with wave.open(str(store.audio_path(SLUG, line.id)), "rb") as handle:
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2") / 32768.0
    assert float(np.sqrt(np.mean(pcm**2))) == pytest.approx(0.11, rel=0.05)


def test_chunks_of_one_response_are_joined_before_decoding(store, corpus):
    pool = FakePool(default=[b"tone:", b"1.5"])

    synthesize(store, ["你好。"], pool=pool)

    assert len(store.get(SLUG).lines) == 1


# ------------------------------------------------------------------ digits


def test_resolvable_digits_are_spoken_and_stored_as_chinese_characters(store, corpus):
    _, pool, _ = synthesize(store, ["活動在2026年11月24日舉行。"])

    assert pool.calls[0][0] == "活動在二零二六年十一月二十四日舉行。"
    line = store.get(SLUG).lines[0]
    assert line.text == "活動在二零二六年十一月二十四日舉行。"
    assert line.review == REVIEW_CONFIRMED


def test_unresolved_digits_are_not_guessed_and_go_to_review(store, corpus):
    report, pool, _ = synthesize(store, ["這個要價 $50 元。", "你好。"])

    line = store.get(SLUG).lines[0]
    assert line.text == "這個要價 $50 元。"
    assert line.review == REVIEW_PENDING
    assert report.needs_review == 1
    assert report.outcomes[0].status == edge_teacher.STATUS_NEEDS_REVIEW
    assert report.outcomes[0].reason == "currency"
    assert not store.get(SLUG).trainability().trainable
    assert store.get(SLUG).review_table()[0].normalized.unresolved


# ------------------------------------------------------------------ quality check


def test_audio_that_fails_the_quality_check_is_not_stored(store, corpus):
    pool = FakePool({"太短。": [tone_bytes(0.2)], "太長。": [tone_bytes(16.0)]})

    report, _, _ = synthesize(store, ["太短。", "太長。", "你好。"], pool=pool)

    assert [line.text for line in store.get(SLUG).lines] == ["你好。"]
    assert [(o.status, o.reason) for o in report.outcomes[:2]] == [
        (edge_teacher.STATUS_REJECTED, "too_short"),
        (edge_teacher.STATUS_REJECTED, "too_long"),
    ]
    assert report.rejected == 2


def test_undecodable_audio_is_rejected_not_fatal(store, corpus):
    pool = FakePool({"壞掉。": [b"garbage"]})

    report, _, _ = synthesize(store, ["壞掉。", "你好。"], pool=pool)

    assert report.outcomes[0].status == edge_teacher.STATUS_REJECTED
    assert report.outcomes[0].reason == "decode_failed"
    assert report.stored == 1


# ------------------------------------------------------------------ retry and backoff


def test_a_failed_request_is_retried_with_doubling_backoff(store, corpus):
    pool = FakePool({"你好。": [ConnectionError("reset"), TimeoutError(), tone_bytes(2.0)]})

    report, _, sleeps = synthesize(store, ["你好。"], pool=pool)

    assert report.stored == 1
    assert len(pool.calls) == 3
    assert sleeps.total == pytest.approx(BASE_BACKOFF_SECONDS * 3)  # base, then twice the base
    assert max(sleeps.durations) <= edge_teacher.PAUSE_SLICE_SECONDS


def test_an_empty_response_counts_as_a_failed_attempt(store, corpus):
    pool = FakePool({"你好。": [[], tone_bytes(2.0)]})

    report, _, _ = synthesize(store, ["你好。"], pool=pool)

    assert report.stored == 1
    assert len(pool.calls) == 2


def test_the_backoff_honours_a_longer_retry_after_header(store, corpus):
    limited = ConnectionError("429")
    limited.headers = {"Retry-After": "30"}
    pool = FakePool({"你好。": [limited, tone_bytes(2.0)]})

    _, _, sleeps = synthesize(store, ["你好。"], pool=pool)

    assert sleeps.total == pytest.approx(30.0)


def test_a_sentence_that_keeps_failing_is_given_up_after_the_attempt_limit(store, corpus):
    pool = FakePool({"壞句。": [ConnectionError("down")] * 10})

    report, _, sleeps = synthesize(store, ["壞句。", "你好。"], pool=pool)

    assert [call for call in pool.calls if call[0] == "壞句。"] == [("壞句。", DEFAULT_VOICE)] * MAX_ATTEMPTS
    assert report.outcomes[0].status == edge_teacher.STATUS_FAILED
    assert report.stored == 1
    assert sleeps.total == pytest.approx(sum(min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * 2**n) for n in range(MAX_ATTEMPTS - 1)))


def test_the_run_aborts_after_consecutive_failed_sentences(store, corpus):
    sentences = [f"{name}。" for name in NAMES[: MAX_CONSECUTIVE_FAILURES + 3]]
    pool = FakePool(default=ConnectionError("blocked"))

    report, _, _ = synthesize(store, sentences, pool=pool)

    assert report.aborted
    assert report.failed == MAX_CONSECUTIVE_FAILURES
    assert len(pool.calls) == MAX_CONSECUTIVE_FAILURES * MAX_ATTEMPTS
    assert store.get(SLUG).lines == ()


def test_a_success_resets_the_consecutive_failure_count(store, corpus):
    sentences = [f"{name}。" for name in NAMES]
    # fail, fail, success, fail, fail, success, fail, fail: never three in a row
    script = {s: [ConnectionError("x")] * MAX_ATTEMPTS for s in (f"{NAMES[n]}。" for n in (0, 1, 3, 4, 6, 7))}

    report, _, _ = synthesize(store, sentences, pool=FakePool(script))

    assert not report.aborted
    assert (report.failed, report.stored) == (6, 2)


# ------------------------------------------------------------------ pacing


def test_it_waits_between_sentences_but_not_after_the_last(store, corpus):
    report, _, sleeps = synthesize(store, ["一。", "二。", "三。"], delay_seconds=SENTENCE_DELAY_SECONDS)

    assert report.stored == 3
    assert sleeps.total == pytest.approx(SENTENCE_DELAY_SECONDS * 2)


# ------------------------------------------------------------------ progress, cancel, resume


def test_progress_is_reported_after_every_sentence(store, corpus):
    events = []
    pool = FakePool({"太短。": [tone_bytes(0.2)]})

    synthesize(store, ["你好。", "太短。", "這個 $5 呢。"], pool=pool, on_progress=events.append)

    assert [(e.index, e.total, e.status) for e in events] == [
        (1, 3, edge_teacher.STATUS_STORED),
        (2, 3, edge_teacher.STATUS_REJECTED),
        (3, 3, edge_teacher.STATUS_NEEDS_REVIEW),
    ]
    assert events[0].text == "你好。"
    assert events[0].line_id == "000001"
    assert events[1].line_id is None


def test_a_failing_progress_callback_does_not_stop_the_run(store, corpus):
    def broken(_event):
        raise RuntimeError("ui went away")

    report, _, _ = synthesize(store, ["一。", "二。"], on_progress=broken)

    assert report.stored == 2


def test_cancel_stops_before_the_next_sentence(store, corpus):
    cancel = threading.Event()
    seen = []

    def on_progress(event):
        seen.append(event.index)
        cancel.set()

    report, pool, _ = synthesize(store, ["一。", "二。", "三。"], cancel=cancel, on_progress=on_progress)

    assert report.cancelled
    assert not report.aborted
    assert seen == [1]
    assert len(pool.calls) == 1
    assert len(store.get(SLUG).lines) == 1


def test_cancel_before_the_start_sends_nothing(store, corpus):
    cancel = threading.Event()
    cancel.set()

    report, pool, _ = synthesize(store, ["一。"], cancel=cancel)

    assert report.cancelled
    assert pool.calls == []


def test_cancel_during_a_backoff_wait_stops_retrying(store, corpus):
    cancel = threading.Event()
    pool = FakePool({"你好。": [ConnectionError("x")] * 10})
    sleeps = Sleeps(on_sleep=lambda _s: cancel.set())

    report, _, _ = synthesize(store, ["你好。", "再見。"], pool=pool, sleeps=sleeps, cancel=cancel)

    assert report.cancelled
    assert len(pool.calls) == 1
    assert sleeps.total <= edge_teacher.PAUSE_SLICE_SECONDS * 2


def test_a_second_run_skips_sentences_the_corpus_already_has(store, corpus):
    synthesize(store, ["一。", "二。"])
    pool = FakePool()

    report, _, _ = synthesize(store, ["一。", "二。", "三。"], pool=pool)

    assert [call[0] for call in pool.calls] == ["三。"]
    assert report.skipped == 2
    assert report.stored == 1
    assert [line.text for line in store.get(SLUG).lines] == ["一。", "二。", "三。"]


# ------------------------------------------------------------------ pool ownership and threads


def test_without_a_pool_it_opens_one_and_closes_it(store, corpus, monkeypatch):
    made = []

    def factory(**kwargs):
        made.append(FakePool())
        return made[-1]

    monkeypatch.setattr(edge_teacher, "EdgeConnectionPool", factory)

    report = run_synthesis(store, SLUG, ["你好。"], decode=fake_decode, sleep=Sleeps(), delay_seconds=0)

    assert report.stored == 1
    assert len(made) == 1 and made[0].closed


def test_a_caller_supplied_pool_is_left_open(store, corpus):
    pool = FakePool()

    synthesize(store, ["你好。"], pool=pool)

    assert not pool.closed


def test_it_can_run_in_a_worker_thread(store, corpus):
    result = []
    worker = threading.Thread(target=lambda: result.append(synthesize(store, ["一。", "二。"])[0]))

    worker.start()
    worker.join(timeout=30)

    assert result and result[0].stored == 2


# ------------------------------------------------------------------ the real MP3 decoder


def _mp3_of_a_tone(seconds: float, rate: int = 24000) -> bytes:
    import av

    buffer = io.BytesIO()
    container = av.open(buffer, "w", format="mp3")
    stream = container.add_stream("libmp3lame", rate=rate)
    count = int(seconds * rate)
    samples = (0.3 * np.sin(2 * np.pi * 440 * np.arange(count) / rate) * 32767).astype(np.int16)
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = rate
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buffer.getvalue()


def test_the_decoder_turns_edge_mp3_into_16k_mono_float_samples():
    samples = decode_mp3_to_float(_mp3_of_a_tone(1.0))

    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert abs(samples.size - SAMPLE_RATE) < 0.15 * SAMPLE_RATE
    assert 0.1 < float(np.max(np.abs(samples))) <= 1.0


def test_the_decoder_refuses_bytes_that_are_not_audio():
    with pytest.raises(DecodeError):
        decode_mp3_to_float(b"this is not an mp3 file at all")
    with pytest.raises(DecodeError):
        decode_mp3_to_float(b"")
