# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Sentences for the Edge test teacher: built-in library, presets, administrator lists.

The library lives in ``sentence_data`` (data only). ``select_by_duration`` picks
sentences until their estimated speaking time reaches a target, taking turns
across categories so even a short preset covers greetings, weather, traffic,
colloquial speech, mixed Chinese and English, and digits. The selection is
deterministic and a smaller target is always a prefix of a larger one, so the
"quick test" preset is a subset of the "standard" preset.

The duration is an estimate from an average speaking rate, not a measurement;
the real length of the synthesised audio is only known after synthesis.

An administrator may instead supply a text file (``parse_text_list``): one
sentence per line, UTF-8. No sentence is ever produced by an LLM.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import cache

from nova_tts.training.corpus import MAX_LINES, MAX_TEXT_CHARS, CorpusError
from nova_tts.training.numerals import Unresolved, normalize_digits
from nova_tts.training.sentence_data import CATEGORIES

# Average speaking rates of an Edge zh-TW voice at its default speed.
CJK_CHARS_PER_SECOND = 5.0
ENGLISH_WORDS_PER_SECOND = 2.8
PAUSE_SECONDS_PER_PUNCTUATION = 0.2

MAX_TEXT_LIST_BYTES = 1024 * 1024

_CJK = re.compile(r"[㐀-䶿一-鿿]")
_ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
_PUNCTUATION = re.compile(r"[，。？！、；：,.?!;:]")


@dataclass(frozen=True)
class Sentence:
    text: str
    category: str


@dataclass(frozen=True)
class ReviewedSentence:
    """One sentence of a text list as the administrator reviews it before synthesis.

    ``index`` counts from 1 in the cleaned list (blank and repeated lines dropped), the
    same list a job would synthesise. ``unresolved`` spans index into ``text``.
    """

    index: int
    text: str
    spoken: str
    unresolved: tuple[Unresolved, ...]


@dataclass(frozen=True)
class TextReview:
    """A whole text list reviewed without synthesising anything."""

    sentences: tuple[ReviewedSentence, ...]
    estimated_seconds: float

    @property
    def total(self) -> int:
        return len(self.sentences)

    @property
    def ok(self) -> bool:
        """True when every digit would be read out, so a job may start."""
        return not any(item.unresolved for item in self.sentences)


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    target_seconds: int


PRESETS: dict[str, Preset] = {
    "quick-test": Preset("quick-test", "快速測試", 15 * 60),
    "standard": Preset("standard", "標準", 60 * 60),
}


@cache
def library() -> tuple[Sentence, ...]:
    """Every built-in sentence, category by category."""
    return tuple(Sentence(text, key) for key, _label, texts in CATEGORIES for text in texts)


def category_labels() -> dict[str, str]:
    """Category key to the Traditional Chinese label shown to the administrator."""
    return {key: label for key, label, _texts in CATEGORIES}


def estimate_seconds(text: str) -> float:
    """Estimated speaking time of ``text`` once its digits are read out."""
    spoken = normalize_digits(text).text
    return (
        len(_CJK.findall(spoken)) / CJK_CHARS_PER_SECOND
        + len(_ENGLISH_WORD.findall(spoken)) / ENGLISH_WORDS_PER_SECOND
        + len(_PUNCTUATION.findall(spoken)) * PAUSE_SECONDS_PER_PUNCTUATION
    )


def select_by_duration(target_seconds: float) -> list[str]:
    """Library sentences, categories taking turns, until the estimate reaches the target."""
    if not target_seconds > 0:
        raise CorpusError("目標長度必須大於零")
    queues = [[item.text for item in library() if item.category == key] for key, _l, _t in CATEGORIES]
    chosen: list[str] = []
    total = 0.0
    depth = 0
    while total < target_seconds and any(depth < len(queue) for queue in queues):
        for queue in queues:
            if depth < len(queue) and total < target_seconds:
                chosen.append(queue[depth])
                total += estimate_seconds(queue[depth])
        depth += 1
    return chosen


def select_preset(key: str) -> list[str]:
    """The sentences of a preset in ``PRESETS``.

    The built-in library needs no proofreading (spec decision 13), so the guarantee that
    every digit in it is read out is checked here on every selection, not only by a test.
    """
    preset = PRESETS.get(key) if isinstance(key, str) else None
    if preset is None:
        raise CorpusError("不明的份量預設")
    chosen = select_by_duration(preset.target_seconds)
    unresolved = [text for text in chosen if not normalize_digits(text).resolved]
    if unresolved:
        raise CorpusError(f"內建句庫有無法展開數字的句子（「{unresolved[0]}」等 {len(unresolved)} 句），請回報給維護者", 500)
    return chosen


def parse_text_list(raw: str | bytes) -> list[str]:
    """Sentences from an administrator-supplied text file, one per line, in order.

    Blank lines and repeated sentences are dropped; the file must be UTF-8 and
    free of control characters, with at most ``MAX_LINES`` sentences of
    ``MAX_TEXT_CHARS`` characters each.
    """
    if isinstance(raw, bytes | bytearray):
        if len(raw) > MAX_TEXT_LIST_BYTES:
            raise CorpusError("文字檔太大", status=413)
        try:
            raw = bytes(raw).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise CorpusError("文字檔必須是 UTF-8 編碼") from None
    elif not isinstance(raw, str):
        raise CorpusError("文字檔必須是文字")
    elif len(raw.encode("utf-8")) > MAX_TEXT_LIST_BYTES:
        raise CorpusError("文字檔太大", status=413)
    sentences: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(raw.lstrip("﻿").splitlines(), start=1):
        if any(unicodedata.category(ch) == "Cc" and not ch.isspace() for ch in line):
            raise CorpusError(f"第 {number} 行含有控制字元")
        text = " ".join(line.split())
        if not text:
            continue
        if len(text) > MAX_TEXT_CHARS:
            raise CorpusError(f"第 {number} 行超過 {MAX_TEXT_CHARS} 字")
        if text not in seen:
            seen.add(text)
            sentences.append(text)
    if not sentences:
        raise CorpusError("文字檔裡沒有任何句子")
    if len(sentences) > MAX_LINES:
        raise CorpusError(f"文字檔最多 {MAX_LINES} 句")
    return sentences


def refusal_for_unresolved(review: TextReview) -> CorpusError | None:
    """A 409 naming every sentence and fragment whose digits cannot be read out, ``None`` if there is none."""
    listing = "；".join(
        f"第 {item.index} 句「{fragment.text}」" for item in review.sentences for fragment in item.unresolved
    )
    if not listing:
        return None
    return CorpusError(f"有數字無法確定怎麼念，請先改寫或移除再開始：{listing}", 409)


def review_text_list(raw: str | bytes) -> TextReview:
    """Parse an administrator's text list and expand its digits, touching nothing else.

    The sentences and the limits are those of ``parse_text_list``; the expansion is that
    of ``normalize_digits``, so the review shows what a job would synthesise.
    """
    reviewed: list[ReviewedSentence] = []
    seconds = 0.0
    for index, text in enumerate(parse_text_list(raw), start=1):
        normalised = normalize_digits(text)
        reviewed.append(ReviewedSentence(index, text, normalised.text, normalised.unresolved))
        seconds += estimate_seconds(text)
    return TextReview(tuple(reviewed), seconds)
