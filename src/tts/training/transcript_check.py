# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# Adapted from tools/tts-distill/audio_qc.py on the jetson-orin branch.
# Modified by HongXian0903, 2026.

"""Whisper comparison hook for a synthesised corpus.

The Edge teacher's own quality check (``audio_quality``) never loads a model. The
check of what was actually said is this hook: the training job (ticket 06)
passes a ``transcribe`` callable that wraps faster-whisper (load the model there,
on the GPU or the CPU as it sees fit, and release it afterwards), and
``verify_with_asr`` excludes every confirmed line whose recognised text is too
different from its transcript. Nothing here loads a model or touches the GPU.

Similarity is the ``difflib`` ratio of the letters and digits of both texts after
converting to Simplified Chinese and lower case, so punctuation and the choice
of Chinese script do not count; the threshold is the inherited 0.65.
"""

from __future__ import annotations

import difflib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from src.tts.training.corpus import REVIEW_CONFIRMED, REVIEW_EXCLUDED, CorpusStore
from src.utils.logging import logger

DEFAULT_MIN_SIMILARITY = 0.65

Transcriber = Callable[[Path], str]
"""Recognised text of one audio file; supplied by the caller (faster-whisper)."""


@dataclass(frozen=True)
class Mismatch:
    line_id: str
    expected: str
    heard: str
    similarity: float


@dataclass(frozen=True)
class TranscriptCheckReport:
    checked: int
    excluded: tuple[Mismatch, ...]
    cancelled: bool


@cache
def _to_simplified():
    from opencc import OpenCC

    return OpenCC("t2s")


def similarity_ratio(expected: str, heard: str) -> float:
    """0.0 to 1.0 similarity of two texts, ignoring punctuation, case and Chinese script."""

    def clean(text: str) -> str:
        return "".join(ch for ch in _to_simplified().convert(text).lower() if ch.isalnum())

    a, b = clean(expected), clean(heard)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def verify_with_asr(
    store: CorpusStore,
    slug: str,
    transcribe: Transcriber,
    *,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> TranscriptCheckReport:
    """Exclude the confirmed lines of ``slug`` whose audio does not match their text.

    Blocking and slow (one recognition per line): call it from the training
    job's worker thread. Errors from ``transcribe`` propagate.
    """
    lines = [line for line in store.get(slug).lines if line.review == REVIEW_CONFIRMED]
    mismatches: list[Mismatch] = []
    checked = 0
    cancelled = False
    for line in lines:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        heard = transcribe(store.audio_path(slug, line.id))
        score = similarity_ratio(line.text, heard)
        checked += 1
        if score < min_similarity:
            store.set_review(slug, line.id, REVIEW_EXCLUDED)
            mismatches.append(Mismatch(line.id, line.text, heard, score))
            logger.info("Excluded line %s of corpus %s: heard text differs (%.2f)", line.id, slug, score)
        if on_progress is not None:
            on_progress(checked, len(lines))
    return TranscriptCheckReport(checked, tuple(mismatches), cancelled)
