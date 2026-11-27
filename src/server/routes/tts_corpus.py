# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console routes for training corpora: upload, transcripts, transcription, review.

Every route is an ``ADMIN`` route (ADR 0021) and is listed in ``ROUTES`` and in
``src.server.access.ROUTE_ACCESS``. Corpora are TTS assets (ADR 0027): these routes
read the request, enforce its size limits and hand it to the TTS layer through
``state.tts`` (``TtsService``), which validates the corpus slug and line ID, builds
every path on disk itself (CODING_STANDARDS 1) and keeps an uploaded file's own name
as display text only. Every layer call blocks (decoding, QC, manifest writes, file
reads), so it runs in ``asyncio.to_thread`` (CODING_STANDARDS 3); the automatic
transcription runs on the layer's own worker thread. Whether a connected stage rules
out the GPU for a transcription is the core's call (``stage_guard``).

Responses are ``{"code": 0, "msg": "ok", "data": ...}`` or
``{"code": -1, "msg": <Traditional Chinese reason>}`` with the error's HTTP
status; transcript import errors add ``"problems"``, one sentence each.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, get_args

from aiohttp import web

from nova_contracts.tts import (
    DEFAULT_TRANSCRIPTION_MODEL,
    MAX_CORPUS_UPLOAD_BYTES,
    MAX_TRANSCRIPT_FILE_BYTES,
    MAX_TRANSCRIPT_TEXT_CHARS,
    ClauseAcknowledgement,
    CorpusCreation,
    CorpusLine,
    CorpusRef,
    LineConfirmation,
    LineEdit,
    LineRef,
    LineUpload,
    ReviewState,
    TranscriptFile,
    TranscriptImport,
    TranscriptionProgress,
    TranscriptionStart,
    TtsError,
    TtsService,
)
from src.server.stage_guard import count_stage_connections, transcription_cpu_reason
from src.server.state import state
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

