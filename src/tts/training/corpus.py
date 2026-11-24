# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Training corpus (訓練語料) on disk under ``data/tts/training/<slug>/``.

A corpus is a set of audio lines with a transcript each, a review state per
line and one source declaration. Layout::

    data/tts/training/<slug>/
        corpus.json                 manifest (UTF-8 JSON, written atomically)
        audio/<line id><extension>  one audio file per line

Every path is built by the server from a validated slug (the same rule as a
voice-model ID, because the trained model is later exported to
``models/tts/<slug>/``), a server-generated six-digit line ID and an extension
from ``AUDIO_EXTENSIONS``. Callers never supply a path: an uploaded file's own
name is kept only as display text (``Line.original_name``) and is never used to
build a path. Symlinked corpus directories and audio files are refused.

Review states: a new line is ``pending``; the administrator moves it to
``confirmed`` or ``excluded``. Editing the text of a confirmed line sends it back
to ``pending`` so a changed transcript is never trained unreviewed. The review
table (``Corpus.review_table``) shows each line's digit-expanded text and the
tokens ``src.tts.training.numerals`` could not decide.

The source declaration is one of ``usage.SOURCE_KINDS``. It is set once, at
creation or later, and never changed afterwards: the usage label derives from it
and processing must not lower the label (``Corpus.usage_label``). To use a
different source, create another corpus.

A corpus is trainable (``Corpus.trainability``) only when the source is
declared, no line is pending, at least one line is confirmed, and no confirmed
line has unresolved digits. This module is the data layer only: it has no
routes, never touches the GPU and loads no model. Deleting a corpus is not
offered here; when added it must check for a running training job and move the
folder into a ``.deleted`` recycle bin (CODING_STANDARDS 4).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tts.training.numerals import NormalizedText, normalize_digits
from src.tts.training.usage import SOURCE_KINDS, corpus_usage_label
from src.tts.voice_models import VOICE_MODEL_ID
from src.utils.logging import logger
from src.utils.paths import get_project_root

TRAINING_ROOT = get_project_root() / "data" / "tts" / "training"
MANIFEST_FILE = "corpus.json"
AUDIO_DIR = "audio"
MANIFEST_VERSION = 1

REVIEW_PENDING = "pending"
REVIEW_CONFIRMED = "confirmed"
REVIEW_EXCLUDED = "excluded"
REVIEW_STATES = (REVIEW_PENDING, REVIEW_CONFIRMED, REVIEW_EXCLUDED)

AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm")
LINE_ID = re.compile(r"[0-9]{6}")
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_LINES = 5000
MAX_TEXT_CHARS = 500
MAX_NAME_CHARS = 120

# Reason codes of ``Trainability.reasons``, in report order.
REASON_SOURCE_MISSING = "source_missing"
REASON_PENDING_LINES = "pending_lines"
REASON_NO_CONFIRMED_LINES = "no_confirmed_lines"
REASON_UNRESOLVED_DIGITS = "unresolved_digits"

# One lock for every store: manifests are read-modify-write and a Matcha corpus
# is filled by a worker thread while the administrator reviews it.
_LOCK = threading.RLock()


class CorpusError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Line:
    id: str
    ext: str
    original_name: str
    text: str
    review: str

    @property
    def audio_name(self) -> str:
        return f"{self.id}{self.ext}"


@dataclass(frozen=True)
class ReviewRow:
    line: Line
    normalized: NormalizedText


@dataclass(frozen=True)
class Counts:
    pending: int
    confirmed: int
    excluded: int


@dataclass(frozen=True)
class Trainability:
    trainable: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Corpus:
    slug: str
    source: str | None
    declared_at: str | None
    lines: tuple[Line, ...]

    @property
    def counts(self) -> Counts:
        states = [line.review for line in self.lines]
        return Counts(
            pending=states.count(REVIEW_PENDING),
            confirmed=states.count(REVIEW_CONFIRMED),
            excluded=states.count(REVIEW_EXCLUDED),
        )

    def usage_label(self, base_usage: str | None = None) -> str:
        """The usage label of a model trained on this corpus; see ``usage``."""
        if base_usage is None:
            return corpus_usage_label(self.source)
        return corpus_usage_label(self.source, base_usage)

    def review_table(self) -> list[ReviewRow]:
        """Every line with its digit-expanded text and unresolved tokens."""
        return [ReviewRow(line, normalize_digits(line.text)) for line in self.lines]

    def trainability(self) -> Trainability:
        """Whether training may start, and every reason it may not."""
        reasons: list[str] = []
        counts = self.counts
        if self.source is None:
            reasons.append(REASON_SOURCE_MISSING)
        if counts.pending:
            reasons.append(REASON_PENDING_LINES)
        if not counts.confirmed:
            reasons.append(REASON_NO_CONFIRMED_LINES)
        if any(
            not normalize_digits(line.text).resolved
            for line in self.lines
            if line.review == REVIEW_CONFIRMED
        ):
            reasons.append(REASON_UNRESOLVED_DIGITS)
        return Trainability(not reasons, tuple(reasons))

    def training_lines(self) -> list[tuple[Line, str]]:
        """The confirmed lines with their digit-expanded text; only for a trainable corpus."""
        if not self.trainability().trainable:
            raise CorpusError("語料尚未可訓練，請先完成校對與來源宣告", status=409)
        return [
            (line, normalize_digits(line.text).text)
            for line in self.lines
            if line.review == REVIEW_CONFIRMED
        ]


