# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Digit and date expansion to Chinese characters for training transcripts."""

from __future__ import annotations

import pytest

from nova_tts.training.numerals import normalize_digits


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("共有15個人", "共有十五個人"),
        ("0", "零"),
        ("10", "十"),
        ("20", "二十"),
        ("100", "一百"),
        ("101", "一百零一"),
        ("110", "一百一十"),
        ("1001", "一千零一"),
        ("1010", "一千零一十"),
        ("2500", "二千五百"),
        ("第3名", "第三名"),
        ("10,000", "一萬"),
        ("100,005", "十萬零五"),
        ("1,234,567", "一百二十三萬四千五百六十七"),
        ("100,005,000", "一億零五千"),
        ("30,000,000", "三千萬"),
    ],
)
def test_integers_are_read_as_quantities(text, expected):
    result = normalize_digits(text)
    assert result.text == expected
    assert result.unresolved == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026年", "二零二六年"),
        ("2026年11月24日", "二零二六年十一月二十四日"),
        ("11月24日", "十一月二十四日"),
        ("05月03號", "五月三號"),
        ("民國115年", "民國一百一十五年"),
        ("3年", "三年"),
    ],
)
def test_dates_and_years(text, expected):
    result = normalize_digits(text)
    assert result.text == expected
    assert result.unresolved == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.5", "三點五"),
        ("0.5", "零點五"),
        ("3.50", "三點五零"),
        ("12.375公斤", "十二點三七五公斤"),
        ("50%", "百分之五十"),
        ("3.5%", "百分之三點五"),
        ("100％", "百分之一百"),
    ],
)
def test_decimals_and_percentages(text, expected):
    result = normalize_digits(text)
    assert result.text == expected
    assert result.unresolved == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0912345678", "零九一二三四五六七八"),
        ("02-23456789", "零二二三四五六七八九"),
        ("02-2345-6789", "零二二三四五六七八九"),
        ("0912-345-678", "零九一二三四五六七八"),
        ("886912345678", "八八六九一二三四五六七八"),
        ("007", "零零七"),
    ],
)
def test_phone_like_strings_are_read_digit_by_digit(text, expected):
    result = normalize_digits(text)
    assert result.text == expected
    assert result.unresolved == ()


def test_full_width_digits_are_treated_as_ascii_digits():
    assert normalize_digits("１５個").text == "十五個"


def test_text_without_digits_is_unchanged():
    result = normalize_digits("你好，Nova。今天天氣很好。")
    assert result.text == "你好，Nova。今天天氣很好。"
    assert result.unresolved == ()
    assert result.resolved


def test_surrounding_text_and_several_numbers_are_kept_in_order():
    result = normalize_digits("2026年有15人，花了3.5小時。")
    assert result.text == "二零二六年有十五人，花了三點五小時。"


@pytest.mark.parametrize(
    ("text", "token", "reason"),
    [
        ("$50", "$50", "currency"),
        ("NT$300", "NT$300", "currency"),
        ("300USD", "300USD", "currency"),
        ("USD 5", "USD 5", "currency"),
        ("12:30", "12:30", "time_or_ratio"),
        ("比例是3:2", "3:2", "time_or_ratio"),
        ("10-20", "10-20", "range"),
        ("5~8", "5~8", "range"),
        ("2026-11-24", "2026-11-24", "numeric_date"),
        ("11/24/2026", "11/24/2026", "numeric_date"),
        ("1/2", "1/2", "slash"),
        ("5kg", "5kg", "mixed_unit"),
        ("3.5GHz", "3.5GHz", "mixed_unit"),
        ("GPT4", "GPT4", "mixed_unit"),
        ("RTX4090", "RTX4090", "mixed_unit"),
        ("COVID-19", "COVID-19", "mixed_unit"),
        ("3x4", "3x4", "mixed_unit"),
        ("1.2.3", "1.2.3", "dotted"),
        ("-5", "-5", "signed"),
        ("+886", "+886", "signed"),
        ("20°C", "20°C", "degree"),
        ("2026", "2026", "ambiguous_year"),
        ("12345", "12345", "ambiguous_long_number"),
        ("1234567", "1234567", "ambiguous_long_number"),
        ("007.5", "007.5", "ambiguous_decimal"),
        ("99999%", "99999%", "ambiguous_long_number"),
    ],
)
def test_undecidable_patterns_are_reported_not_guessed(text, token, reason):
    result = normalize_digits(text)
    assert not result.resolved
    [found] = result.unresolved
    assert found.text == token
    assert found.reason == reason
    # The span points into the original text and the token stays verbatim.
    assert text[found.start : found.end] == token
    assert token in result.text


def test_resolved_and_unresolved_parts_are_mixed_in_one_line():
    text = "15人在12:30開會，共3.5小時"
    result = normalize_digits(text)
    assert result.text == "十五人在12:30開會，共三點五小時"
    [found] = result.unresolved
    assert (found.text, found.reason) == ("12:30", "time_or_ratio")
    assert text[found.start : found.end] == "12:30"


def test_unresolved_positions_survive_earlier_expansions():
    text = "2026年的$50和5kg"
    result = normalize_digits(text)
    assert [u.text for u in result.unresolved] == ["$50", "5kg"]
    assert all(text[u.start : u.end] == u.text for u in result.unresolved)


def test_a_digit_run_is_never_silently_dropped():
    # Every ASCII digit of the output belongs to an unresolved token.
    for text in ["12:30", "5kg和3個", "0.5", "COVID-19有15例", "2026", "10-20人"]:
        result = normalize_digits(text)
        leftover = "".join(ch for ch in result.text if ch.isdigit())
        flagged = "".join(ch for u in result.unresolved for ch in u.text if ch.isdigit())
        assert leftover == flagged, text
