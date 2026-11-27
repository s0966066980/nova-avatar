# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# Adapted from tools/tts-distill/distill_edge_teacher.py on the jetson-orin branch.
# Modified by HongXian0903, 2026.

"""Edge test teacher (測試用老師): synthesise training sentences into a corpus.

DEVELOPMENT ONLY. Audio synthesised from Edge read-aloud output is subject to
Microsoft's service terms (ADR 0026): a corpus filled here has the source
``edge-test-teacher``, a model trained from it is labelled Development only and
is never exported. The service refuses to start unless the corpus carries the
recorded MSA acknowledgement (``edge_acknowledgement.require_acknowledgement``);
it never creates that record.

This is the service layer a background job calls (no routes, no GPU, no model):

``synthesize_corpus`` (a coroutine) and ``run_synthesis`` (the same, blocking, for
a worker thread) take the sentences (``sentences.select_preset`` or
``sentences.parse_text_list``), one at a time:

1. digits are expanded through ``numerals.normalize_digits``; Edge is asked to
   read the expanded text and the line stores it. A list holding digits the
   normaliser cannot decide is refused before any request (409), so Edge never reads
   a guess and nothing unreviewed can be trained;
2. ``EdgeConnectionPool.stream(text, voice)`` returns MP3, retried with doubling
   backoff on failure (``MAX_ATTEMPTS``, ``BASE_BACKOFF_SECONDS`` up to
   ``MAX_BACKOFF_SECONDS``, a longer ``Retry-After`` wins), and the run waits
   ``SENTENCE_DELAY_SECONDS`` between sentences so Edge does not rate-limit it;
3. the MP3 is decoded to 16 kHz mono, checked and normalised by
   ``audio_quality.assess_audio`` and stored as a PCM16 WAV line. Audio that
   fails the check is not stored; a decoded, resolved sentence is stored
   ``confirmed`` because its text is exactly what was spoken.

The Whisper comparison is a separate step (``transcript_check``), because it
needs a heavy model that this layer never loads.

Cancellation is a ``threading.Event`` checked between sentences and during
waits. Progress is reported after every sentence through a callback. Sentences
the corpus already holds are skipped, so a cancelled or aborted run can be
repeated. ``MAX_CONSECUTIVE_FAILURES`` sentences in a row that exhaust their
attempts abort the run (Edge is probably blocking the client).
"""

from __future__ import annotations

import asyncio
import io
import threading
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import aiohttp
import av
import numpy as np
from edge_tts.exceptions import EdgeTTSException

from nova_tts.edge_connection import EdgeConnectionPool
from nova_tts.training.audio_quality import SAMPLE_RATE, assess_audio, to_wav_bytes
from nova_tts.training.corpus import REVIEW_CONFIRMED, CorpusError, CorpusStore
from nova_tts.training.edge_acknowledgement import require_acknowledgement
from nova_tts.training.numerals import normalize_digits
from nova_tts.training.sentences import refusal_for_unresolved, review_text_list
from nova_core.utils.logging import logger

# The Edge zh-TW voices; English lines are read by the same voice. Kept equal to
# ``runtime_settings.EDGE_TTS_ZH_TW_VOICES`` by a test.
EDGE_ZH_TW_VOICES = (
    "zh-TW-HsiaoChenNeural",
    "zh-TW-HsiaoYuNeural",
    "zh-TW-YunJheNeural",
)
DEFAULT_VOICE = EDGE_ZH_TW_VOICES[0]

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 4.0
MAX_BACKOFF_SECONDS = 60.0
SENTENCE_DELAY_SECONDS = 0.35
MAX_CONSECUTIVE_FAILURES = 3
# Waits are taken in slices so a cancel is noticed within this time.
PAUSE_SLICE_SECONDS = 0.25

STATUS_STORED = "stored"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

REASON_DECODE_FAILED = "decode_failed"
REASON_SYNTHESIS_FAILED = "synthesis_failed"

_RETRYABLE = (
    aiohttp.ClientError,
    # Python 3.10 keeps asyncio.TimeoutError distinct from the builtin one.
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
    RuntimeError,
    EdgeTTSException,
)


class DecodeError(ValueError):
    """Edge audio could not be decoded."""


class _EmptyAudio(RuntimeError):
    pass