class CorpusStore:
    """Corpora under one root directory (``TRAINING_ROOT`` unless given)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = TRAINING_ROOT if root is None else root

    # ------------------------------------------------------------ corpus

    def create(self, slug: str, source: str | None = None) -> Corpus:
        slug = _slug(slug)
        if source is not None:
            _check_source(source)
        with _LOCK:
            self.root.mkdir(parents=True, exist_ok=True)
            try:
                (self.root / slug).mkdir()
            except FileExistsError:
                raise CorpusError("同名的訓練語料已存在", status=409) from None
            corpus = Corpus(slug, source, _now() if source else None, ())
            self._save(corpus)
            logger.info("Created training corpus %s (source %s)", slug, source)
            return corpus

    def get(self, slug: str) -> Corpus:
        slug = _slug(slug)
        with _LOCK:
            return self._load(slug)

    def list(self) -> list[Corpus]:
        """The readable corpora, ordered by slug; broken folders are logged and skipped."""
        if not self.root.is_dir():
            return []
        corpora = []
        for path in sorted(self.root.iterdir()):
            if path.name.startswith(".") or path.is_symlink() or not path.is_dir():
                continue
            try:
                corpora.append(self.get(path.name))
            except CorpusError as exc:
                logger.info("Training corpus %s not listed: %s", path.name, exc.message)
        return corpora

    def declare_source(self, slug: str, source: str) -> Corpus:
        """Record where the audio comes from; allowed once, then immutable."""
        _check_source(source)
        with _LOCK:
            corpus = self.get(slug)
            if corpus.source == source:
                return corpus
            if corpus.source is not None:
                raise CorpusError("來源宣告已記錄，不能更改；請建立新的語料", status=409)
            updated = Corpus(corpus.slug, source, _now(), corpus.lines)
            self._save(updated)
            logger.info("Declared source %s for training corpus %s", source, corpus.slug)
            return updated

    # ------------------------------------------------------------ lines

    def add_line(
        self, slug: str, audio: bytes, extension: str, text: str = "", original_name: str = ""
    ) -> Line:
        """Store one audio file as a new pending line and return it."""
        extension = _check_extension(extension)
        if not isinstance(audio, bytes | bytearray) or not audio:
            raise CorpusError("音檔是空的")
        if len(audio) > MAX_AUDIO_BYTES:
            raise CorpusError("音檔太大", status=413)
        text = _clean_text(text)
        with _LOCK:
            corpus = self.get(slug)
            if len(corpus.lines) >= MAX_LINES:
                raise CorpusError(f"語料最多 {MAX_LINES} 句")
            next_number = max((int(line.id) for line in corpus.lines), default=0) + 1
            line = Line(f"{next_number:06d}", extension, _display_name(original_name), text, REVIEW_PENDING)
            audio_dir = self._audio_dir(corpus.slug, create=True)
            audio_file = audio_dir / line.audio_name
            _write_atomic(audio_file, bytes(audio))
            try:
                self._save(Corpus(corpus.slug, corpus.source, corpus.declared_at, (*corpus.lines, line)))
            except BaseException:
                audio_file.unlink(missing_ok=True)
                raise
            return line

    def set_text(self, slug: str, line_id: str, text: str) -> Line:
        """Replace a line's transcript; a confirmed line goes back to pending."""
        text = _clean_text(text)

        def change(line: Line) -> Line:
            review = REVIEW_PENDING if line.review == REVIEW_CONFIRMED else line.review
            return Line(line.id, line.ext, line.original_name, text, review)

        return self._change_line(slug, line_id, change)

    def set_review(self, slug: str, line_id: str, review: str) -> Line:
        if review not in REVIEW_STATES:
            raise CorpusError("不明的校對狀態")

        def change(line: Line) -> Line:
            if review == REVIEW_CONFIRMED and not line.text:
                raise CorpusError("沒有逐字稿的句子不能確認")
            return Line(line.id, line.ext, line.original_name, line.text, review)

        return self._change_line(slug, line_id, change)

    def audio_path(self, slug: str, line_id: str) -> Path:
        """The server-built path of a line's audio file."""
        slug = _slug(slug)
        if not isinstance(line_id, str) or not LINE_ID.fullmatch(line_id):
            raise CorpusError("找不到這一句", status=404)
        with _LOCK:
            line = _find(self._load(slug), line_id)
            path = self._audio_dir(slug) / line.audio_name
            if path.is_symlink() or not path.is_file():
                raise CorpusError("找不到這一句的音檔", status=404)
            return path

    # ------------------------------------------------------------ internals

    def _change_line(self, slug: str, line_id: str, change) -> Line:
        if not isinstance(line_id, str) or not LINE_ID.fullmatch(line_id):
            raise CorpusError("找不到這一句", status=404)
        with _LOCK:
            corpus = self.get(slug)
            old = _find(corpus, line_id)
            new = change(old)
            lines = tuple(new if line.id == line_id else line for line in corpus.lines)
            self._save(Corpus(corpus.slug, corpus.source, corpus.declared_at, lines))
            return new

    def _corpus_dir(self, slug: str) -> Path:
        path = self.root / slug
        if path.is_symlink():
            raise CorpusError("訓練語料資料夾不可為符號連結")
        return path

    def _audio_dir(self, slug: str, create: bool = False) -> Path:
        path = self._corpus_dir(slug) / AUDIO_DIR
        if path.is_symlink():
            raise CorpusError("音檔資料夾不可為符號連結")
        if create:
            path.mkdir(exist_ok=True)
        return path

    def _load(self, slug: str) -> Corpus:
        manifest = self._corpus_dir(slug) / MANIFEST_FILE
        if not manifest.is_file() or manifest.is_symlink():
            raise CorpusError("找不到這份訓練語料", status=404)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorpusError(f"訓練語料清單無法讀取：{exc}", status=500) from exc
        return _parse(slug, data)

    def _save(self, corpus: Corpus) -> None:
        data = {
            "version": MANIFEST_VERSION,
            "source": corpus.source,
            "declared_at": corpus.declared_at,
            "lines": [
                {
                    "id": line.id,
                    "ext": line.ext,
                    "original_name": line.original_name,
                    "text": line.text,
                    "review": line.review,
                }
                for line in corpus.lines
            ],
        }
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        _write_atomic(self._corpus_dir(corpus.slug) / MANIFEST_FILE, text.encode("utf-8"))