MAX_TEXT_FIELD_BYTES = MAX_TRANSCRIPT_TEXT_CHARS * 4
MAX_JSON_BYTES = 256 * 1024
MAX_TRANSCRIPT_FILES = 5001
REVIEW_STATES = get_args(ReviewState)
# What a stored line's first bytes say it is; uploads are stored as WAV.
AUDIO_SIGNATURES = (
    (b"RIFF", "audio/wav"),
    (b"fLaC", "audio/flac"),
    (b"OggS", "audio/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"\x1aE\xdf\xa3", "audio/webm"),
)


def register(app: web.Application) -> None:
    """Add the corpus routes to ``app``; they reach the TTS layer through ``state.tts``."""
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


class RequestError(Exception):
    """A request the route refuses before asking the TTS layer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


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


def endpoint(
    handler: Callable[[web.Request, TtsService], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    """Turn a refusal (the route's or the TTS layer's) into its Traditional Chinese JSON response."""

    async def wrapped(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request, state.tts)
        except TtsError as exc:
            return _error(exc.message, exc.status, **exc.extra)
        except RequestError as exc:
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
        raise RequestError("請求內容太大", status=413)
    raw = await request.read()
    if not raw.strip() and not required:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise RequestError("請求內容必須是 JSON") from None
    if not isinstance(body, dict):
        raise RequestError("請求內容必須是 JSON 物件")
    return body


async def _read_part(part, limit: int, too_large: str) -> bytes:
    data = bytearray()
    while chunk := await part.read_chunk(size=256 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise RequestError(too_large, status=413)
    return bytes(data)


async def _multipart(request: web.Request):
    if not request.content_type.startswith("multipart/"):
        raise RequestError("請以表單（multipart）上傳檔案")
    try:
        return await request.multipart()
    except Exception:
        raise RequestError("上傳內容格式不正確") from None


def _line_payload(slug: str, line: CorpusLine) -> dict:
    """A line as the console reads it: the layer's fields and the core's audio URL."""
    return {**line.model_dump(mode="json"), "audio_url": f"{BASE}/{slug}/lines/{line.id}/audio"}


def _line_ids(value: Any) -> tuple[str, ...] | None:
    """A ``line_ids`` list as IDs; any item that is not text names no line (404)."""
    if value is None:
        return None
    if not all(isinstance(item, str) for item in value):
        raise RequestError("找不到這一句", status=404)
    return tuple(value)


def _audio_type(data: bytes) -> str:
    return next((kind for magic, kind in AUDIO_SIGNATURES if data.startswith(magic)), "application/octet-stream")


def _slug(request: web.Request) -> str:
    return request.match_info["slug"]


# ------------------------------------------------------------------ corpora


@endpoint
async def list_corpora(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Every corpus with its source, usage label, counts and trainability."""
    listing = await asyncio.to_thread(tts.list_corpora)
    return _reply(listing.model_dump(mode="json"))


@endpoint
async def create_corpus(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Create a corpus: for uploaded recordings with a source declaration, or for the Edge test teacher.

    An Edge corpus holds no recordings of its own and needs no consent statement; the
    Microsoft clause is confirmed separately (``acknowledge_clause``) before synthesis.
    """
    body = await _json_body(request)
    slug, source = body.get("slug"), body.get("source")
    creation = CorpusCreation(
        # Anything but text fails the layer's slug and source rules with their own message.
        slug=slug if isinstance(slug, str) else "",
        source=source if isinstance(source, str) else None,
        consent=body.get("consent") is True,
    )
    summary = await asyncio.to_thread(tts.create_corpus, creation)
    return _reply(summary.model_dump(mode="json"))


@endpoint
async def get_corpus(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """The review table: every line with its state and digit-expanded text."""
    slug = _slug(request)
    detail = await asyncio.to_thread(tts.get_corpus, CorpusRef(slug=slug))
    data = detail.model_dump(mode="json")
    data["lines"] = [_line_payload(slug, line) for line in detail.lines]
    return _reply(data)


# ------------------------------------------------------------------ lines


@endpoint
async def upload_line(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Add one recording (multipart ``audio``, optional ``text``) as a pending line."""
    slug = _slug(request)
    await asyncio.to_thread(tts.get_corpus, CorpusRef(slug=slug))  # unknown corpus: 404 before reading the file
    reader = await _multipart(request)
    audio: bytes | None = None
    filename = ""
    text = ""
    while (part := await reader.next()) is not None:
        if part.name == "audio" and part.filename and audio is None:
            filename = part.filename
            limit = MAX_CORPUS_UPLOAD_BYTES
            audio = await _read_part(part, limit, f"音檔不可超過 {limit // 1024 // 1024} MB")
        elif part.name == "text":
            raw = await _read_part(part, MAX_TEXT_FIELD_BYTES, f"逐字稿最多 {MAX_TRANSCRIPT_TEXT_CHARS} 字")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise RequestError("逐字稿必須是 UTF-8 文字") from None
        else:
            raise RequestError("上傳欄位不正確")
    if audio is None:
        raise RequestError("請選擇要上傳的音檔")
    added = await asyncio.to_thread(tts.add_line, audio, LineUpload(slug=slug, filename=filename, text=text))
    return _reply({"line": _line_payload(slug, added.line), "duration": added.duration})


@endpoint
async def edit_line(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Change a line's transcript (back to pending) and/or its review state."""
    slug, line_id = _slug(request), request.match_info["line_id"]
    body = await _json_body(request)
    if not body or set(body) - {"text", "review"}:
        raise RequestError("請提供 text 或 review")
    review = body.get("review")
    if "review" in body and review not in REVIEW_STATES:
        raise RequestError("不明的校對狀態")
    if "text" in body and not isinstance(body["text"], str):
        raise RequestError("逐字稿必須是文字")
    if review == "confirmed" and isinstance(body.get("text"), str) and not body["text"].strip():
        raise RequestError("沒有逐字稿的句子不能確認")
    edit = LineEdit(slug=slug, line_id=line_id, text=body.get("text"), review=review)
    edited = await asyncio.to_thread(tts.edit_line, edit)
    return _reply({"line": _line_payload(slug, edited.line), "summary": edited.summary.model_dump(mode="json")})


@endpoint
async def line_audio(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """The stored audio of a line, for listening while reviewing; never for an Edge corpus.

    Edge read-aloud output is not played back or taken out of the machine (spec decision
    13, ADR 0026); only the administrator's own uploads are served.
    """
    ref = LineRef(slug=_slug(request), line_id=request.match_info["line_id"])
    audio = await asyncio.to_thread(tts.line_audio, ref)
    return web.Response(
        body=audio,
        headers={
            "Content-Type": _audio_type(audio),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@endpoint
async def confirm_lines(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Confirm every pending line that has a transcript, or only ``line_ids``."""
    slug = _slug(request)
    body = await _json_body(request, required=False)
    line_ids = body.get("line_ids")
    if set(body) - {"line_ids"} or (line_ids is not None and not isinstance(line_ids, list)):
        raise RequestError("line_ids 必須是句子 ID 清單")
    result = await asyncio.to_thread(tts.confirm_lines, LineConfirmation(slug=slug, line_ids=_line_ids(line_ids)))
    return _reply(result.model_dump(mode="json"))


# ------------------------------------------------------------------ Edge clause


@endpoint
async def acknowledge_clause(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Record that the administrator confirmed the clause text the console showed.

    ``shown_text`` must be exactly the server's clause text (delivered as
    ``settings.edge_clause`` of ``GET /api/tts/training``) and ``confirmed`` must be
    ``true``, which the console sends only after the required box is ticked; the text
    alone is not a confirmation.
    """
    slug = _slug(request)
    body = await _json_body(request)
    if body.get("confirmed") is not True:
        raise RequestError("請先勾選確認，才能記錄條文確認")
    shown_text = body.get("shown_text")
    if not isinstance(shown_text, str):
        raise RequestError("shown_text 必須是顯示給管理者的條文文字")
    record = await asyncio.to_thread(
        tts.acknowledge_clause, ClauseAcknowledgement(slug=slug, shown_text=shown_text)
    )
    return _reply(record.model_dump(mode="json"))


# ------------------------------------------------------------------ transcripts


@endpoint
async def import_transcripts(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Import same-name ``.txt`` files and/or one ``metadata.csv`` (multipart ``files``)."""
    slug = _slug(request)
    await asyncio.to_thread(tts.get_corpus, CorpusRef(slug=slug))
    reader = await _multipart(request)
    files: list[TranscriptFile] = []
    seen_csv = False
    count = 0
    while (part := await reader.next()) is not None:
        count += 1
        if part.name != "files" or not part.filename or count > MAX_TRANSCRIPT_FILES:
            raise RequestError("上傳欄位不正確")
        name = part.filename
        data = await _read_part(part, MAX_TRANSCRIPT_FILE_BYTES + 1, "逐字稿檔太大")
        if name.lower() == "metadata.csv":
            if seen_csv:
                raise RequestError("只能上傳一個 metadata.csv")
            seen_csv = True
        files.append(TranscriptFile(name=name, content=data))
    if not count:
        raise RequestError("請選擇逐字稿檔（.txt 或 metadata.csv）")
    result = await asyncio.to_thread(tts.import_transcripts, TranscriptImport(slug=slug, files=tuple(files)))
    return _reply(result.model_dump(mode="json"))


# ------------------------------------------------------------------ automatic transcription


def _progress(progress: TranscriptionProgress) -> dict:
    return progress.model_dump(mode="json")


@endpoint
async def start_transcription(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Start transcribing the lines without a transcript in a background thread.

    A connected stage keeps it on the CPU; otherwise the TTS layer decides by free VRAM.
    """
    body = await _json_body(request, required=False)
    line_ids, model = body.get("line_ids"), body.get("model", DEFAULT_TRANSCRIPTION_MODEL)
    if set(body) - {"line_ids", "model"} or not isinstance(model, str):
        raise RequestError("請提供 model（字串）與 line_ids（清單）")
    if line_ids is not None and (not isinstance(line_ids, list) or not all(isinstance(i, str) for i in line_ids)):
        raise RequestError("line_ids 必須是句子 ID 清單")
    slug = _slug(request)

    def start() -> TranscriptionProgress:
        cpu_reason = transcription_cpu_reason(count_stage_connections())
        return tts.start_transcription(TranscriptionStart(
            slug=slug, line_ids=None if line_ids is None else tuple(line_ids), model=model, cpu_reason=cpu_reason,
        ))

    return _reply(_progress(await asyncio.to_thread(start)), status=202)


@endpoint
async def transcription_status(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Progress of the transcription job; ``idle`` when this corpus has none."""
    return _reply(_progress(await asyncio.to_thread(tts.transcription_status, CorpusRef(slug=_slug(request)))))


@endpoint
async def cancel_transcription(request: web.Request, tts: TtsService) -> web.StreamResponse:
    """Stop the transcription job after the file it is on."""
    return _reply(_progress(await asyncio.to_thread(tts.cancel_transcription, CorpusRef(slug=_slug(request)))))
