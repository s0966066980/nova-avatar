# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Reference-audio library and the rules for TTS inputs that name files or servers.

Administrators upload reference audio; it is decoded, checked and stored as
``data/voices/<id>.wav``. TTS settings then name a voice by its library ID, so
a settings request can never point an engine at an arbitrary file on the host.
The same module checks the TTS server address (loopback only) and migrates
saved settings written before these rules existed.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from src.utils.audio_container import HEADER_BYTES, demuxer_for
from src.utils.logging import logger
from src.utils.paths import get_project_root

VOICES_ROOT = get_project_root() / "data" / "voices"
# Saved paths under these roots are imported into the library on load; any
# other saved path is cleared.
MIGRATION_ROOTS = (get_project_root() / "data", Path.home() / "CosyVoice" / "asset")

VOICE_ID = re.compile(r"[0-9a-f]{16}")
# Edge voice names name voices on the server side.
SERVER_SIDE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
# The only TTS engines; src.tts.factory builds exactly these.
TTS_ENGINES = frozenset({"edgetts", "breezyvoice"})
REFERENCE_AUDIO_ENGINES = frozenset({"breezyvoice"})
DEFAULT_EDGE_VOICE = "zh-TW-HsiaoChenNeural"
# Settings of TTS engines removed in 2026; dropped from saved settings on load.
REMOVED_TTS_FIELDS = ("mode", "language", "speaker", "instruct", "device")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_SECONDS = 60.0
MIN_SECONDS = 0.5
MAX_NAME_CHARS = 80
# What the reference recording says, for engines that clone from audio + text.
MAX_TRANSCRIPT_CHARS = 500
SUPPORTED_FORMATS = "WAV、MP3、FLAC、OGG、M4A、WebM"


class VoiceLibraryError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------------ library


def voices_root() -> Path:
    return VOICES_ROOT


def _record_path(voice_id: str) -> Path:
    return voices_root() / f"{voice_id}.json"


def voice_path(voice_id: Any) -> Path:
    """The stored WAV of a library voice; anything else raises VoiceLibraryError."""
    if not isinstance(voice_id, str) or not VOICE_ID.fullmatch(voice_id):
        raise VoiceLibraryError("參考音訊不在音訊庫中，請從音訊庫選擇或上傳", status=404)
    path = voices_root() / f"{voice_id}.wav"
    if path.is_symlink() or not path.is_file():
        raise VoiceLibraryError("參考音訊不在音訊庫中，請從音訊庫選擇或上傳", status=404)
    return path


def _read_record(voice_id: str) -> dict:
    try:
        record = json.loads(_record_path(voice_id).read_text("utf-8"))
    except (OSError, ValueError):
        record = {}
    if not isinstance(record, dict):
        record = {}
    name = record.get("name")
    seconds = record.get("seconds")
    transcript = record.get("transcript")
    return {
        "id": voice_id,
        "name": name if isinstance(name, str) and name else voice_id,
        "seconds": float(seconds) if isinstance(seconds, (int, float)) else 0.0,
        "transcript": transcript if isinstance(transcript, str) else "",
        # Recordings without the speaker's consent, for development only.
        "development": record.get("development") is True,
    }


def voice_transcript(voice_id: Any) -> str:
    """The stored transcript of a library voice; "" when none is selected or recorded."""
    if voice_id is None or (isinstance(voice_id, str) and not voice_id.strip()):
        return ""
    voice_path(voice_id)
    return _read_record(voice_id)["transcript"]


def list_voices() -> list[dict]:
    root = voices_root()
    try:
        paths = [path for path in root.glob("*.wav") if VOICE_ID.fullmatch(path.stem)]
    except OSError:
        return []
    voices = []
    for path in sorted(paths, key=lambda item: (item.stat().st_mtime, item.stem)):
        if path.is_file() and not path.is_symlink():
            voices.append(_read_record(path.stem))
    return voices


def _clean_name(name: Any, fallback: str) -> str:
    text = name if isinstance(name, str) else ""
    text = "".join(char for char in text if char.isprintable()).strip()
    return text[:MAX_NAME_CHARS] or fallback


def _clean_transcript(transcript: Any) -> str:
    text = transcript if isinstance(transcript, str) else ""
    text = "".join(char for char in text if char.isprintable()).strip()
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise VoiceLibraryError(f"參考音訊逐字稿不可超過 {MAX_TRANSCRIPT_CHARS} 字")
    return text


def _sniff_format(path: Path) -> str:
    """The FFmpeg demuxer for ``path`` (see src.utils.audio_container)."""
    try:
        with path.open("rb") as handle:
            head = handle.read(HEADER_BYTES)
    except OSError as exc:
        raise VoiceLibraryError("無法讀取上傳的音訊") from exc
    fmt = demuxer_for(head)
    if fmt is None:
        raise VoiceLibraryError(f"不是支援的音訊檔，請上傳 {SUPPORTED_FORMATS}")
    return fmt