# ------------------------------------------------------------------ validation


def _slug(slug: Any) -> str:
    if not isinstance(slug, str) or not VOICE_MODEL_ID.fullmatch(slug):
        raise CorpusError("語料名稱只能用英數字、點、底線與連字號（最長 80 字元），且以英數字開頭")
    return slug


def _check_source(source: Any) -> str:
    if not isinstance(source, str) or source not in SOURCE_KINDS:
        raise CorpusError("不明的來源宣告")
    return source


def _check_extension(extension: Any) -> str:
    extension = extension.lower() if isinstance(extension, str) else ""
    if extension not in AUDIO_EXTENSIONS:
        raise CorpusError("不支援的音檔格式")
    return extension


def _clean_text(text: Any) -> str:
    if not isinstance(text, str):
        raise CorpusError("逐字稿必須是文字")
    if any(unicodedata.category(ch) == "Cc" and not ch.isspace() for ch in text):
        raise CorpusError("逐字稿含有控制字元")
    text = " ".join(text.split())
    if len(text) > MAX_TEXT_CHARS:
        raise CorpusError(f"每句逐字稿最多 {MAX_TEXT_CHARS} 字")
    return text


def _display_name(name: Any) -> str:
    """The base name of an uploaded file, for display only; never used as a path."""
    if not isinstance(name, str):
        return ""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if unicodedata.category(ch) != "Cc").strip()
    return "" if base in (".", "..") else base[:MAX_NAME_CHARS]


def _find(corpus: Corpus, line_id: str) -> Line:
    for line in corpus.lines:
        if line.id == line_id:
            return line
    raise CorpusError("找不到這一句", status=404)


def _parse(slug: str, data: Any) -> Corpus:
    """Validate a manifest read from disk; it is untrusted like any other input."""
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        raise CorpusError("訓練語料清單格式不符", status=500)
    source = data.get("source")
    declared_at = data.get("declared_at")
    if source is not None and (not isinstance(source, str) or source not in SOURCE_KINDS):
        raise CorpusError("訓練語料清單的來源宣告不明", status=500)
    if declared_at is not None and not isinstance(declared_at, str):
        raise CorpusError("訓練語料清單格式不符", status=500)
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list):
        raise CorpusError("訓練語料清單格式不符", status=500)
    lines = []
    seen: set[str] = set()
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise CorpusError("訓練語料清單格式不符", status=500)
        line_id, ext = raw.get("id"), raw.get("ext")
        name, text, review = raw.get("original_name"), raw.get("text"), raw.get("review")
        if (
            not isinstance(line_id, str)
            or not LINE_ID.fullmatch(line_id)
            or line_id in seen
            or ext not in AUDIO_EXTENSIONS
            or not isinstance(name, str)
            or not isinstance(text, str)
            or review not in REVIEW_STATES
        ):
            raise CorpusError("訓練語料清單含有不合法的句子", status=500)
        seen.add(line_id)
        lines.append(Line(line_id, ext, name, text, review))
    return Corpus(slug, source, declared_at, tuple(lines))


# ------------------------------------------------------------------ files


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` next to ``path`` and rename it into place."""
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
