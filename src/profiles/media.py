# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Validated silent clips and bounded, server-side directed role transitions."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from uuid import uuid4

import cv2
import numpy as np

from src.profiles.store import ProfileError
from src.scene.service import scene_service
from src.utils.paths import get_data_dir

WIDTH, HEIGHT, FPS = 720, 1280, 25
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


class _VideoReader:
    """A small producer queue; a 30-second clip never becomes 750 raw frames."""
    def __init__(self, path, frames):
        self.frames = frames
        self.queue = queue.Queue(maxsize=3)
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.last = None
        self.last_index = -1
        self._next = None
        self.failed = False
        self.thread = threading.Thread(target=self._run, args=(path,), daemon=True,
                                       name="avatar-transition-video")
        self.thread.start()
        if not self.ready.wait(2) or self.failed:
            self.close()
            raise ProfileError("轉場影片暫時無法播放")

    def _run(self, path):
        capture = cv2.VideoCapture(str(path))
        try:
            for index in range(self.frames):
                if self.stop.is_set():
                    return
                ok, frame = capture.read()
                if not ok:
                    self.failed = True
                    return
                while not self.stop.is_set():
                    try:
                        self.queue.put((index, frame), timeout=.05)
                        self.ready.set()
                        break
                    except queue.Full:
                        continue
        finally:
            capture.release()
            self.ready.set()

    def frame(self, index):
        while True:
            if self._next is None:
                try:
                    self._next = self.queue.get_nowait()
                except queue.Empty:
                    break
            if self._next[0] > index:
                break
            self.last_index, self.last = self._next
            self._next = None
        return self.last

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)


def fit_frame(frame, background=None):
    height, width = frame.shape[:2]
    ratio = min(WIDTH / width, HEIGHT / height)
    resized = cv2.resize(frame, (max(1, round(width * ratio)), max(1, round(height * ratio))),
                         interpolation=cv2.INTER_AREA if ratio < 1 else cv2.INTER_LINEAR)
    canvas = background.copy() if background is not None else np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    y, x = (HEIGHT - resized.shape[0]) // 2, (WIDTH - resized.shape[1]) // 2
    canvas[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
    return canvas


class RolePresentation:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.last_raw = None
        self.transition = None
        self.marker = {}

    def begin(self, transition_id, edge, *, reader=None, started_at=None):
        with self.lock:
            self.close()
            self.transition = dict(id=transition_id, edge=dict(edge), reader=reader,
                                   started=self.clock() if started_at is None else started_at,
                                   previous=self.last_raw.copy() if self.last_raw is not None else None)

    def close(self):
        with self.lock:
            if self.transition and self.transition["reader"]:
                self.transition["reader"].close()
            self.transition = None
            self.marker = {}

    def compose(self, frame, *, green_screen):
        from src.scene.service import chroma_composite
        with self.lock:
            canvas = np.full((HEIGHT, WIDTH, 3), (0, 255, 0), np.uint8) if green_screen else None
            raw = fit_frame(frame, canvas)
            self.last_raw = raw
            background = scene_service.background_frame(WIDTH, HEIGHT)
            if background is None:
                background = np.full_like(raw, (0, 255, 0)) if green_screen else np.zeros_like(raw)
            current = chroma_composite(raw, background) if green_screen else raw
            transition = self.transition
            if not transition:
                return current
            if self.clock() < transition["started"]:
                # Keep the source visible while other peers finish binding.
                # Reading frame zero here exposes the clip before its common
                # start time, then makes it appear to play again at that time.
                self.marker = {}
                previous = transition["previous"]
                if previous is None:
                    return current
                return chroma_composite(previous, background) if green_screen else previous.copy()
            edge, reader = transition["edge"], transition["reader"]
            if reader is not None and reader.failed:
                reader.close()
                transition.update(reader=None, started=self.clock(),
                                  edge={"kind": "effect", "effect": "fade", "duration": .6})
                edge, reader = transition["edge"], None
            elapsed = max(0., self.clock() - transition["started"])
            duration = reader.frames / FPS if reader else edge.get("duration", .6)
            progress = min(1., elapsed / duration)
            completed = progress >= 1
            if reader and not reader.failed:
                requested = min(reader.frames - 1, int(elapsed * FPS))
                clip = reader.frame(requested)
                if clip is not None:
                    current = fit_frame(clip, background)
                completed = completed and reader.last_index >= reader.frames - 1
            else:
                previous = transition["previous"] if transition["previous"] is not None else raw
                effect = edge.get("effect", "fade")
                if effect == "fade":
                    old = chroma_composite(previous, background) if green_screen else previous
                    current = cv2.addWeighted(old, 1-progress, current, progress, 0)
                else:
                    old_canvas = np.full_like(raw, (0, 255, 0))
                    new_canvas = old_canvas.copy()
                    if effect in {"slide_left", "slide_right"}:
                        direction = -1 if effect == "slide_left" else 1
                        shift = round(WIDTH * progress) * direction
                        matrix = np.float32([[1, 0, shift], [0, 1, 0]])
                        old_canvas = cv2.warpAffine(previous, matrix, (WIDTH, HEIGHT), borderValue=(0,255,0))
                        matrix[0, 2] = shift - direction * WIDTH
                        new_canvas = cv2.warpAffine(raw, matrix, (WIDTH, HEIGHT), borderValue=(0,255,0))
                    else:
                        for source, target, scale in ((previous, old_canvas, 1-progress), (raw, new_canvas, progress)):
                            if scale > .001:
                                small = cv2.resize(source, (max(1, round(WIDTH*scale)), max(1, round(HEIGHT*scale))))
                                x, y = (WIDTH-small.shape[1])//2, (HEIGHT-small.shape[0])//2
                                target[y:y+small.shape[0], x:x+small.shape[1]] = small
                    current = chroma_composite(new_canvas, chroma_composite(old_canvas, background))
            self.marker = {"role_transition_id": transition["id"], "role_transition_end": completed}
            return current