def _decode(path: Path):
    """Decode at most MAX_SECONDS of mono 16-bit audio; returns (samples, rate)."""
    import av
    import numpy as np

    fmt = _sniff_format(path)
    try:
        container = av.open(str(path), format=fmt)
    except Exception as exc:
        raise VoiceLibraryError(f"無法解析音訊檔，請上傳 {SUPPORTED_FORMATS}") from exc
    try:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None or not stream.rate or not 8000 <= stream.rate <= 192000:
            raise VoiceLibraryError("檔案沒有可用的音訊軌")
        duration = None
        if container.duration:
            duration = container.duration / 1_000_000
        elif stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)
        if duration is not None and duration > MAX_SECONDS + 0.5:
            raise VoiceLibraryError(f"參考音訊不可超過 {MAX_SECONDS:g} 秒")
        rate = min(max(int(stream.rate), 16000), 48000)
        limit = int(MAX_SECONDS * rate)
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=rate)
        chunks = []
        collected = 0

        def keep(frames):
            nonlocal collected
            for frame in frames:
                samples = frame.to_ndarray().reshape(-1).astype(np.int16)
                collected += samples.size
                if collected > limit + rate // 2:
                    raise VoiceLibraryError(f"參考音訊不可超過 {MAX_SECONDS:g} 秒")
                chunks.append(samples)

        for frame in container.decode(stream):
            keep(resampler.resample(frame))
        keep(resampler.resample(None))
    except VoiceLibraryError:
        raise
    except Exception as exc:
        raise VoiceLibraryError(f"無法解碼音訊檔，請上傳 {SUPPORTED_FORMATS}") from exc
    finally:
        container.close()
    if collected < MIN_SECONDS * rate:
        raise VoiceLibraryError(f"參考音訊太短，至少需要 {MIN_SECONDS:g} 秒")
    return np.concatenate(chunks)[:limit], rate


def add_voice(source: Path, name: Any = "", transcript: Any = "", *, development: bool = False) -> dict:
    """Validate ``source`` as audio, store it as a mono WAV and return its record.

    The ID is derived from the stored audio, so adding the same audio again
    returns the existing voice. ``transcript`` is what the recording says;
    ``development`` marks a recording whose speaker has not consented.
    """
    import soundfile as sf

    spoken = _clean_transcript(transcript)
    samples, rate = _decode(Path(source))
    root = voices_root()
    root.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=root, prefix=".voice-", suffix=".wav", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            sf.write(handle, samples, rate, format="WAV", subtype="PCM_16")
        voice_id = hashlib.sha256(temporary.read_bytes()).hexdigest()[:16]
        target = root / f"{voice_id}.wav"
        if target.is_file() and _record_path(voice_id).is_file():
            return _read_record(voice_id)
        record = {"id": voice_id, "name": _clean_name(name, voice_id),
                  "seconds": round(samples.size / rate, 2), "transcript": spoken}
        if development:
            record["development"] = True
        _write_text(_record_path(voice_id), json.dumps(record, ensure_ascii=False))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    logger.info("已加入參考音訊 %s（%s，%.1f 秒）", voice_id, record["name"], record["seconds"])
    return _read_record(voice_id)


def _write_text(path: Path, text: str) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".voice-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def delete_voice(voice_id: Any) -> Path:
    """Move a voice into the library's ``.deleted`` recycle bin; returns its folder there."""
    path = voice_path(voice_id)
    destination = voices_root() / ".deleted" / f"{voice_id}-{uuid.uuid4().hex[:12]}"
    destination.mkdir(parents=True)
    record = _record_path(voice_id)
    # Move the audio first so list_voices stops showing it straight away.
    path.replace(destination / path.name)
    if record.is_file():
        record.replace(destination / record.name)
    logger.info("已將參考音訊 %s 移入回收桶 %s", voice_id, destination.name)
    return destination


# ------------------------------------------------------------------ input rules


def check_reference(engine: str, value: Any) -> str:
    """``value`` as a reference for ``engine``: a library ID, or a server-side voice name."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise VoiceLibraryError("參考音訊格式不正確")
    value = value.strip()
    if str(engine or "").strip().lower() in REFERENCE_AUDIO_ENGINES:
        if value:
            try:
                voice_path(value)
            except VoiceLibraryError:
                raise VoiceLibraryError(
                    f"參考音訊「{value[:120]}」不在音訊庫中，請從音訊庫選擇或上傳"
                ) from None
        return value
    if value and not SERVER_SIDE_REFERENCE.fullmatch(value):
        raise VoiceLibraryError("聲線名稱只能包含英數字、底線與連字號")
    return value


def _loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return (mapped or address).is_loopback


def check_tts_server(value: Any) -> str:
    """A TTS service address on this host, normalized to ``scheme://host[:port]``."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise VoiceLibraryError("語音服務網址格式不正確")
    value = value.strip()
    if not value:
        return ""
    message = "語音服務只能連線本機（127.0.0.1、localhost 或 ::1），且網址不可包含帳密、路徑或查詢參數"
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        raise VoiceLibraryError(message) from None
    if (parts.scheme not in {"http", "https"} or not host or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or parts.path not in {"", "/"} or not _loopback_host(host)):
        raise VoiceLibraryError(message)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return f"{parts.scheme}://{netloc}"


