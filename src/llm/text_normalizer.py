# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Deterministic, post-protocol normalization for LLM output."""

from __future__ import annotations

import re

from opencc import OpenCC

_TW = OpenCC("s2twp")
_SELF_IDENTITY = re.compile(
    r"(?P<prefix>(?:我(?:是|叫)|我的名字是|\bI am|\bI'm|\bI’m|\bMy name is)\s*)"
    r"(?P<name>[^，。！？.!?\n]{1,80})", re.IGNORECASE,
)
_IDENTITY_QUESTION = re.compile(
    r"你是誰|你叫什麼|你的(?:名字|名稱|身份)|自我介紹|介紹你自己"
    r"|introduce\s+yourself|who\s+are\s+you|what(?:'s|\s+is)\s+your\s+name", re.IGNORECASE,
)

_EN_UNITS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_EN_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_EN_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_EN_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}
_EN_ALL_NUM_WORDS = (
    tuple(_EN_UNITS) + tuple(_EN_TEENS) + tuple(_EN_TENS) + tuple(_EN_SCALES)
)
_EN_WORD_ALT = "|".join(sorted(_EN_ALL_NUM_WORDS, key=len, reverse=True))
_EN_NUMBER_PHRASE = re.compile(
    rf"\b(?:(?:minus|negative)\s+)?(?:a\s+(?=(?:hundred|thousand|million|billion)\b)|(?:{_EN_WORD_ALT})\b)"
    rf"(?:(?:[\s-]+|\s+and\s+)(?:{_EN_WORD_ALT})\b)*"
    rf"(?:\s+point(?:\s+(?:{_EN_WORD_ALT})\b)+)?",
    re.IGNORECASE,
)
_EN_SINGLE_ONE_FOLLOWING_UNITS = re.compile(
    r"^\s*(?:percent|%|°[cf]|degrees?\b|celsius\b|fahrenheit\b|hours?\b|minutes?\b|seconds?\b"
    r"|meters?\b|kilometers?\b|millimeters?\b|centimeters?\b|grams?\b|kilograms?\b|dollars?\b"
    r"|steps?\b|items?\b|points?\b)",
    re.IGNORECASE,
)


def _eval_en_int_tokens(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    total = 0
    current = 0
    has_scale_or_value = False
    for token in tokens:
        if token == "and":
            continue
        if token == "a":
            current = max(current, 1)
            continue
        if token in _EN_UNITS:
            if current % 10 != 0 or 10 <= (current % 100) < 20:
                return None
            current += _EN_UNITS[token]
            has_scale_or_value = True
        elif token in _EN_TEENS:
            if current % 100 != 0:
                return None
            current += _EN_TEENS[token]
            has_scale_or_value = True
        elif token in _EN_TENS:
            if current % 100 != 0:
                return None
            current += _EN_TENS[token]
            has_scale_or_value = True
        elif token == "hundred":
            current = (current or 1) * 100
            has_scale_or_value = True
        elif token in _EN_SCALES:
            total += (current or 1) * _EN_SCALES[token]
            current = 0
            has_scale_or_value = True
        else:
            return None
    if not has_scale_or_value:
        return None
    return str(total + current)


def normalize_english_numbers(text: str) -> str:
    """Convert spelled-out English cardinal numbers into Arabic numerals for captions."""
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        tokens = [t.lower() for t in re.findall(r"[a-zA-Z]+", raw)]
        if not tokens:
            return raw

        negative = False
        if tokens[0] in {"minus", "negative"}:
            negative = True
            tokens = tokens[1:]
        if not tokens:
            return raw

        # Keep idiomatic or pronoun uses of standalone "one" (e.g. "one of", "this one").
        if tokens == ["one"] and not negative:
            tail = text[match.end() :]
            if not _EN_SINGLE_ONE_FOLLOWING_UNITS.search(tail):
                return raw

        # Only treat "and" as part of a single number when preceded by a scale word.
        for idx, tok in enumerate(tokens):
            if tok == "and":
                if idx == 0 or idx == len(tokens) - 1 or tokens[idx - 1] not in _EN_SCALES:
                    return raw

        if "point" in tokens:
            point_idx = tokens.index("point")
            int_tokens = tokens[:point_idx]
            dec_tokens = tokens[point_idx + 1 :]
            if not int_tokens or not dec_tokens or "point" in dec_tokens:
                return raw
            int_str = _eval_en_int_tokens(int_tokens)
            if int_str is None:
                return raw
            dec_parts: list[str] = []
            for dtok in dec_tokens:
                if dtok in _EN_UNITS:
                    dec_parts.append(str(_EN_UNITS[dtok]))
                elif dtok in _EN_TEENS:
                    dec_parts.append(str(_EN_TEENS[dtok]))
                elif dtok in _EN_TENS:
                    dec_parts.append(str(_EN_TENS[dtok]))
                else:
                    return raw
            return f"{'-' if negative else ''}{int_str}.{''.join(dec_parts)}"

        int_str = _eval_en_int_tokens(tokens)
        if int_str is None:
            return raw
        return f"{'-' if negative else ''}{int_str}"

    return _EN_NUMBER_PHRASE.sub(_replace, text)


def join_spoken_fragments(fragments) -> str:
    """Keep Latin sentence spacing when individually trimmed speech is committed."""
    result = ''
    for text in fragments:
        if (result and text and result[-1] in '.!?,;:'
                and text[0].isascii() and text[0].isalnum()):
            result += ' '
        result += text
    return result


def strip_unsolicited_self_introduction(
    text: str, *, user_message: str, assistant_name: str
) -> str:
    """Remove only an opening self-introduction when the user did not ask for it."""
    if not text or not assistant_name or _IDENTITY_QUESTION.search(user_message or ""):
        return text
    name = re.escape(assistant_name.strip())
    if not name:
        return text
    leading_intro = re.compile(
        rf"^\s*(?:您好[，,！!。\s]*)?(?:我(?:是|叫)|我的名字是)\s*{name}"
        r"(?:[，,。！!、\s]+(?:很高興(?:為您)?服務|很高興認識您|我可以協助您)[，,。！!、\s]*)?"
    )
    stripped = leading_intro.sub("", text)
    if stripped == text:
        return text
    stripped = stripped.lstrip("，,。！!、 \n")
    return stripped or text


def normalize_output_text(text: str, *, locale: str = "zh-TW", enabled: bool = True) -> str:
    """Convert human-readable output after protocol parsing, not raw LLM output."""
    if not text or not enabled:
        return text
    loc = locale.lower()
    if loc == "en-us":
        return normalize_english_numbers(text)
    if loc != "zh-tw":
        return text
    # OpenCC's Taiwan phrase dictionary chooses 「影片」 for 视频. The product
    # output convention is 「視訊」, so apply that deterministic final term map.
    return _TW.convert(text).replace("影片", "視訊")


def normalize_assistant_identity(
    text: str, *, assistant_name: str, forbidden_names: list[str]
) -> str:
    """Replace forbidden names only in an explicit first-person identity claim."""
    if not text or not assistant_name:
        return text
    forbidden = [name.strip() for name in forbidden_names if str(name).strip()]
    if not forbidden:
        return text

    def replace(match: re.Match[str]) -> str:
        claimed = match.group("name").strip()
        if any(name in claimed for name in forbidden):
            return f"{match.group('prefix')}{assistant_name}"
        return match.group(0)

    return _SELF_IDENTITY.sub(replace, text)
