# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The library of validated, silent role-transition clips.

The core keeps this library; the avatar rendering layer plays a clip from the
path the core hands it (``AvatarService.open_transition_clip``).
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

import cv2

from nova_contracts.avatar import STAGE_FPS, STAGE_FRAME
from nova_core.profiles.store import ProfileError
from nova_core.utils.paths import get_data_dir

# Imported transition clips are fitted to the stage canvas the renderer composes.
WIDTH, HEIGHT, FPS = STAGE_FRAME.width, STAGE_FRAME.height, STAGE_FPS
MAX_BYTES = 100 * 1024 * 1024
_ID = re.compile(r"[a-f0-9]{12}")


def _probe(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
             "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, timeout=10, check=True)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise ProfileError("無法辨識轉場影片") from exc


class TransitionMedia:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else get_data_dir() / "transitions"

    def get(self, asset_id):
        if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id):
            raise ProfileError("轉場影片識別碼不正確")
        metadata, video = self.root / f"{asset_id}.json", self.root / f"{asset_id}.mp4"
        if metadata.is_symlink() or video.is_symlink() or not metadata.is_file() or not video.is_file():
            raise ProfileError("找不到轉場影片", 404)
        try:
            data = json.loads(metadata.read_text("utf-8"))
            if data.get("id") != asset_id or not 0 < data["duration"] <= 30 or not 1 <= data["frames"] <= 750:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProfileError("轉場影片資料損壞") from exc
        return data, video

    def list(self):
        if not self.root.exists():
            return []
        result = []
        for path in sorted(self.root.glob("*.json")):
            try:
                info, _ = self.get(path.stem)
                result.append(info)
            except ProfileError:
                continue
        return result

    def import_file(self, source, filename):
        source = Path(source)
        if Path(filename).suffix.lower() not in {".mp4", ".mov", ".webm"}:
            raise ProfileError("轉場支援 MP4、MOV 或 WebM")
        if source.stat().st_size > MAX_BYTES or source.stat().st_size == 0:
            raise ProfileError("轉場影片須為 100 MiB 內的有效檔案")
        probe = _probe(source)
        stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
        try:
            duration = float(probe["format"]["duration"])
            width, height = int(stream["width"]), int(stream["height"])
            container = str(probe["format"]["format_name"])
            if not 0 < duration <= 30 or not 0 < width * height <= 4096 * 4096:
                raise ValueError
            if not any(name in container.split(",") for name in ("mov", "mp4", "matroska", "webm")):
                raise ValueError
        except (KeyError, ValueError, TypeError) as exc:
            raise ProfileError("轉場影片須在 30 秒內，且解析度不可超過 4096² 像素") from exc
        self.root.mkdir(parents=True, exist_ok=True)
        asset_id = uuid4().hex[:12]
        temporary = self.root / f".{asset_id}.mp4"
        target, metadata = self.root / f"{asset_id}.mp4", self.root / f"{asset_id}.json"
        published = False
        try:
            # Fit within the stage, retaining the video's original aspect ratio;
            # the live compositor fills the remaining area with the scene.
            process = subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-protocol_whitelist", "file,pipe",
                "-i", str(source), "-map", "0:v:0", "-an", "-sn", "-dn",
                "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                "-t", "31", "-frames:v", "776", "-c:v", "libx264", "-preset", "veryfast",
                "-threads", "2", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(temporary),
            ], capture_output=True, timeout=60)
            if process.returncode or process.stderr.strip():
                raise ProfileError("轉場影片解碼失敗")
            final = _probe(temporary)
            video = next(s for s in final["streams"] if s.get("codec_type") == "video")
            frames = int(video["nb_frames"])
            actual_duration = float(final["format"]["duration"])
            if not 1 <= frames <= 750 or not 0 < actual_duration <= 30 or temporary.stat().st_size > MAX_BYTES:
                raise ProfileError("轉場影片實際時長或大小超過限制")
            if any(s.get("codec_type") == "audio" for s in final["streams"]):
                raise ProfileError("轉場影片音軌移除失敗")
            capture = cv2.VideoCapture(str(temporary))
            try:
                count, first = 0, None
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    count += 1
                    if first is None:
                        first = frame
                    if count > 750:
                        raise ProfileError("轉場影片影格數超過限制")
                if count != frames or first is None:
                    raise ProfileError("轉場影片影格不完整")
            finally:
                capture.release()
            info = dict(id=asset_id, name=Path(filename).name[:150], duration=frames / FPS,
                        frames=frames, width=int(video["width"]), height=int(video["height"]),
                        fps=FPS, silent=True)
            temporary.replace(target)
            metadata.write_text(json.dumps(info, ensure_ascii=False), "utf-8")
            published = True
            return info
        except (OSError, subprocess.SubprocessError, KeyError, ValueError, StopIteration) as exc:
            if isinstance(exc, ProfileError):
                raise
            raise ProfileError("無法完成轉場影片處理") from exc
        finally:
            temporary.unlink(missing_ok=True)
            if not published:
                metadata.unlink(missing_ok=True)
                target.unlink(missing_ok=True)

    def delete(self, asset_id, *, referenced):
        if asset_id in referenced:
            raise ProfileError("請先解除轉場設定再刪除影片", 409)
        _, path = self.get(asset_id)
        path.unlink()
        path.with_suffix(".json").unlink()
