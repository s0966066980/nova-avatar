# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Transcript import: same-name .txt files and a metadata.csv, parsed strictly."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tts.training.corpus import CorpusStore
from src.tts.training.transcripts import (
    TranscriptError,
    apply_transcripts,
    parse_metadata_csv,
    parse_txt,
)

WAV = b"RIFF fixture wav bytes"


@pytest.fixture
def store(tmp_path: Path) -> CorpusStore:
    store = CorpusStore(tmp_path / "training")
    store.create("voice", source="self-recorded")
    return store


def upload(store: CorpusStore, original_name: str, text: str = "") -> str:
    return store.add_line("voice", WAV, ".wav", text=text, original_name=original_name).id


# ------------------------------------------------------------------ parsing


def test_a_txt_file_is_named_after_its_audio_and_holds_one_transcript():
    entry = parse_txt("sample-01.txt", "今天天氣很好。\n".encode("utf-8"))

    assert (entry.name, entry.text) == ("sample-01", "今天天氣很好。")


def test_a_txt_file_accepts_a_byte_order_mark_and_folds_line_breaks():
    entry = parse_txt("a.TXT", "﻿第一行\r\n第二行\n".encode("utf-8"))

    assert (entry.name, entry.text) == ("a", "第一行 第二行")


@pytest.mark.parametrize(
    ("filename", "data", "fragment"),
    [
        ("a.txt", b"", "沒有內容"),
        ("a.txt", b"   \n\n", "沒有內容"),
        ("a.txt", "你好".encode("big5"), "UTF-8"),
        ("a.txt", b"x" * 20000, "太大"),
        ("a.txt", ("字" * 501).encode(), "500"),
        ("a.txt", b"bad\x07bell", "控制字元"),
        ("../a.txt", b"x", "檔名"),
        ("a.csv", b"x", ".txt"),
        (".txt", b"x", "檔名"),
    ],
)
def test_bad_txt_files_get_a_clear_message(filename, data, fragment):
    with pytest.raises(TranscriptError) as excinfo:
        parse_txt(filename, data)
    assert fragment in excinfo.value.message


def test_metadata_csv_is_filename_pipe_text_and_may_carry_a_header():
    entries = parse_metadata_csv("filename|text\na.wav|你好\n\nb|世界\n".encode("utf-8-sig"))

    assert [(e.name, e.text) for e in entries] == [("a.wav", "你好"), ("b", "世界")]


def test_a_text_containing_a_pipe_is_refused_as_ambiguous():
    with pytest.raises(TranscriptError) as excinfo:
        parse_metadata_csv("a.wav|你好\nb.wav|Hello | world\n".encode("utf-8"))

    assert "第 2 行" in excinfo.value.message


def test_metadata_csv_without_a_header_is_accepted():
    entries = parse_metadata_csv("a.wav|你好\r\nb.wav|世界\r\n".encode("utf-8"))

    assert [e.name for e in entries] == ["a.wav", "b.wav"]


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("a.wav|你好\nb.wav\n", "第 2 行"),
        ("a.wav|你好\n|沒有檔名\n", "第 2 行"),
        ("a.wav|\n", "第 1 行"),
        ("a.wav|你好\na.wav|再一次\n", "重複"),
        ("dir/a.wav|你好\n", "檔名"),
        ("..\\a.wav|你好\n", "檔名"),
        ("a.wav|bad\x07text\n", "控制字元"),
        ("", "沒有任何資料"),
        ("filename|text\n", "沒有任何資料"),
    ],
)
def test_bad_csv_rows_are_reported_with_their_line_number(content, fragment):
    with pytest.raises(TranscriptError) as excinfo:
        parse_metadata_csv(content.encode("utf-8"))
    assert fragment in excinfo.value.message


def test_a_csv_that_is_not_utf8_asks_for_utf8():
    with pytest.raises(TranscriptError) as excinfo:
        parse_metadata_csv("a.wav|你好".encode("big5"))
    assert "UTF-8" in excinfo.value.message


def test_every_problem_in_one_csv_is_listed_together():
    with pytest.raises(TranscriptError) as excinfo:
        parse_metadata_csv(b"a.wav\nb.wav|\nok.wav|fine\n")
    assert len(excinfo.value.problems) == 2


# ------------------------------------------------------------------ applying


def test_transcripts_are_matched_to_uploads_by_original_name(store):
    first = upload(store, "take1.wav")
    second = upload(store, "take2.mp3")
    entries = parse_metadata_csv("take1.wav|第一句\ntake2|第二句\n".encode("utf-8"))

    result = apply_transcripts(store, "voice", entries)

    assert result.applied == 2
    texts = {line.id: line.text for line in store.get("voice").lines}
    assert texts == {first: "第一句", second: "第二句"}


def test_matching_is_all_or_nothing_and_names_every_unmatched_file(store):
    upload(store, "take1.wav")
    entries = parse_metadata_csv("take1.wav|第一句\nghost.wav|沒有這個音檔\nother|也沒有\n".encode("utf-8"))

    with pytest.raises(TranscriptError) as excinfo:
        apply_transcripts(store, "voice", entries)

    assert "ghost.wav" in excinfo.value.message and "other" in excinfo.value.message
    assert store.get("voice").lines[0].text == ""  # nothing was applied


def test_two_uploads_with_the_same_name_make_a_transcript_ambiguous(store):
    upload(store, "take.wav")
    upload(store, "take.wav")

    with pytest.raises(TranscriptError) as excinfo:
        apply_transcripts(store, "voice", [parse_txt("take.txt", b"x")])

    assert "同名" in excinfo.value.message


def test_two_transcripts_for_one_audio_are_refused(store):
    upload(store, "take.wav")

    with pytest.raises(TranscriptError) as excinfo:
        apply_transcripts(store, "voice", [parse_txt("take.txt", b"a"), parse_txt("take.txt", b"b")])

    assert "重複" in excinfo.value.message


def test_a_new_transcript_sends_a_confirmed_line_back_to_review(store):
    line_id = upload(store, "take.wav", text="舊稿")
    store.set_review("voice", line_id, "confirmed")

    apply_transcripts(store, "voice", [parse_txt("take.txt", "新稿".encode())])

    line = store.get("voice").lines[0]
    assert (line.text, line.review) == ("新稿", "pending")


def test_lines_without_a_transcript_are_left_for_automatic_transcription(store):
    upload(store, "a.wav")
    other = upload(store, "b.wav")

    result = apply_transcripts(store, "voice", [parse_txt("a.txt", b"x")])

    assert result.applied == 1
    assert result.without_transcript == [other]
