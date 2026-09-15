# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Incremental semantic text fragmentation for reply speech."""
from __future__ import annotations

import re
import time
import unicodedata

STRONG_PUNCTUATION = frozenset("。！？.!?…")
WEAK_PUNCTUATION = frozenset("，、：,:；;")
CLOSING_PUNCTUATION = frozenset("\"'”’」』）》】〕〉>)]}")
OPENING_DELIMITERS = {
    "「": "」",
    "『": "』",
    "“": "”",
    "‘": "’",
    "（": "）",
    "(": ")",
    "[": "]",
    "{": "}",
}

_PROTECTED_INLINE_TOKEN = re.compile(
    r"(?:https?://|www\.)[^\s，、：,。！？；!?;）」』】》…]+"
    r"|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?<![A-Za-z])v?\d+(?:[.,]\d+)+(?![A-Za-z])"
    r"|(?<![@\w])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s]*)?"
    r"|(?<![A-Za-z])(?:e\.g|i\.e|Mr|Mrs|Ms|Dr|vs)\.(?![A-Za-z])",
    re.IGNORECASE,
)


def _grapheme_spans(text: str) -> list[tuple[int, int]]:
    """Return approximate Unicode grapheme spans without splitting emoji marks."""
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    previous = ""
    for index, character in enumerate(text):
        if index and _starts_new_grapheme(previous, character):
            spans.append((start, index))
            start = index
        previous = character
    spans.append((start, len(text)))
    return spans


def _starts_new_grapheme(previous: str, character: str) -> bool:
    if previous == "\u200d" or unicodedata.combining(character):
        return False
    codepoint = ord(character)
    if 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF:
        return False
    if 0x1F3FB <= codepoint <= 0x1F3FF:
        return False
    return True


def _content_length(text: str) -> int:
    return sum(
        any(character.isalnum() for character in text[start:end])
        for start, end in _grapheme_spans(text)
    )


