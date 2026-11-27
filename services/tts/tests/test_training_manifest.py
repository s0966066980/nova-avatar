# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Training manifest: token IDs come only from digit-expanded, confirmed corpus lines."""

from __future__ import annotations

import json

import pytest

from nova_tts.training.corpus import REVIEW_CONFIRMED, CorpusStore
from nova_tts.training.manifest import BASE_VOCAB, SKIP_NO_AUDIO, SKIP_NO_TOKENS, SKIP_UNKNOWN_TOKEN, build_manifest
from nova_tts.training.preparation import prepared_path
from nova_tts.training.usage import SOURCE_SELF_RECORDED

TOKENS = {" ": 1, ",": 4, ".": 5, "wo3": 11, "you3": 12, "san1": 13, "ge4": 14, "ping2": 15, "guo3": 16,
          "er4": 17, "ling2": 18, "liu4": 19, "nian2": 20, "dian4": 21, "hua4": 22, "<|unused|>": 2190}
LEXICON = ["我 wo3", "有 you3", "三 san1", "个 ge4", "苹果 ping2 guo3", "二 er4", "零 ling2", "六 liu4",
           "年 nian2", "电话 dian4 hua4"]


@pytest.fixture
def base_assets(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "tokens.txt").write_text("".join(f"{token} {number}\n" for token, number in TOKENS.items()), encoding="utf-8")
    (base / "lexicon.txt").write_text("\n".join(LEXICON) + "\n", encoding="utf-8")
    return base


@pytest.fixture
def store(tmp_path):
    store = CorpusStore(tmp_path / "corpora")
    store.create("voice", SOURCE_SELF_RECORDED)
    return store


def confirmed_line(store, text: str, work, *, prepared: bool = True):
    line = store.add_line("voice", b"RIFF", ".wav", text)
    line = store.set_review("voice", line.id, REVIEW_CONFIRMED)
    if prepared:
        path = prepared_path(work, line.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"wav")
    return line


def rows(result):
    return [json.loads(line) for line in result.manifest.read_text(encoding="utf-8").splitlines()]


def test_traditional_text_is_tokenised_through_the_simplified_lexicon(store, tmp_path, base_assets):
    work = tmp_path / "work"
    line = confirmed_line(store, "我有三個蘋果", work)
    result = build_manifest([(line, line.text)], work, base_assets)
    (row,) = rows(result)
    assert row["phoneme_ids"] == [11, 12, 13, 14, 15, 16]
    assert row["wav"] == str(prepared_path(work, line.id))
    assert result.written == 1 and not result.skipped
    assert (work / "lexicon.txt").read_text(encoding="utf-8").startswith("我 wo3\n")


def test_digits_are_expanded_by_the_corpus_before_tokenising(store, tmp_path, base_assets):
    work = tmp_path / "work"
    confirmed_line(store, "2026年有電話", work)
    lines = store.get("voice").training_lines()
    result = build_manifest(lines, work, base_assets)
    assert rows(result)[0]["phoneme_ids"] == [17, 18, 17, 19, 20, 12, 21, 22]
    assert not any(ch.isdigit() for ch in rows(result)[0]["text"])


def test_a_raw_digit_is_an_error_and_is_never_dropped_silently(store, tmp_path, base_assets):
    work = tmp_path / "work"
    line = confirmed_line(store, "我有3個蘋果", work)
    with pytest.raises(ValueError, match="digits"):
        build_manifest([(line, line.text)], work, base_assets)


def test_unusable_lines_are_skipped_with_a_reason(store, tmp_path, base_assets):
    work = tmp_path / "work"
    ok = confirmed_line(store, "我有三個蘋果", work)
    no_audio = confirmed_line(store, "我有三個蘋果", work, prepared=False)
    no_tokens = confirmed_line(store, "完全不在詞典裡", work)
    result = build_manifest([(line, line.text) for line in (ok, no_audio, no_tokens)], work, base_assets)
    assert result.written == 1
    assert dict(result.skipped) == {no_audio.id: SKIP_NO_AUDIO, no_tokens.id: SKIP_NO_TOKENS}


def test_a_token_outside_the_embedding_table_skips_the_line(store, tmp_path, base_assets):
    work = tmp_path / "work"
    line = confirmed_line(store, "我有三個蘋果", work)
    (base_assets / "lexicon.txt").write_text("我 wo3\n有 you3\n三 <|unused|>\n", encoding="utf-8")
    result = build_manifest([(line, line.text)], work, base_assets)
    assert result.written == 0 and result.skipped == ((line.id, SKIP_UNKNOWN_TOKEN),)
    assert BASE_VOCAB == 2190
