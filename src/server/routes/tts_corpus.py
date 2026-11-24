# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console routes for training corpora: upload, transcripts, transcription, review.

Every route is an ``ADMIN`` route (ADR 0021) and is listed in ``ROUTES`` and in
``src.server.access.ROUTE_ACCESS``. Requests name a corpus by its slug and a line
by its six-digit ID, both validated by ``CorpusStore``; every path on disk is
built by the server from those (CODING_STANDARDS 1), and an uploaded file's own
name is stored as display text only. Blocking work (decoding, QC, manifest
writes, file reads) runs in ``asyncio.to_thread`` (CODING_STANDARDS 3), and the
automatic transcription runs on its own worker thread (``TranscriptionJobs``).

Responses are ``{"code": 0, "msg": "ok", "data": ...}`` or
``{"code": -1, "msg": <Traditional Chinese reason>}`` with the error's HTTP
status; transcript import errors add ``"problems"``, one sentence each.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from src.tts.training.corpus import (
    MAX_TEXT_CHARS,
    REVIEW_CONFIRMED,
    REVIEW_STATES,
    Corpus,
    CorpusError,
    CorpusStore,
    Line,
    ReviewRow,
)
from src.server.state import state
from src.server.tts_training_jobs import settings_from_config
from src.tts.training.gpu_guard import (
    DeviceChoice,
    choose_transcription_device,
    count_stage_connections,
)
from src.tts.training.gpu_probe import VramReading, read_free_vram
from src.tts.training.ingest import MAX_UPLOAD_BYTES, create_uploaded_corpus, ingest_audio
from src.tts.training.edge_acknowledgement import record_acknowledgement
from src.tts.training.numerals import normalize_digits
from src.tts.training.transcription import (
    DEFAULT_MODEL,
    TranscriptionJobs,
    TranscriptionStatus,
    cuda_available,
    default_factory,
)
from src.tts.training.usage import SOURCE_EDGE_TEST_TEACHER
from src.tts.training.transcripts import (
    MAX_CSV_BYTES,
    TranscriptEntry,
    TranscriptError,
    apply_transcripts,
    parse_metadata_csv,
    parse_txt,
)
from src.utils.logging import logger

BASE = "/api/tts/corpora"
CORPUS = BASE + "/{slug}"
LINE = CORPUS + "/lines/{line_id}"

# (method, canonical path) of every route; each is ADMIN in access.ROUTE_ACCESS.
ROUTES = (
    ("GET", BASE),
    ("POST", BASE),
    ("GET", CORPUS),
    ("POST", CORPUS + "/lines"),
    ("PUT", LINE),
    ("GET", LINE + "/audio"),
    ("POST", CORPUS + "/transcripts"),
    ("POST", CORPUS + "/confirm"),
    ("POST", CORPUS + "/acknowledgement"),
    ("POST", CORPUS + "/transcription"),
    ("GET", CORPUS + "/transcription"),
    ("DELETE", CORPUS + "/transcription"),
)

MAX_TEXT_FIELD_BYTES = MAX_TEXT_CHARS * 4
MAX_JSON_BYTES = 256 * 1024
MAX_TRANSCRIPT_FILES = 5001
AUDIO_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
}


@dataclass(frozen=True)
class Services:
    store: CorpusStore
    jobs: TranscriptionJobs


SERVICES = web.AppKey("tts_corpus_services", Services)


def register(app: web.Application, store: CorpusStore | None = None, jobs: TranscriptionJobs | None = None) -> None:
    """Add the corpus routes to ``app``; tests pass their own store and jobs."""
    store = store if store is not None else CorpusStore()
    jobs = jobs if jobs is not None else TranscriptionJobs(store, default_factory, live_device_choice)
    app[SERVICES] = Services(store, jobs)

    async def stop_jobs(_app: web.Application) -> None:
        await asyncio.to_thread(jobs.stop)

    app.on_shutdown.append(stop_jobs)
    handlers: dict[tuple[str, str], Callable[[web.Request], Awaitable[web.StreamResponse]]] = {
        ("GET", BASE): list_corpora,
        ("POST", BASE): create_corpus,
        ("GET", CORPUS): get_corpus,
        ("POST", CORPUS + "/lines"): upload_line,
        ("PUT", LINE): edit_line,
        ("GET", LINE + "/audio"): line_audio,
        ("POST", CORPUS + "/transcripts"): import_transcripts,
        ("POST", CORPUS + "/confirm"): confirm_lines,
        ("POST", CORPUS + "/acknowledgement"): acknowledge_clause,
        ("POST", CORPUS + "/transcription"): start_transcription,
        ("GET", CORPUS + "/transcription"): transcription_status,
        ("DELETE", CORPUS + "/transcription"): cancel_transcription,
    }
    assert set(handlers) == set(ROUTES)
    for (method, path), handler in handlers.items():
        app.router.add_route(method, path, handler)


