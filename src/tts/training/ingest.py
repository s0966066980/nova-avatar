# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Uploading recordings into a training corpus.

An upload corpus declares where its audio comes from before any file is added
(spec decision 5):

* ``self-recorded`` and ``written-authorization`` need the administrator's
  consent statement (``consent=True``); their models are Research /
  Non-commercial at best (``usage``), never commercial.
* ``development-unlicensed`` needs no statement and yields Development only.
* ``edge-test-teacher`` is not an upload source: only the Edge teacher
  (ticket 04) writes such corpora, so an upload can neither claim it nor be
  added to one.

``ingest_audio`` validates the file name's extension and size, really decodes the
content (``audio_decode.decode_to_16k_mono``), runs the audio QC
(``audio_quality.assess_audio``, shared with the Edge teacher) and stores the
result as a 16 kHz mono PCM16 WAV through ``CorpusStore.add_line``. The client's
file name is kept only as display text; paths come from the store. The Whisper
similarity check is optional: pass ``recognizer`` (16 kHz float samples to text)
together with ``text`` to refuse a transcript the audio does not support.

This is blocking CPU work; async callers use ``asyncio.to_thread`` (CODING_STANDARDS 3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

import numpy as np

from src.tts.training.audio_decode import decode_to_16k_mono, quality_message
from src.tts.training.audio_quality import assess_audio, to_wav_bytes
from src.tts.training.corpus import AUDIO_EXTENSIONS, Corpus, CorpusError, CorpusStore, Line
from src.tts.training.transcript_check import DEFAULT_MIN_SIMILARITY, similarity_ratio
from src.tts.training.usage import (
    SOURCE_DEVELOPMENT_UNLICENSED,
    SOURCE_SELF_RECORDED,
    SOURCE_WRITTEN_AUTHORIZATION,
)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_SOURCES = (SOURCE_SELF_RECORDED, SOURCE_WRITTEN_AUTHORIZATION, SOURCE_DEVELOPMENT_UNLICENSED)
CONSENT_SOURCES = (SOURCE_SELF_RECORDED, SOURCE_WRITTEN_AUTHORIZATION)

Recognizer = Callable[[np.ndarray], str]


@dataclass(frozen=True)
class IngestResult:
    line: Line
    duration: float


def _check_declaration(source: object, consent: bool) -> str:
    if not isinstance(source, str) or source not in UPLOAD_SOURCES:
        raise CorpusError("請選擇錄音來源：自己錄的、有書面授權，或開發用（未取得授權）")
    if source in CONSENT_SOURCES and consent is not True:
        raise CorpusError("請勾選聲明：這些錄音是你自己錄製，或已取得說話者的書面授權")
    return source


def create_uploaded_corpus(store: CorpusStore, slug: str, source: object, *, consent: bool) -> Corpus:
    """Create a corpus for uploaded recordings with a validated source declaration."""
    return store.create(slug, source=_check_declaration(source, consent))


def _extension(filename: str) -> str:
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower() if isinstance(filename, str) else ""
    if suffix not in AUDIO_EXTENSIONS:
        raise CorpusError("不支援的音檔格式，請上傳 WAV、MP3、FLAC、OGG、M4A 或 WebM", status=415)
    return suffix


def ingest_audio(
    store: CorpusStore,
    slug: str,
    data: bytes,
    filename: str,
    text: str = "",
    *,
    recognizer: Recognizer | None = None,
) -> IngestResult:
    """Validate, convert and QC one recording and add it to the corpus as a pending line."""
    corpus = store.get(slug)
    if corpus.source is None:
        raise CorpusError("請先宣告這份語料的錄音來源，才能上傳音檔", status=409)
    if corpus.source not in UPLOAD_SOURCES:
        raise CorpusError("這份語料不接受上傳的音檔", status=409)
    _extension(filename)
    if not data:
        raise CorpusError("音檔是空的")
    if len(data) > MAX_UPLOAD_BYTES:
        raise CorpusError(f"音檔不可超過 {MAX_UPLOAD_BYTES // 1024 // 1024} MB", status=413)
    result = assess_audio(decode_to_16k_mono(data))
    if not result.ok:
        raise CorpusError(quality_message(result.reasons), status=422)
    if text and recognizer is not None:
        heard = recognizer(result.samples)
        if similarity_ratio(text, heard) < DEFAULT_MIN_SIMILARITY:
            raise CorpusError("逐字稿與音檔內容不符（語音辨識結果差異過大），請檢查逐字稿或音檔", status=422)
    line = store.add_line(slug, to_wav_bytes(result.samples), ".wav", text=text, original_name=filename)
    return IngestResult(line, result.duration)
