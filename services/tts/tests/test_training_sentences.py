# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Built-in sentence library, duration-based presets and admin-supplied text lists."""

from __future__ import annotations

import re

import pytest
from opencc import OpenCC

from src.tts.training.corpus import MAX_TEXT_CHARS, CorpusError
from src.tts.training.numerals import normalize_digits
from src.tts.training.sentences import (
    MAX_TEXT_LIST_BYTES,
    PRESETS,
    estimate_seconds,
    library,
    parse_text_list,
    review_text_list,
    select_by_duration,
    select_preset,
)

# ------------------------------------------------------------------ the library


def test_library_has_about_nine_hundred_unique_sentences():
    sentences = library()

    assert 850 <= len(sentences) <= 950
    assert len({item.text for item in sentences}) == len(sentences)


def test_library_covers_every_requested_category():
    categories = {item.category for item in library()}

    assert {"greetings", "weather", "traffic", "colloquial", "mixed", "numbers"} <= categories


def test_library_is_traditional_chinese():
    to_traditional = OpenCC("s2t")
    # Variant forms that are ordinary Traditional characters in Taiwan.
    accepted = {("台", "臺"), ("吃", "喫"), ("才", "纔"), ("群", "羣")}

    simplified = [
        item.text
        for item in library()
        if any(
            (before, after) not in accepted
            for before, after in zip(item.text, to_traditional.convert(item.text), strict=True)
            if before != after
        )
    ]

    assert simplified == []


def test_library_mixes_chinese_and_english_and_digits():
    texts = [item.text for item in library()]

    assert any(re.search(r"[A-Za-z]{3,}", text) and re.search(r"[一-鿿]", text) for text in texts)
    assert any(not re.search(r"[一-鿿]", text) for text in texts)
    assert sum(1 for text in texts if re.search(r"[0-9]", text)) >= 100


def test_every_library_sentence_is_a_clean_single_line_the_normaliser_can_fully_expand():
    for item in library():
        assert item.text == " ".join(item.text.split()), item.text
        assert 4 <= len(item.text) <= MAX_TEXT_CHARS, item.text
        assert normalize_digits(item.text).resolved, item.text


# ------------------------------------------------------------------ duration estimate


def test_estimate_counts_the_expanded_digits_not_the_numerals():
    assert estimate_seconds("今年是2026年") > estimate_seconds("今年是1年")


def test_estimate_grows_with_length_and_counts_english_words():
    short = estimate_seconds("你好。")
    long = estimate_seconds("你好，歡迎來到今天的活動現場，請往這邊走。")
    english = estimate_seconds("Please follow the guide to the next room.")

    assert 0 < short < long
    assert english > short


# ------------------------------------------------------------------ presets


def test_presets_are_quick_test_and_standard():
    assert [preset.label for preset in PRESETS.values()] == ["快速測試", "標準"]
    assert PRESETS["quick-test"].target_seconds == 15 * 60
    assert PRESETS["standard"].target_seconds == 60 * 60


@pytest.mark.parametrize("key", ["quick-test", "standard"])
def test_a_preset_lands_within_ten_percent_of_its_target(key):
    chosen = select_preset(key)

    total = sum(estimate_seconds(text) for text in chosen)
    target = PRESETS[key].target_seconds
    assert target * 0.9 <= total <= target * 1.1


def test_the_standard_preset_is_a_superset_of_the_quick_test_preset():
    assert set(select_preset("quick-test")) < set(select_preset("standard"))


def test_the_quick_test_preset_still_covers_every_category():
    by_text = {item.text: item.category for item in library()}

    covered = {by_text[text] for text in select_preset("quick-test")}

    assert covered == {item.category for item in library()}


def test_unknown_preset_is_refused():
    with pytest.raises(CorpusError):
        select_preset("whole-library")


def test_selection_is_deterministic_and_has_no_duplicates():
    first = select_by_duration(1200)

    assert first == select_by_duration(1200)
    assert len(set(first)) == len(first)


def test_a_target_beyond_the_library_returns_the_whole_library():
    assert len(select_by_duration(10**9)) == len(library())


def test_a_non_positive_target_is_refused():
    with pytest.raises(CorpusError):
        select_by_duration(0)


# ------------------------------------------------------------------ administrator text list


def test_text_list_keeps_one_sentence_per_line_in_order():
    assert parse_text_list("你好\n早安\n") == ["你好", "早安"]


def test_text_list_accepts_utf8_bytes_with_a_bom_and_windows_line_ends():
    raw = "﻿你好\r\n早安\r\n".encode("utf-8")

    assert parse_text_list(raw) == ["你好", "早安"]


def test_text_list_drops_blank_lines_and_collapses_spaces_and_duplicates():
    assert parse_text_list("  你好   世界 \n\n你好 世界\n再見") == ["你好 世界", "再見"]


def test_text_list_without_any_sentence_is_refused():
    with pytest.raises(CorpusError):
        parse_text_list("\n  \n")


def test_text_list_that_is_not_utf8_is_refused():
    with pytest.raises(CorpusError):
        parse_text_list("你好".encode("big5"))


def test_text_list_names_the_line_of_an_overlong_sentence():
    with pytest.raises(CorpusError) as caught:
        parse_text_list("你好\n" + "字" * (MAX_TEXT_CHARS + 1))

    assert "第 2 行" in caught.value.message


def test_text_list_refuses_control_characters():
    with pytest.raises(CorpusError):
        parse_text_list("你好\x00世界")


def test_text_list_is_bounded_in_size_and_in_lines():
    with pytest.raises(CorpusError):
        parse_text_list("\n".join(f"第{n}句" for n in range(6000)))
    with pytest.raises(CorpusError):
        parse_text_list("字" * (2 * 1024 * 1024))


# ------------------------------------------------------------------ the text review


def test_review_expands_digits_per_sentence_and_estimates_the_total():
    review = review_text_list("我有3個蘋果\n今天晴天\n")

    assert review.ok and review.total == 2
    assert [(r.index, r.text, r.spoken) for r in review.sentences] == [
        (1, "我有3個蘋果", "我有三個蘋果"),
        (2, "今天晴天", "今天晴天"),
    ]
    assert review.estimated_seconds == pytest.approx(estimate_seconds("我有3個蘋果") + estimate_seconds("今天晴天"))


def test_review_reports_each_unresolved_fragment_with_its_reason_and_span():
    review = review_text_list("價錢是$50\n你好\n溫度 25°C")

    assert not review.ok
    first, clean, third = review.sentences
    assert clean.unresolved == ()
    assert first.unresolved[0].text == "$50" and first.unresolved[0].reason == "currency"
    assert first.text[first.unresolved[0].start : first.unresolved[0].end] == "$50"
    assert [u.reason for u in third.unresolved] == ["degree"]
    assert [r.index for r in review.sentences if r.unresolved] == [1, 3]


def test_review_uses_the_same_sentence_list_as_a_job_would_synthesise():
    raw = "第一句\n\n第二句\n第一句\n"

    assert [r.text for r in review_text_list(raw).sentences] == parse_text_list(raw)


@pytest.mark.parametrize("raw", ["", "\n \n", "含\x07控制字元"])
def test_review_refuses_what_parse_text_list_refuses(raw):
    with pytest.raises(CorpusError):
        review_text_list(raw)


def test_review_keeps_the_size_limit_of_a_job():
    with pytest.raises(CorpusError) as caught:
        review_text_list("字" * (MAX_TEXT_LIST_BYTES + 1))
    assert caught.value.status == 413