# ------------------------------------------------------------------ helpers


def _reply(data: Any = None, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"code": 0, "msg": "ok", "data": data}, ensure_ascii=False),
    )


def _error(message: str, status: int, **extra: Any) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps({"code": -1, "msg": message, **extra}, ensure_ascii=False),
    )


def endpoint(handler):
    """Turn a ``CorpusError`` into its Traditional Chinese JSON response."""

    async def wrapped(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request, request.app[SERVICES])
        except TranscriptError as exc:
            return _error(exc.message, exc.status, problems=exc.problems)
        except CorpusError as exc:
            return _error(exc.message, exc.status)
        except web.HTTPException:
            raise
        except Exception:
            logger.exception("Training corpus route %s %s failed", request.method, request.path)
            return _error("處理訓練語料時發生錯誤", 500)

    wrapped.__name__ = handler.__name__
    wrapped.__doc__ = handler.__doc__
    return wrapped


async def _json_body(request: web.Request, *, required: bool = True) -> dict:
    if request.content_length is not None and request.content_length > MAX_JSON_BYTES:
        raise CorpusError("請求內容太大", status=413)
    raw = await request.read()
    if not raw.strip() and not required:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise CorpusError("請求內容必須是 JSON") from None
    if not isinstance(body, dict):
        raise CorpusError("請求內容必須是 JSON 物件")
    return body


