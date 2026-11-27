# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The Whisper comparison hook: a fake transcriber stands in, no model is loaded."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from nova_tts.training.corpus import REVIEW_CONFIRMED, REVIEW_EXCLUDED, REVIEW_PENDING, CorpusStore
from nova_tts.training.transcript_check import (
    DEFAULT_MIN_SIMILARITY,
    similarity_ratio,
    verify_with_asr,
)

WAV = b"RIFF fixture wav bytes"


@pytest.fixture
def store(tmp_path: Path) -> CorpusStore:
    store = CorpusStore(tmp_path / "training")
    store.create("edge-test", source="edge-test-teacher")
    return store


def add(store: CorpusStore, text: str, review: str = REVIEW_CONFIRMED) -> str:
    line = store.add_line("edge-test", WAV, ".wav", text=text)
    store.set_review("edge-test", line.id, review)
    return line.id


def transcriber(heard: dict[str, str]):
    """Returns what 'Whisper' heard for the audio file of each line id."""
    return lambda path: heard[path.stem]


def test_similarity_ignores_punctuation_case_and_script_variant():
    assert similarity_ratio("你好，世界。", "你好世界") == 1.0
    assert similarity_ratio("Hello World", "hello world") == 1.0
    assert similarity_ratio("歡迎來到台灣", "欢迎来到台湾") == 1.0


def test_similarity_of_unrelated_or_empty_text_is_low():
    assert similarity_ratio("今天天氣很好", "完全不同的內容在這裡") < 0.4
    assert similarity_ratio("今天天氣很好", "") == 0.0


def test_lines_that_match_what_was_heard_stay_confirmed(store):
    good = add(store, "今天天氣很好。")

    report = verify_with_asr(store, "edge-test", transcriber({good: "今天天氣很好"}))

    assert store.get("edge-test").lines[0].review == REVIEW_CONFIRMED
    assert (report.checked, report.excluded) == (1, ())


def test_lines_below_the_threshold_are_excluded_and_reported(store):
    good = add(store, "今天天氣很好。")
    bad = add(store, "請打開窗戶。")

    report = verify_with_asr(
        store, "edge-test", transcriber({good: "今天天氣很好", bad: "我想吃一碗牛肉麵加蛋"})
    )

    reviews = {line.id: line.review for line in store.get("edge-test").lines}
    assert reviews == {good: REVIEW_CONFIRMED, bad: REVIEW_EXCLUDED}
    assert [item.line_id for item in report.excluded] == [bad]
    assert report.excluded[0].heard == "我想吃一碗牛肉麵加蛋"
    assert report.excluded[0].similarity < DEFAULT_MIN_SIMILARITY


def test_the_threshold_can_be_changed(store):
    line = add(store, "今天天氣很好。")
    heard = {line: "今天天氣不錯"}

    lenient = verify_with_asr(store, "edge-test", transcriber(heard), min_similarity=0.5)
    assert lenient.excluded == ()
    strict = verify_with_asr(store, "edge-test", transcriber(heard), min_similarity=0.99)
    assert len(strict.excluded) == 1


def test_only_confirmed_lines_are_checked(store):
    pending = add(store, "還沒校對。", REVIEW_PENDING)
    excluded = add(store, "已經排除。", REVIEW_EXCLUDED)
    asked = []

    def transcribe(path):
        asked.append(path.stem)
        return ""

    report = verify_with_asr(store, "edge-test", transcribe)

    assert asked == [] and report.checked == 0
    assert {line.id: line.review for line in store.get("edge-test").lines} == {
        pending: REVIEW_PENDING,
        excluded: REVIEW_EXCLUDED,
    }


def test_progress_and_cancel(store):
    ids = [add(store, f"第{n}句話。") for n in "甲乙丙"]
    cancel = threading.Event()
    seen = []

    def on_progress(done, total):
        seen.append((done, total))
        cancel.set()

    report = verify_with_asr(
        store, "edge-test", transcriber({i: "" for i in ids}), cancel=cancel, on_progress=on_progress
    )

    assert seen == [(1, 3)]
    assert report.cancelled
    assert report.checked == 1


def test_a_failing_transcriber_is_not_swallowed(store):
    add(store, "今天天氣很好。")

    def transcribe(_path):
        raise RuntimeError("model not loaded")

    with pytest.raises(RuntimeError):
        verify_with_asr(store, "edge-test", transcribe)


# ------------------------------------------------------------------ digits


UPLOAD_DATE = "2026年11月24日"
SPOKEN_DATE = "二零二六年十一月二十四日"


@pytest.fixture
def uploads(tmp_path: Path) -> CorpusStore:
    store = CorpusStore(tmp_path / "uploads")
    store.create("edge-test", source="self-recorded")
    return store


def test_a_proofread_digit_line_is_compared_with_the_digits_read_out(uploads):
    """Whisper hears the date in Chinese numerals; the stored text has Arabic digits."""
    line = add(uploads, UPLOAD_DATE)

    report = verify_with_asr(uploads, "edge-test", transcriber({line: SPOKEN_DATE}))

    assert report.excluded == ()
    assert uploads.get("edge-test").lines[0].review == REVIEW_CONFIRMED


def test_the_raw_text_still_counts_when_whisper_writes_digits(uploads):
    line = add(uploads, UPLOAD_DATE)

    report = verify_with_asr(uploads, "edge-test", transcriber({line: "2026年11月24日"}))

    assert report.excluded == ()


def test_a_digit_line_that_really_differs_is_still_excluded_and_reports_the_spoken_text(uploads):
    line = add(uploads, UPLOAD_DATE)

    report = verify_with_asr(uploads, "edge-test", transcriber({line: "我想吃一碗牛肉麵加蛋"}))

    assert [item.line_id for item in report.excluded] == [line]
    assert report.excluded[0].expected == SPOKEN_DATE
    assert uploads.get("edge-test").lines[0].review == REVIEW_EXCLUDED