def check_model(value: Any) -> str:
    """An empty model (engine default) or a model ID from the ``models/`` catalog."""
    from src.tts.cosyvoice_runtime import local_models

    if value is None:
        value = ""
    if not isinstance(value, str):
        raise VoiceLibraryError("TTS 模型格式不正確")
    value = value.strip()
    if value and value not in {item["id"] for item in local_models()}:
        raise VoiceLibraryError(f"TTS 模型「{value[:120]}」不在 models/ 清單中")
    return value


# ------------------------------------------------------------------ saved settings

# Why saved settings were switched to Edge TTS in this process, for the console.
_removed_engine_notices: list[str] = []


def removed_engine_notice() -> str:
    """The console message for saved settings that named a removed TTS engine."""
    return "；".join(dict.fromkeys(_removed_engine_notices))


def clear_removed_engine_notice() -> None:
    _removed_engine_notices.clear()


def _fall_back_to_edge(values: dict, engine: str, where: str) -> None:
    """Switch saved settings of a removed engine to Edge TTS instead of failing."""
    message = (f"{where} 的 TTS 引擎「{engine[:40]}」已移除，已改用 Edge TTS（開發用）；"
               "請到數位人設定檔的「聲音與工具」改選 BreezyVoice 或 Edge TTS 聲線並套用")
    logger.warning(message)
    _removed_engine_notices.append(message)
    values["type"] = "edgetts"
    for key, value in (("ref_file", DEFAULT_EDGE_VOICE), ("ref_text", None),
                       ("tts_server", ""), ("model", "")):
        if key in values:
            values[key] = value


def _import_saved_path(value: str, where: str) -> str:
    """Import a saved reference path under MIGRATION_ROOTS; "" when not allowed."""
    if not value:
        return ""
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = get_project_root() / raw
    try:
        resolved = raw.resolve()
        allowed = any(resolved.is_relative_to(root.resolve()) for root in MIGRATION_ROOTS)
        if allowed and resolved.is_file():
            voice = add_voice(resolved, resolved.stem)
            logger.info("%s 的參考音訊 %s 已移入音訊庫：%s", where, value, voice["id"])
            return voice["id"]
    except (OSError, VoiceLibraryError) as exc:
        logger.warning("%s 的參考音訊 %s 無法移入音訊庫：%s", where, value, exc)
    return ""


def drop_stale_transcript(values: dict, where: str) -> bool:
    """Clear a saved ``ref_text``: the transcript comes only from the voice library.

    The console no longer edits a per-setting transcript, so a saved one would
    silently override the library's. Returns whether one was dropped.
    """
    if not values.get("ref_text"):
        return False
    logger.warning("%s 的 tts.ref_text 已停用（逐字稿只來自音訊庫），已移除：%r", where, values["ref_text"])
    values["ref_text"] = None
    return True


def migrate_tts_values(values: dict, *, where: str) -> bool:
    """Bring saved TTS settings under the current engines and input rules.

    Mutates ``values`` and returns whether anything changed. A removed engine
    becomes Edge TTS, REMOVED_TTS_FIELDS are dropped and a stale ``ref_text``
    is cleared (see drop_stale_transcript). Of ``ref_file`` /
    ``tts_server`` / ``model`` only keys already present are touched: paths
    under MIGRATION_ROOTS move into the library; everything else that breaks
    a rule is cleared and logged.
    """
    changed = False
    for key in REMOVED_TTS_FIELDS:
        if key in values:
            del values[key]
            changed = True
    if drop_stale_transcript(values, where):
        changed = True
    engine =str(values.get("type") or "edgetts").strip().lower()
    if engine not in TTS_ENGINES:
        _fall_back_to_edge(values, engine, where)
        return True
    if "ref_file" in values:
        current = values["ref_file"]
        try:
            updated = check_reference(engine, current)
        except VoiceLibraryError:
            text = current if isinstance(current, str) else ""
            updated = _import_saved_path(text.strip(), where) if engine in REFERENCE_AUDIO_ENGINES else ""
            if not updated:
                if engine == "edgetts":
                    updated = DEFAULT_EDGE_VOICE
                logger.warning("%s 的 tts.ref_file 不是音訊庫 ID，已改為「%s」：%r", where, updated, current)
        if updated != current:
            values["ref_file"] = updated
            changed = True
    for key, check in (("tts_server", check_tts_server), ("model", check_model)):
        if key not in values:
            continue
        current = values[key]
        try:
            updated = check(current)
        except VoiceLibraryError:
            updated = ""
            logger.warning("%s 的 tts.%s 不符合限制，已清空：%r", where, key, current)
        if updated != current:
            values[key] = updated
            changed = True
    return changed


def migrate_tts_config(tts, *, where: str) -> bool:
    """migrate_tts_values for a TTSConfig-like object."""
    keys = ("type", "ref_file", "ref_text", "tts_server", "model")
    values = {key: getattr(tts, key) for key in keys if hasattr(tts, key)}
    changed = migrate_tts_values(values, where=where)
    for key in keys:
        if key in values:
            setattr(tts, key, values[key])
    return changed