@dataclass(frozen=True)
class Progress:
    """What happened to one sentence; ``line_id`` is set when a line was stored."""

    index: int
    total: int
    text: str
    status: str
    reason: str | None = None
    line_id: str | None = None


@dataclass(frozen=True)
class SynthesisReport:
    total: int
    stored: int
    needs_review: int
    rejected: int
    failed: int
    skipped: int
    cancelled: bool
    aborted: bool
    outcomes: tuple[Progress, ...]


ProgressCallback = Callable[[Progress], None]
Decoder = Callable[[bytes], np.ndarray]
Sleeper = Callable[[float], Awaitable[None]]


def decode_mp3_to_float(data: bytes) -> np.ndarray:
    """Decode Edge MP3 bytes to mono 16 kHz float32 samples in [-1, 1]."""
    if not data:
        raise DecodeError("沒有音訊資料")
    chunks: list[np.ndarray] = []
    try:
        container = av.open(io.BytesIO(data), format="mp3")
        try:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                chunks.extend(_pcm(resampled) for resampled in resampler.resample(frame))
            chunks.extend(_pcm(resampled) for resampled in resampler.resample(None))
        finally:
            container.close()
    except (av.error.FFmpegError, ValueError, OSError) as exc:
        raise DecodeError(f"無法解碼 Edge 音訊：{exc}") from exc
    chunks = [chunk for chunk in chunks if chunk.size]
    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)


def _pcm(frame) -> np.ndarray:
    return frame.to_ndarray().reshape(-1).astype(np.float32) / 32768.0


def run_synthesis(*args, **kwargs) -> SynthesisReport:
    """``synthesize_corpus`` for a worker thread: runs it on its own event loop."""
    return asyncio.run(synthesize_corpus(*args, **kwargs))


async def synthesize_corpus(
    store: CorpusStore,
    slug: str,
    sentences: Sequence[str],
    *,
    voice: str = DEFAULT_VOICE,
    pool: EdgeConnectionPool | None = None,
    cancel: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
    decode: Decoder = decode_mp3_to_float,
    sleep: Sleeper = asyncio.sleep,
    delay_seconds: float = SENTENCE_DELAY_SECONDS,
    max_attempts: int = MAX_ATTEMPTS,
    base_backoff: float = BASE_BACKOFF_SECONDS,
) -> SynthesisReport:
    """Synthesise ``sentences`` into the Edge corpus ``slug``; see the module docs.

    Raises ``CorpusError`` (403) before any request when the corpus has no valid
    MSA acknowledgement, and for an unknown voice or an unusable sentence list; a list
    with digits that cannot be read out (409) is refused as a whole, before the first request.
    A caller-supplied ``pool`` is left open; otherwise one is opened and closed here.
    """
    require_acknowledgement(store, slug)
    if voice not in EDGE_ZH_TW_VOICES:
        raise CorpusError("不明的 Edge 聲音")
    review = review_text_list("\n".join(sentences))
    refusal = refusal_for_unresolved(review)
    if refusal is not None:  # never ask Edge to read a guess; the job layer refuses first, this is the last gate
        raise refusal
    sentences = [item.text for item in review.sentences]
    existing = {line.text for line in store.get(slug).lines}

    owned = pool is None
    pool = EdgeConnectionPool(max_idle=1) if pool is None else pool
    outcomes: list[Progress] = []
    cancelled = aborted = False
    consecutive_failures = 0
    try:
        for index, text in enumerate(sentences, start=1):
            if _is_set(cancel):
                cancelled = True
                break
            normalised = normalize_digits(text)
            spoken = normalised.text if normalised.resolved else text
            if spoken in existing:
                outcome = Progress(index, len(sentences), text, STATUS_SKIPPED)
            else:
                audio = await _fetch_audio(pool, spoken, voice, cancel, sleep, max_attempts, base_backoff)
                if audio is _CANCELLED:
                    cancelled = True
                    break
                if audio is None:
                    outcome = Progress(index, len(sentences), text, STATUS_FAILED, REASON_SYNTHESIS_FAILED)
                else:
                    outcome = await asyncio.to_thread(
                        _ingest, store, slug, index, len(sentences), text, spoken, normalised, audio, voice, decode
                    )
            outcomes.append(outcome)
            if outcome.status == STATUS_STORED or outcome.status == STATUS_NEEDS_REVIEW:
                existing.add(spoken)
            _notify(on_progress, outcome)
            if outcome.status == STATUS_FAILED:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    aborted = True
                    logger.warning("Edge teacher aborted after %d failed sentences in a row", consecutive_failures)
                    break
            elif outcome.status != STATUS_SKIPPED:
                consecutive_failures = 0
            if outcome.status != STATUS_SKIPPED and index < len(sentences) and delay_seconds > 0:
                if await _pause(delay_seconds, cancel, sleep):
                    cancelled = True
                    break
    finally:
        if owned:
            await pool.close()

    def count(status: str) -> int:
        return sum(1 for outcome in outcomes if outcome.status == status)

    return SynthesisReport(
        total=len(sentences),
        stored=count(STATUS_STORED),
        needs_review=count(STATUS_NEEDS_REVIEW),
        rejected=count(STATUS_REJECTED),
        failed=count(STATUS_FAILED),
        skipped=count(STATUS_SKIPPED),
        cancelled=cancelled,
        aborted=aborted,
        outcomes=tuple(outcomes),
    )


