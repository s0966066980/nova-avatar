# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Audio preparation for a training job: conversion of uploads and the quality check.

Two steps, both blocking (run them in the job's worker thread, CODING_STANDARDS 3):

``convert_uploads`` (corpus preparation of an uploaded recording): decode every
confirmed line, whatever its format, to 16 kHz mono PCM16 WAV under
``<workdir>/converted/``. A file that cannot be decoded is excluded from the corpus.

``check_quality``: for every confirmed line, run ``audio_quality.assess_audio``
(trimmed silence, 0.5 to 15 seconds, level and clipping checks, normalised level) on the
converted audio, or on the corpus audio of an Edge line, which is 16 kHz already. The
normalised result goes to ``<workdir>/prepared/<line id>.wav``, the file training reads;
a line that fails is excluded from the corpus and reported with its reasons. The corpus's
own audio is never modified. The Whisper check of what was said is ``transcript_check``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from src.tts.training.audio_quality import SAMPLE_RATE, assess_audio, to_wav_bytes
from src.tts.training.corpus import REVIEW_CONFIRMED, REVIEW_EXCLUDED, CorpusStore
from src.utils.logging import logger

CONVERTED_DIR = "converted"
PREPARED_DIR = "prepared"
REASON_DECODE_FAILED = "decode_failed"

Progress = Callable[[int, int], None]


class DecodeError(ValueError):
    pass


@dataclass(frozen=True)
class Excluded:
    line_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PreparationReport:
    total: int
    done: int
    excluded: tuple[Excluded, ...]
    cancelled: bool


def decode_audio_file(path: Path) -> np.ndarray:
    """Any audio file as mono 16 kHz float32 samples in [-1, 1]; raises ``DecodeError``."""
    chunks: list[np.ndarray] = []
    try:
        container = av.open(str(path))
        try:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                chunks.extend(_pcm(part) for part in resampler.resample(frame))
            chunks.extend(_pcm(part) for part in resampler.resample(None))
        finally:
            container.close()
    except (av.error.FFmpegError, ValueError, OSError, IndexError) as exc:
        raise DecodeError(f"無法解碼音檔：{exc}") from exc
    chunks = [chunk for chunk in chunks if chunk.size]
    if not chunks:
        raise DecodeError("音檔沒有音訊資料")
    return np.concatenate(chunks)


def _pcm(frame) -> np.ndarray:
    return frame.to_ndarray().reshape(-1).astype(np.float32) / 32768.0


def convert_uploads(
    store: CorpusStore,
    slug: str,
    workdir: Path,
    *,
    cancel: threading.Event | None = None,
    on_progress: Progress | None = None,
) -> PreparationReport:
    lines = _confirmed(store, slug)
    out_dir = workdir / CONVERTED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    excluded: list[Excluded] = []
    done = 0
    for line in lines:
        if cancel is not None and cancel.is_set():
            return PreparationReport(len(lines), done, tuple(excluded), True)
        try:
            samples = decode_audio_file(store.audio_path(slug, line.id))
            (out_dir / f"{line.id}.wav").write_bytes(to_wav_bytes(samples))
            done += 1
        except DecodeError as exc:
            logger.info("Excluded line %s of corpus %s: %s", line.id, slug, exc)
            store.set_review(slug, line.id, REVIEW_EXCLUDED)
            excluded.append(Excluded(line.id, (REASON_DECODE_FAILED,)))
        if on_progress is not None:
            on_progress(done + len(excluded), len(lines))
    return PreparationReport(len(lines), done, tuple(excluded), False)


def check_quality(
    store: CorpusStore,
    slug: str,
    workdir: Path,
    *,
    cancel: threading.Event | None = None,
    on_progress: Progress | None = None,
) -> PreparationReport:
    """``done`` counts the lines that passed; the rest are in ``excluded`` with their reasons."""
    lines = _confirmed(store, slug)
    out_dir = workdir / PREPARED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    excluded: list[Excluded] = []
    done = 0
    for index, line in enumerate(lines, start=1):
        if cancel is not None and cancel.is_set():
            return PreparationReport(len(lines), done, tuple(excluded), True)
        converted = workdir / CONVERTED_DIR / f"{line.id}.wav"
        try:
            samples = decode_audio_file(converted if converted.is_file() else store.audio_path(slug, line.id))
            result = assess_audio(samples)
            reasons = result.reasons
        except DecodeError:
            result, reasons = None, (REASON_DECODE_FAILED,)
        if result is not None and result.ok:
            (out_dir / f"{line.id}.wav").write_bytes(to_wav_bytes(result.samples))
            done += 1
        else:
            logger.info("Excluded line %s of corpus %s: %s", line.id, slug, ", ".join(reasons))
            store.set_review(slug, line.id, REVIEW_EXCLUDED)
            excluded.append(Excluded(line.id, tuple(reasons)))
        if on_progress is not None:
            on_progress(index, len(lines))
    return PreparationReport(len(lines), done, tuple(excluded), False)


def prepared_path(workdir: Path, line_id: str) -> Path:
    return workdir / PREPARED_DIR / f"{line_id}.wav"


def _confirmed(store: CorpusStore, slug: str):
    return [line for line in store.get(slug).lines if line.review == REVIEW_CONFIRMED]