async def _read_part(part, limit: int, too_large: str) -> bytes:
    data = bytearray()
    while chunk := await part.read_chunk(size=256 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise CorpusError(too_large, status=413)
    return bytes(data)


async def _multipart(request: web.Request):
    if not request.content_type.startswith("multipart/"):
        raise CorpusError("請以表單（multipart）上傳檔案")
    try:
        return await request.multipart()
    except Exception:
        raise CorpusError("上傳內容格式不正確") from None


def _line_payload(slug: str, line: Line, normalized=None) -> dict:
    normalized = normalized if normalized is not None else normalize_digits(line.text)
    return {
        "id": line.id,
        "original_name": line.original_name,
        "text": line.text,
        "normalized_text": normalized.text,
        "unresolved": [
            {"text": item.text, "start": item.start, "end": item.end, "reason": item.reason}
            for item in normalized.unresolved
        ],
        "review": line.review,
        "audio_url": f"{BASE}/{slug}/lines/{line.id}/audio",
    }


def _summary(corpus: Corpus) -> dict:
    counts = corpus.counts
    trainability = corpus.trainability()
    return {
        "slug": corpus.slug,
        "source": corpus.source,
        "declared_at": corpus.declared_at,
        "usage_label": corpus.usage_label(),
        "counts": {
            "pending": counts.pending,
            "confirmed": counts.confirmed,
            "excluded": counts.excluded,
            "total": len(corpus.lines),
        },
        "trainable": trainability.trainable,
        "reasons": list(trainability.reasons),
    }


def _detail(corpus: Corpus) -> dict:
    rows: list[ReviewRow] = corpus.review_table()
    return {**_summary(corpus), "lines": [_line_payload(corpus.slug, row.line, row.normalized) for row in rows]}


def _status_payload(status: TranscriptionStatus) -> dict:
    return {
        "state": status.state,
        "slug": status.slug,
        "model": status.model,
        "total": status.total,
        "done": status.done,
        "skipped": status.skipped,
        "failed": [{"line_id": item.line_id, "message": item.message} for item in status.failed],
        "message": status.message,
        "cancel_requested": status.cancel_requested,
        "device": status.device,
        "fallback_reason": status.fallback_reason,
    }


def live_device_choice(
    *,
    sessions: Callable[[], int] = count_stage_connections,
    vram_probe: Callable[[], VramReading] = read_free_vram,
    cuda_available: Callable[[], bool] = cuda_available,
) -> DeviceChoice:
    """The GPU guard's decision for a new transcription job, on the live configuration.

    Uses the same stage count and free-VRAM threshold (``matcha.training_min_free_vram_gb``)
    as the training start. Blocking (``nvidia-smi``): ``TranscriptionJobs.start`` runs it in a worker thread.
    """
    threshold = settings_from_config(state.config).min_free_vram_gb
    return choose_transcription_device(sessions, vram_probe, threshold, cuda_available)


def _slug(request: web.Request) -> str:
    return request.match_info["slug"]


# ------------------------------------------------------------------ corpora


@endpoint
async def list_corpora(request: web.Request, services: Services) -> web.StreamResponse:
    """Every corpus with its source, usage label, counts and trainability."""
    summaries = await asyncio.to_thread(lambda: [_summary(corpus) for corpus in services.store.list()])
    return _reply({"corpora": summaries})


@endpoint
async def create_corpus(request: web.Request, services: Services) -> web.StreamResponse:
    """Create a corpus: for uploaded recordings with a source declaration, or for the Edge test teacher.

    An Edge corpus holds no recordings of its own and needs no consent statement; the
    Microsoft clause is confirmed separately (``acknowledge_clause``) before synthesis.
    """
    body = await _json_body(request)
    slug = body.get("slug")
    if body.get("source") == SOURCE_EDGE_TEST_TEACHER:
        corpus = await asyncio.to_thread(services.store.create, slug, source=SOURCE_EDGE_TEST_TEACHER)
    else:
        consent = body.get("consent") is True
        corpus = await asyncio.to_thread(
            lambda: create_uploaded_corpus(services.store, slug, body.get("source"), consent=consent)
        )
    return _reply(_summary(corpus))


@endpoint
async def get_corpus(request: web.Request, services: Services) -> web.StreamResponse:
    """The review table: every line with its state and digit-expanded text."""
    detail = await asyncio.to_thread(lambda: _detail(services.store.get(_slug(request))))
    return _reply(detail)


# ------------------------------------------------------------------ lines


@endpoint
async def upload_line(request: web.Request, services: Services) -> web.StreamResponse:
    """Add one recording (multipart ``audio``, optional ``text``) as a pending line."""
    slug = _slug(request)
    await asyncio.to_thread(services.store.get, slug)  # unknown corpus: 404 before reading the file
    reader = await _multipart(request)
    audio: bytes | None = None
    filename = ""
    text = ""
    while (part := await reader.next()) is not None:
        if part.name == "audio" and part.filename and audio is None:
            filename = part.filename
            limit = MAX_UPLOAD_BYTES
            audio = await _read_part(part, limit, f"音檔不可超過 {limit // 1024 // 1024} MB")
        elif part.name == "text":
            raw = await _read_part(part, MAX_TEXT_FIELD_BYTES, f"逐字稿最多 {MAX_TEXT_CHARS} 字")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise CorpusError("逐字稿必須是 UTF-8 文字") from None
        else:
            raise CorpusError("上傳欄位不正確")
    if audio is None:
        raise CorpusError("請選擇要上傳的音檔")
    result = await asyncio.to_thread(ingest_audio, services.store, slug, audio, filename, text)
    payload = await asyncio.to_thread(_line_payload, slug, result.line)
    return _reply({"line": payload, "duration": round(result.duration, 2)})


@endpoint
async def edit_line(request: web.Request, services: Services) -> web.StreamResponse:
    """Change a line's transcript (back to pending) and/or its review state."""
    slug, line_id = _slug(request), request.match_info["line_id"]
    body = await _json_body(request)
    if not body or set(body) - {"text", "review"}:
        raise CorpusError("請提供 text 或 review")
    review = body.get("review")
    if "review" in body and review not in REVIEW_STATES:
        raise CorpusError("不明的校對狀態")
    if review == REVIEW_CONFIRMED and isinstance(body.get("text"), str) and not body["text"].strip():
        raise CorpusError("沒有逐字稿的句子不能確認")

    def change() -> dict:
        store = services.store
        if "text" in body:
            store.set_text(slug, line_id, body["text"])
        if "review" in body:
            store.set_review(slug, line_id, review)
        corpus = store.get(slug)
        line = next(item for item in corpus.lines if item.id == line_id)
        return {"line": _line_payload(slug, line), "summary": _summary(corpus)}

    return _reply(await asyncio.to_thread(change))


@endpoint
async def line_audio(request: web.Request, services: Services) -> web.StreamResponse:
    """The stored audio of a line, for listening while reviewing; never for an Edge corpus.

    Edge read-aloud output is not played back or taken out of the machine (spec decision
    13, ADR 0026); only the administrator's own uploads are served.
    """

    def locate() -> Path:
        slug = _slug(request)
        if services.store.get(slug).source == SOURCE_EDGE_TEST_TEACHER:
            raise CorpusError("Edge 測試用老師合成的音檔不提供試聽或下載（ADR 0026）", status=403)
        return services.store.audio_path(slug, request.match_info["line_id"])

    path = await asyncio.to_thread(locate)
    return web.FileResponse(
        path,
        headers={
            "Content-Type": AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream"),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@endpoint
async def confirm_lines(request: web.Request, services: Services) -> web.StreamResponse:
    """Confirm every pending line that has a transcript, or only ``line_ids``."""
    slug = _slug(request)
    body = await _json_body(request, required=False)
    line_ids = body.get("line_ids")
    if set(body) - {"line_ids"} or (line_ids is not None and not isinstance(line_ids, list)):
        raise CorpusError("line_ids 必須是句子 ID 清單")

    def confirm() -> dict:
        result = services.store.confirm_pending(slug, line_ids)
        summary = _summary(services.store.get(slug))
        return {"confirmed": result.confirmed, "without_text": result.without_text, "summary": summary}

    return _reply(await asyncio.to_thread(confirm))


# ------------------------------------------------------------------ Edge clause


@endpoint
async def acknowledge_clause(request: web.Request, services: Services) -> web.StreamResponse:
    """Record that the administrator confirmed the clause text the console showed.

    ``shown_text`` must be exactly the server's ``MSA_CLAUSE.text`` (delivered as
    ``settings.edge_clause`` of ``GET /api/tts/training``) and ``confirmed`` must be
    ``true``, which the console sends only after the required box is ticked; the text
    alone is not a confirmation.
    """
    slug = _slug(request)
    body = await _json_body(request)
    if body.get("confirmed") is not True:
        raise CorpusError("請先勾選確認，才能記錄條文確認")
    shown_text = body.get("shown_text")
    if not isinstance(shown_text, str):
        raise CorpusError("shown_text 必須是顯示給管理者的條文文字")
    record = await asyncio.to_thread(record_acknowledgement, services.store, slug, shown_text)
    return _reply(
        {
            "acknowledged_at": record.acknowledged_at,
            "clause_reference": record.clause_reference,
            "clause_effective": record.clause_effective,
        }
    )


# ------------------------------------------------------------------ transcripts


def _parse_transcript_files(files: list[tuple[str, bytes]]) -> list[TranscriptEntry]:
    """Parse the uploaded files; every problem of every file is reported together (blocking)."""
    entries: list[TranscriptEntry] = []
    problems: list[str] = []
    for name, data in files:
        try:
            if name.lower() == "metadata.csv":
                entries.extend(parse_metadata_csv(data))
            elif name.lower().endswith(".txt"):
                entries.append(parse_txt(name, data))
            else:
                raise TranscriptError([f"「{name.replace(chr(92), '/').rsplit('/', 1)[-1][:80]}」不是支援的逐字稿檔，只接受 .txt 與 metadata.csv"])
        except TranscriptError as exc:
            problems.extend(exc.problems)
    if problems:
        raise TranscriptError(problems)
    return entries


@endpoint
async def import_transcripts(request: web.Request, services: Services) -> web.StreamResponse:
    """Import same-name ``.txt`` files and/or one ``metadata.csv`` (multipart ``files``)."""
    slug = _slug(request)
    await asyncio.to_thread(services.store.get, slug)
    reader = await _multipart(request)
    files: list[tuple[str, bytes]] = []
    seen_csv = False
    count = 0
    while (part := await reader.next()) is not None:
        count += 1
        if part.name != "files" or not part.filename or count > MAX_TRANSCRIPT_FILES:
            raise CorpusError("上傳欄位不正確")
        name = part.filename
        data = await _read_part(part, MAX_CSV_BYTES + 1, "逐字稿檔太大")
        if name.lower() == "metadata.csv":
            if seen_csv:
                raise CorpusError("只能上傳一個 metadata.csv")
            seen_csv = True
        files.append((name, data))
    if not count:
        raise CorpusError("請選擇逐字稿檔（.txt 或 metadata.csv）")
    entries = await asyncio.to_thread(_parse_transcript_files, files)
    result = await asyncio.to_thread(apply_transcripts, services.store, slug, entries)
    return _reply({"applied": result.applied, "without_transcript": result.without_transcript})


# ------------------------------------------------------------------ automatic transcription


@endpoint
async def start_transcription(request: web.Request, services: Services) -> web.StreamResponse:
    """Start transcribing the lines without a transcript in a background thread."""
    body = await _json_body(request, required=False)
    line_ids, model = body.get("line_ids"), body.get("model", DEFAULT_MODEL)
    if set(body) - {"line_ids", "model"} or not isinstance(model, str):
        raise CorpusError("請提供 model（字串）與 line_ids（清單）")
    if line_ids is not None and (not isinstance(line_ids, list) or not all(isinstance(i, str) for i in line_ids)):
        raise CorpusError("line_ids 必須是句子 ID 清單")
    status = await asyncio.to_thread(services.jobs.start, _slug(request), line_ids, model)
    return _reply(_status_payload(status), status=202)


@endpoint
async def transcription_status(request: web.Request, services: Services) -> web.StreamResponse:
    """Progress of the transcription job; ``idle`` when this corpus has none."""
    await asyncio.to_thread(services.store.get, _slug(request))
    return _reply(_status_payload(services.jobs.status(_slug(request))))


@endpoint
async def cancel_transcription(request: web.Request, services: Services) -> web.StreamResponse:
    """Stop the transcription job after the file it is on."""
    return _reply(_status_payload(services.jobs.cancel(_slug(request))))
