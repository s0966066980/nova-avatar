# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Per-character presentation and versioned, atomically applied video assets."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from threading import RLock

from src.avatars.catalog import avatars_root, is_safe_avatar_id

LOCK = RLock()
SLOTS = ("idle", "talking")


class PresentationError(ValueError):
    pass


def mode(config, avatar_id=None):
    return getattr(config.model, "presentation_modes", {}).get(
        avatar_id or config.model.avatar_id, "musetalk"
    )


def folder(avatar_id):
    if not is_safe_avatar_id(avatar_id):
        raise PresentationError("無效的角色 ID")
    root = avatars_root().resolve()
    character = root / avatar_id
    if not character.is_dir() or character.is_symlink():
        raise PresentationError("找不到角色")
    target = character / "prerecorded"
    if target.is_symlink():
        raise PresentationError("無效的素材目錄")
    target.mkdir(exist_ok=True)
    return target


def media_path(avatar_id, name):
    import re
    if not re.fullmatch(r"[0-9a-f]{32}\.mp4", name):
        raise PresentationError("無效的素材檔名")
    path = folder(avatar_id) / name
    if path.is_symlink() or not path.is_file():
        raise PresentationError("找不到素材")
    return path


def read(avatar_id):
    path = folder(avatar_id) / "manifest.json"
    if not path.exists():
        return {slot: {} for slot in SLOTS}
    try:
        value = json.loads(path.read_text())
        return {slot: value.get(slot, {}) for slot in SLOTS}
    except (OSError, ValueError, TypeError) as exc:
        raise PresentationError("素材設定損毀，請重新上傳") from exc


def _save(avatar_id, value):
    destination = folder(avatar_id) / "manifest.json"
    temporary = destination.with_name(f".{uuid.uuid4().hex}.json")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def candidate(avatar_id, slot, metadata):
    if slot not in SLOTS:
        raise PresentationError("請選擇待機或說話素材")
    with LOCK:
        value = read(avatar_id)
        value[slot]["candidate"] = metadata
        _save(avatar_id, value)


def apply_asset(avatar_id, slot, *, restore=False):
    if slot not in SLOTS:
        raise PresentationError("無效的素材類型")
    with LOCK:
        value = read(avatar_id)
        source = "previous" if restore else "candidate"
        new = value[slot].get(source)
        if not new:
            raise PresentationError("沒有可套用的素材")
        media_path(avatar_id, new["name"])
        other = value[SLOTS[1] if slot == SLOTS[0] else SLOTS[0]].get("current")
        if other and (new["width"], new["height"]) != (other["width"], other["height"]):
            raise PresentationError("待機與說話影片必須使用相同尺寸")
        old = value[slot].get("current")
        value[slot]["current"] = new
        if old:
            value[slot]["previous"] = old
        if not restore:
            value[slot].pop("candidate", None)
        _save(avatar_id, value)


def snapshot(config, avatar_id=None):
    avatar_id = avatar_id or config.model.avatar_id
    try:
        value = read(avatar_id)
    except PresentationError as exc:
        return {"avatar_id": avatar_id, "mode": mode(config, avatar_id), "slots": {s: {} for s in SLOTS},
                "ready": False, "reason": str(exc), "background": None,
                "max_height": 0, "fps": 25}
    errors = []
    for slot in SLOTS:
        item = value[slot].get("current")
        if not item:
            errors.append("缺少" + ("待機" if slot == "idle" else "說話") + "影片")
        else:
            try:
                media_path(avatar_id, item["name"])
            except (PresentationError, KeyError):
                errors.append("素材遺失，請修復或還原")
    if not errors:
        a, b = (value[slot]["current"] for slot in SLOTS)
        if (a["width"], a["height"]) != (b["width"], b["height"]):
            errors.append("待機與說話影片尺寸不一致")
    background = None
    background_id = getattr(config.stage, "background_id", "")
    if background_id:
        from src.scene.service import list_backgrounds
        background = next((item for item in list_backgrounds() if item["id"] == background_id), None)
        if background:
            background = {**background, "url": f"/api/presentation/background/{background_id}"}
            if background["kind"] == "gif":
                background["kind"] = "video"
    return {"avatar_id": avatar_id, "mode": mode(config, avatar_id), "slots": value,
            "ready": not errors, "reason": "；".join(errors), "background": background,
            "max_height": 0, "fps": 25,
            "silence_ms": 300, "transition_ms": 100}


def require_ready(config):
    value = snapshot(config)
    if not value["ready"]:
        raise PresentationError(value["reason"])
    return value


def normalize(source: Path, destination: Path, progress=lambda value: None, cancelled=lambda: False):
    """Stream-decode and resample video timing; never load a whole raw clip."""
    import av
    from fractions import Fraction
    with av.open(str(source)) as incoming:
        if not incoming.streams.video:
            raise PresentationError("影片沒有影像軌")
        stream = incoming.streams.video[0]
        width, height = stream.width, stream.height
        if width <= 0 or height <= 0 or width % 2 or height % 2 or width * height > 3840 * 2160:
            raise PresentationError("影片須為偶數尺寸，最大支援 4K")
        with av.open(str(destination), "w") as output:
            target = output.add_stream("libx264", rate=25)
            target.width, target.height, target.pix_fmt = width, height, "yuv420p"
            target.options = {"crf": "18", "preset": "fast"}
            previous = None
            origin = None
            index = 0
            for frame in incoming.decode(video=0):
                if cancelled():
                    raise InterruptedError("已取消")
                timestamp = frame.time
                if timestamp is None:
                    raise PresentationError("影片缺少影格時間資訊")
                if origin is None:
                    origin = timestamp
                timestamp -= origin
                if timestamp > 600:
                    raise PresentationError("素材影片最長支援十分鐘")
                while previous is not None and index / 25 < timestamp - 0.0001:
                    if cancelled():
                        raise InterruptedError("已取消")
                    previous.pts, previous.time_base = index, Fraction(1, 25)
                    for packet in target.encode(previous):
                        output.mux(packet)
                    index += 1
                previous = frame.reformat(width, height, "yuv420p")
                total = float(stream.duration * stream.time_base) if stream.duration else 0
                progress(min(95, 5 + int(timestamp / total * 90)) if total > 0 else min(95, 5 + int(timestamp * 2)))
            if previous is None:
                raise PresentationError("影片無法解碼")
            duration = (timestamp + 1 / float(stream.average_rate or 25))
            if duration > 600.0001:
                raise PresentationError("素材影片最長支援十分鐘")
            while index / 25 < duration - 0.0001:
                if cancelled():
                    raise InterruptedError("已取消")
                previous.pts, previous.time_base = index, Fraction(1, 25)
                for packet in target.encode(previous):
                    output.mux(packet)
                index += 1
            for packet in target.encode():
                output.mux(packet)
    return {"name": destination.name, "width": width, "height": height,
            "fps": 25, "frames": index, "duration": index / 25, "audio": False}