class SemanticFragmenter:
    """Turn arbitrary LLM token boundaries into playable text fragments."""

    def __init__(
        self,
        *,
        weak_min_chars: int = 24,
        soft_limit_chars: int = 72,
        hard_limit_chars: int = 120,
        strong_min_chars: int = 1,
        semantic_wait_seconds: float = 5.0,
        clock=time.monotonic,
    ) -> None:
        if weak_min_chars < 1:
            raise ValueError("weak punctuation threshold must be positive")
        if soft_limit_chars < weak_min_chars:
            raise ValueError("soft limit cannot be below weak punctuation threshold")
        if hard_limit_chars < soft_limit_chars:
            raise ValueError("hard limit cannot be below soft limit")
        if strong_min_chars < 1:
            raise ValueError("strong punctuation threshold must be positive")
        if strong_min_chars > hard_limit_chars:
            raise ValueError("strong punctuation threshold cannot exceed hard limit")
        if semantic_wait_seconds <= 0:
            raise ValueError("semantic wait must be positive")
        self._weak_min_chars = weak_min_chars
        self._soft_limit_chars = soft_limit_chars
        self._hard_limit_chars = hard_limit_chars
        self._strong_min_chars = strong_min_chars
        self._buffer = ""
        self._semantic_wait_seconds = float(semantic_wait_seconds)
        self._clock = clock
        self._buffer_started_at: float | None = None
        self._wait_boundary_offset: int | None = None

    @property
    def buffered_text(self) -> str:
        return self._buffer

    def feed(self, token: str) -> list[str]:
        if token:
            if self._semantic_wait_expired() and self._wait_boundary_offset is None:
                self._wait_boundary_offset = len(self._buffer)
            if not self._buffer:
                self._buffer_started_at = self._clock()
            self._buffer += token
        fragments: list[str] = []
        while self._buffer:
            split_at = self._strong_boundary()
            if split_at is None and self._semantic_wait_expired():
                split_at = self._weak_boundary(self._wait_boundary_offset)
            if split_at is None:
                break
            fragment = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:]
            self._buffer_started_at = self._clock() if self._buffer else None
            self._wait_boundary_offset = None
            if fragment:
                fragments.append(fragment)
        return fragments

    def flush(self) -> list[str]:
        fragment = self._buffer.strip()
        self._buffer = ""
        self._buffer_started_at = None
        self._wait_boundary_offset = None
        return [fragment] if fragment else []

    def _semantic_wait_expired(self) -> bool:
        return (
            self._buffer_started_at is not None
            and self._clock() - self._buffer_started_at >= self._semantic_wait_seconds
        )

    def _strong_boundary(self) -> int | None:
        for index, character in enumerate(self._buffer):
            if self._is_protected_punctuation(index):
                continue
            if character not in STRONG_PUNCTUATION:
                continue
            boundary = index + 1
            if _content_length(self._buffer[:boundary]) < self._strong_min_chars:
                continue
            if boundary == len(self._buffer) and self._has_unclosed_delimiter(boundary):
                continue
            while boundary < len(self._buffer):
                if self._buffer[boundary] in STRONG_PUNCTUATION | CLOSING_PUNCTUATION:
                    boundary += 1
                    continue
                break
            return boundary
        return None

    def _weak_boundary(self, minimum_offset: int | None = None) -> int | None:
        last = None
        for index, character in enumerate(self._buffer):
            if self._is_protected_punctuation(index) or character not in WEAK_PUNCTUATION:
                continue
            boundary = index + 1
            if minimum_offset is not None and boundary <= minimum_offset:
                continue
            length = _content_length(self._buffer[:boundary])
            if length < self._weak_min_chars:
                continue
            return boundary
        return last

    def _length_boundary(self) -> int | None:
        content_chars = 0
        hard_boundary = None
        for start, end in _grapheme_spans(self._buffer):
            content_chars += any(
                character.isalnum() for character in self._buffer[start:end]
            )
            if content_chars < self._hard_limit_chars:
                continue
            if hard_boundary is None:
                hard_boundary = end
            if self._is_safe_boundary(end):
                return end
        return hard_boundary

    def _is_protected_punctuation(self, index: int) -> bool:
        if self._buffer[index] not in STRONG_PUNCTUATION | WEAK_PUNCTUATION:
            return False
        if self._is_numeric_punctuation(index):
            return True
        prefix = self._buffer[:index]
        if prefix.rfind("<") > prefix.rfind(">") or prefix.count("`") % 2:
            return True
        for match in _PROTECTED_INLINE_TOKEN.finditer(self._buffer):
            end = match.end()
            token = match.group(0).lower()
            if (
                self._buffer[index] == "."
                and end == len(self._buffer)
                and token.startswith(("http://", "https://", "www."))
            ):
                if match.start() <= index < end:
                    return True
            while end > match.start() and self._buffer[end - 1] in STRONG_PUNCTUATION:
                end -= 1
            if match.start() <= index < end:
                return True
        return False

    def _has_unclosed_delimiter(self, boundary: int) -> bool:
        prefix = self._buffer[:boundary]
        for opening, closing in OPENING_DELIMITERS.items():
            if prefix.count(opening) > prefix.count(closing):
                return True
        return prefix.count('"') % 2 == 1

    def _is_numeric_punctuation(self, index: int) -> bool:
        if self._buffer[index] not in STRONG_PUNCTUATION | WEAK_PUNCTUATION:
            return False
        if index == 0 or index + 1 >= len(self._buffer):
            return False
        return self._buffer[index - 1].isdigit() and self._buffer[index + 1].isdigit()

    def _is_safe_boundary(self, boundary: int) -> bool:
        if boundary <= 0 or boundary > len(self._buffer):
            return False
        left = self._buffer[boundary - 1]
        if boundary >= len(self._buffer):
            return left.isspace()
        right = self._buffer[boundary]
        return left.isspace() or right.isspace()