_CANCELLED = object()


async def _fetch_audio(pool, text, voice, cancel, sleep, max_attempts, base_backoff):
    """MP3 bytes for ``text``; ``None`` after the last failed attempt, ``_CANCELLED`` on cancel."""
    delay = base_backoff
    for attempt in range(1, max_attempts + 1):
        try:
            buffer = bytearray()
            async for chunk in pool.stream(text, voice):
                if chunk.get("type") == "audio":
                    buffer.extend(chunk["data"])
            if not buffer:
                raise _EmptyAudio("Edge returned no audio")
            return bytes(buffer)
        except _RETRYABLE as exc:
            status = getattr(exc, "status", None)
            if attempt >= max_attempts:
                logger.warning(
                    "Edge teacher gave up on a sentence after %d attempts type=%s status=%s",
                    attempt, type(exc).__name__, status,
                )
                return None
            wait = max(delay, _retry_after(exc))
            logger.info(
                "Edge teacher retry %d/%d type=%s status=%s wait=%.1fs",
                attempt, max_attempts, type(exc).__name__, status, wait,
            )
            if await _pause(wait, cancel, sleep):
                return _CANCELLED
            delay = min(MAX_BACKOFF_SECONDS, delay * 2.0)
    return None


def _retry_after(exc: BaseException) -> float:
    headers = getattr(exc, "headers", None) or {}
    try:
        return max(0.0, float(headers.get("Retry-After", 0.0)))
    except (TypeError, ValueError):
        return 0.0


async def _pause(seconds: float, cancel: threading.Event | None, sleep: Sleeper) -> bool:
    """Wait ``seconds`` in short slices; ``True`` if cancelled meanwhile."""
    remaining = seconds
    while remaining > 0:
        if _is_set(cancel):
            return True
        step = min(remaining, PAUSE_SLICE_SECONDS)
        await sleep(step)
        remaining -= step
    return _is_set(cancel)


def _ingest(store, slug, index, total, text, spoken, normalised, audio, voice, decode) -> Progress:
    """Decode, check and store one synthesised sentence (blocking; run in a thread)."""
    try:
        samples = decode(audio)
    except DecodeError as exc:
        logger.info("Edge teacher audio not decodable: %s", exc)
        return Progress(index, total, text, STATUS_REJECTED, REASON_DECODE_FAILED)
    result = assess_audio(samples)
    if not result.ok:
        return Progress(index, total, text, STATUS_REJECTED, result.reasons[0])
    line = store.add_line(
        slug, to_wav_bytes(result.samples), ".wav", text=spoken, original_name=f"edge-{voice}"
    )
    if normalised.resolved:
        store.set_review(slug, line.id, REVIEW_CONFIRMED)
        return Progress(index, total, text, STATUS_STORED, line_id=line.id)
    return Progress(index, total, text, STATUS_NEEDS_REVIEW, normalised.unresolved[0].reason, line.id)


def _is_set(cancel: threading.Event | None) -> bool:
    return cancel is not None and cancel.is_set()


def _notify(callback: ProgressCallback | None, outcome: Progress) -> None:
    if callback is None:
        return
    try:
        callback(outcome)
    except Exception:  # a broken progress sink must not abort a long synthesis run
        logger.exception("Edge teacher progress callback failed")
