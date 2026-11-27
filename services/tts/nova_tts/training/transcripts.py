# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Import transcripts for a corpus: same-name ``.txt`` files or a ``metadata.csv``.

Two layouts are accepted, both UTF-8 (a byte order mark is tolerated):

* ``<audio name>.txt`` holds the transcript of the audio file with the same name
  (``take1.wav`` and ``take1.txt``); line breaks fold into spaces.
* ``metadata.csv`` has one ``filename|text`` row per line, split at the pipe.
  An optional first row ``filename|text`` is a header; blank rows are skipped.
  A text containing a pipe is refused instead of guessed at.

Parsing is strict: any bad row is reported with its row number and nothing is
imported until every problem is fixed. ``apply_transcripts`` matches entries to
the uploaded audio by the original file name (with or without the extension) and
is all-or-nothing as well: an entry naming no uploaded file, two entries for one
file, or two uploads sharing a name abort the import. Names are only compared,
never used as paths. All messages are Traditional Chinese for the console.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from nova_tts.training.corpus import CorpusError, CorpusStore, clean_text

MAX_TXT_BYTES = 8 * 1024
MAX_CSV_BYTES = 2 * 1024 * 1024
HEADER_ROW = ("filename", "text")
MAX_REPORTED_PROBLEMS = 10


class TranscriptError(CorpusError):
    """An import refused for one or more problems, each a Traditional Chinese sentence."""

    def __init__(self, problems: list[str]):
        shown = problems[:MAX_REPORTED_PROBLEMS]
        message = "；".join(shown)
        if len(problems) > len(shown):
            message += f"；還有 {len(problems) - len(shown)} 項問題"
        super().__init__(message, status=422)
        self.problems = problems


@dataclass(frozen=True)
class TranscriptEntry:
    """A transcript and the audio file name it belongs to (``take1`` or ``take1.wav``)."""

    name: str
    text: str


@dataclass(frozen=True)
class ApplyResult:
    applied: int
    without_transcript: list[str] = field(default_factory=list)


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TranscriptError([f"{what}不是 UTF-8 編碼，請另存為 UTF-8 後再上傳"]) from None


def _file_name_problem(name: str) -> str | None:
    if not name or name in (".", "..") or name.startswith(".") or "/" in name or "\\" in name:
        return "檔名不正確，只能是單純的檔案名稱"
    return None




def parse_txt(filename: str, data: bytes) -> TranscriptEntry:
    """The entry of one ``<audio name>.txt`` upload."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    shown = f"「{base[:80]}」"
    if filename != base or _file_name_problem(base):
        raise TranscriptError([f"{shown}的檔名不正確，只能是單純的檔案名稱"])
    path = PurePosixPath(base)
    if path.suffix.lower() != ".txt":
        raise TranscriptError([f"{shown}不是 .txt 逐字稿檔"])
    if len(data) > MAX_TXT_BYTES:
        raise TranscriptError([f"{shown}太大，每個逐字稿檔最多 {MAX_TXT_BYTES // 1024} KB"])
    decoded = _decode(data, shown)
    try:
        text = clean_text(decoded)
    except CorpusError as exc:
        raise TranscriptError([f"{shown}：{exc.message}"]) from None
    if not text:
        raise TranscriptError([f"{shown}沒有內容"])
    return TranscriptEntry(path.stem, text)


def parse_metadata_csv(data: bytes) -> list[TranscriptEntry]:
    """The entries of a ``metadata.csv`` (``filename|text`` per row)."""
    if len(data) > MAX_CSV_BYTES:
        raise TranscriptError([f"metadata.csv 太大，最多 {MAX_CSV_BYTES // 1024 // 1024} MB"])
    content = _decode(data, "metadata.csv ")
    entries: list[TranscriptEntry] = []
    problems: list[str] = []
    seen: set[str] = set()
    first_row = True
    for number, raw in enumerate(content.split("\n"), start=1):
        row = raw.rstrip("\r")
        if not row.strip():
            continue
        columns = row.split("|")
        if first_row:
            first_row = False
            if tuple(column.strip().lower() for column in columns) == HEADER_ROW:
                continue
        if len(columns) != 2:
            reason = "文字含有「|」，無法分辨欄位" if len(columns) > 2 else "需要「檔名|文字」兩欄"
            problems.append(f"第 {number} 行：{reason}")
            continue
        name = columns[0].strip()
        if not name:
            problems.append(f"第 {number} 行：沒有檔名")
            continue
        if reason := _file_name_problem(name):
            problems.append(f"第 {number} 行：{reason}")
            continue
        try:
            text = clean_text(columns[1])
        except CorpusError as exc:
            problems.append(f"第 {number} 行：{exc.message}")
            continue
        if not text:
            problems.append(f"第 {number} 行：沒有逐字稿文字")
            continue
        if name in seen:
            problems.append(f"第 {number} 行：檔名「{name[:80]}」重複")
            continue
        seen.add(name)
        entries.append(TranscriptEntry(name, text))
    if problems:
        raise TranscriptError(problems)
    if not entries:
        raise TranscriptError(["metadata.csv 沒有任何資料"])
    return entries


def _stem(name: str) -> str:
    return PurePosixPath(name).stem


def apply_transcripts(store: CorpusStore, slug: str, entries: list[TranscriptEntry]) -> ApplyResult:
    """Set the transcript of the upload each entry names; all or nothing.

    A line whose transcript changes goes back to ``pending`` (``CorpusStore.set_text``).
    """
    lines = store.get(slug).lines
    problems: list[str] = []
    targets: dict[str, str] = {}  # line id -> text
    for entry in entries:
        matches = [
            line
            for line in lines
            if line.original_name == entry.name or _stem(line.original_name) == entry.name
        ]
        if not matches:
            problems.append(f"找不到對應的音檔：{entry.name[:80]}")
        elif len(matches) > 1:
            problems.append(f"有多個同名的音檔，無法判斷逐字稿屬於哪一個：{entry.name[:80]}")
        elif matches[0].id in targets:
            problems.append(f"同一個音檔有重複的逐字稿：{entry.name[:80]}")
        else:
            targets[matches[0].id] = entry.text
    if problems:
        raise TranscriptError(problems)
    for line_id, text in targets.items():
        store.set_text(slug, line_id, text)
    return ApplyResult(
        applied=len(targets),
        without_transcript=[line.id for line in lines if line.id not in targets and not line.text],
    )
