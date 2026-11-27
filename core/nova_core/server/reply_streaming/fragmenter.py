# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Incremental semantic text fragmentation for reply speech."""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from typing import Callable

STRONG_PUNCTUATION = frozenset("。！？.!?…")
WEAK_PUNCTUATION = frozenset("，、：,:；;")
# The first fragment of a turn may end at a clause mark (not the list comma 、).
FIRST_CLAUSE_PUNCTUATION = frozenset("，：；,:;")
FIRST_FRAGMENT_MIN_UNITS = 8
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


def _is_wide(character: str) -> bool:
    return unicodedata.east_asian_width(character) in ("W", "F")


def speech_units(text: str) -> int:
    """Count spoken units: one per CJK character and one per Latin word or number.

    ``content_length`` counts every letter, so eight units would be two short
    English words; a word is closer to what one Chinese character says.
    """
    units = 0
    in_word = False
    for start, end in _grapheme_spans(text):
        grapheme = text[start:end]
        if in_word and grapheme in ("'", "’", "-"):
            continue
        if not any(character.isalnum() for character in grapheme):
            in_word = False
        elif _is_wide(grapheme[0]):
            units += 1
            in_word = False
        elif not in_word:
            units += 1
            in_word = True
    return units


def content_length(text: str) -> int:
    """Count the letters, digits and CJK characters the fragment thresholds use."""
    return sum(
        any(character.isalnum() for character in text[start:end])
        for start, end in _grapheme_spans(text)
    )


class SemanticFragmenter:
    """Turn arbitrary LLM token boundaries into playable text fragments.

    Fragments end at a complete semantic boundary, except the first one: it
    may end at a comma, colon or semicolon once the clause before it has
    ``first_fragment_min_units`` spoken units, without the semantic wait.
    ``None`` turns that exception off.
    """

    def __init__(
        self,
        *,
        weak_min_chars: int = 24,
        soft_limit_chars: int = 72,
        hard_limit_chars: int = 120,
        strong_min_chars: int = 1,
        semantic_wait_seconds: float = 0.5,
        first_fragment_min_units: int | None = FIRST_FRAGMENT_MIN_UNITS,
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
        if first_fragment_min_units is not None and first_fragment_min_units < 1:
            raise ValueError("first fragment threshold must be positive")
        self._weak_min_chars = weak_min_chars
        self._soft_limit_chars = soft_limit_chars
        self._hard_limit_chars = hard_limit_chars
        self._strong_min_chars = strong_min_chars
        self._buffer = ""
        self._semantic_wait_seconds = float(semantic_wait_seconds)
        self._clock = clock
        self._buffer_started_at: float | None = None
        self._first_fragment_min_units = first_fragment_min_units
        self._emitted = False

    @property
    def buffered_text(self) -> str:
        return self._buffer

    def feed(self, token: str) -> list[str]:
        if token:
            if not self._buffer:
                self._buffer_started_at = self._clock()
            self._buffer += token
        fragments: list[str] = []
        while self._buffer:
            split_at = self._strong_boundary()
            first_clause = self._first_clause_boundary()
            if first_clause is not None and (split_at is None or first_clause < split_at):
                split_at = first_clause
            if split_at is None and self._semantic_wait_expired():
                split_at = self._weak_boundary()
            if split_at is None:
                break
            fragment = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:]
            self._buffer_started_at = self._clock() if self._buffer else None
            if fragment:
                fragments.append(fragment)
                self._emitted = True
        return fragments

    def flush(self) -> list[str]:
        fragment = self._buffer.strip()
        self._buffer = ""
        self._buffer_started_at = None
        if not fragment:
            return []
        self._emitted = True
        return [fragment]

    def semantic_wait_remaining(self) -> float | None:
        """Seconds until ``feed("")`` releases a clause at weak punctuation.

        ``None`` while no clause is long enough to be released by the wait.
        """
        if self._buffer_started_at is None or self._weak_boundary() is None:
            return None
        elapsed = self._clock() - self._buffer_started_at
        return max(0.0, self._semantic_wait_seconds - elapsed)

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
            if content_length(self._buffer[:boundary]) < self._strong_min_chars:
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

    def _first_clause_boundary(self) -> int | None:
        """End of the first fragment's opening clause, or ``None``.

        A Latin mark (``,`` ``:`` ``;``) counts only once the next character
        shows it is not inside a number, time or URL: a space or CJK text.
        """
        if self._emitted or self._first_fragment_min_units is None:
            return None
        for index, character in enumerate(self._buffer):
            if (
                character not in FIRST_CLAUSE_PUNCTUATION
                or self._is_protected_punctuation(index)
            ):
                continue
            boundary = index + 1
            if not _is_wide(character):
                if boundary >= len(self._buffer):
                    return None
                following = self._buffer[boundary]
                if not (following.isspace() or _is_wide(following)):
                    continue
            if speech_units(self._buffer[:boundary]) < self._first_fragment_min_units:
                continue
            if self._has_unclosed_delimiter(boundary):
                continue
            return boundary
        return None

    def _weak_boundary(self) -> int | None:
        for index, character in enumerate(self._buffer):
            if self._is_protected_punctuation(index) or character not in WEAK_PUNCTUATION:
                continue
            boundary = index + 1
            length = content_length(self._buffer[:boundary])
            if length < self._weak_min_chars:
                continue
            return boundary
        return None

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


class SemanticWaitTimer:
    """Release a waiting clause when the semantic wait ends, not when a token arrives.

    Fragments reach ``emit`` from the caller's thread for fed text and from a
    timer thread when the wait expires; one lock keeps them in order and never
    concurrent. ``active`` is checked before a timed release so a fenced turn
    stays silent. ``close`` stops the timer; fragments are never emitted after it.
    """

    def __init__(
        self,
        fragmenter: SemanticFragmenter,
        emit: Callable[[str], None],
        *,
        active: Callable[[], bool] = lambda: True,
    ) -> None:
        self._fragmenter = fragmenter
        self._emit = emit
        self._active = active
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._generation = 0
        self._closed = False

    def feed(self, token: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._emit_all(self._fragmenter.feed(token))
            self._schedule()

    def flush(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._cancel()
            self._emit_all(self._fragmenter.flush())

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cancel()

    def _expire(self, generation: int) -> None:
        with self._lock:
            # A timer cancelled while waiting for the lock must not fire.
            if generation != self._generation:
                return
            self._timer = None
            if self._closed or not self._active():
                return
            self._emit_all(self._fragmenter.feed(""))
            self._schedule()

    def _emit_all(self, fragments: list[str]) -> None:
        for fragment in fragments:
            self._emit(fragment)

    def _schedule(self) -> None:
        self._cancel()
        remaining = self._fragmenter.semantic_wait_remaining()
        if remaining is None:
            return
        self._timer = threading.Timer(remaining, self._expire, args=(self._generation,))
        self._timer.daemon = True
        self._timer.start()

    def _cancel(self) -> None:
        self._generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
