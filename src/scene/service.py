# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""One shared stage background, decoded away from the avatar render thread."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from src.utils.paths import get_data_dir

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
VIDEO_EXTS = frozenset({".mp4", ".mov", ".webm"})
GIF_EXTS = frozenset({".gif"})
BACKGROUND_EXTS = IMAGE_EXTS | VIDEO_EXTS | GIF_EXTS
MAX_BACKGROUND_BYTES = 100 * 1024 * 1024
MAX_BACKGROUND_PIXELS = 4096 * 4096
_ID = re.compile(r"^[0-9a-f]{12}$")
_ARCHIVE_NAME = re.compile(r"^([0-9a-f]{12})-([0-9a-f]{12})$")


class SceneError(ValueError):
    """Invalid background asset or selection."""


def backgrounds_root() -> Path:
    return get_data_dir() / "backgrounds"


def _asset_paths(background_id: str) -> tuple[Path, Path, Path]:
    if not _ID.fullmatch(background_id):
        raise SceneError("無效的背景 ID")
    root = backgrounds_root()
    metadata = root / f"{background_id}.json"
    preview = root / f"{background_id}.preview.jpg"
    if not metadata.is_file() or metadata.is_symlink():
        raise SceneError("找不到背景")
    try:
        info = json.loads(metadata.read_text(encoding="utf-8"))
        ext = str(info["extension"])
        if ext not in BACKGROUND_EXTS:
            raise ValueError("bad extension")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SceneError("背景資料損壞") from exc
    asset = root / f"{background_id}{ext}"
    if not asset.is_file() or asset.is_symlink():
        raise SceneError("找不到背景檔案")
    return asset, metadata, preview


def _first_frame(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".gif":
        try:
            with Image.open(path) as image:
                frame = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise SceneError("無法讀取 GIF 背景") from exc
    elif path.suffix.lower() in IMAGE_EXTS:
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    else:
        cap = cv2.VideoCapture(str(path))
        try:
            ok, frame = cap.read() if cap.isOpened() else (False, None)
            if not ok:
                frame = None
        finally:
            cap.release()
    if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
        raise SceneError("無法解碼背景，請換一個圖片、GIF 或影片")
    if frame.shape[0] * frame.shape[1] > MAX_BACKGROUND_PIXELS:
        raise SceneError("背景解析度過高，請使用 4096×4096 像素以內的素材")
    return frame


def add_background(path: Path, original_name: str) -> dict[str, Any]:
    """Validate an already uploaded file, then publish it in the local catalog."""
    extension = Path(original_name).suffix.lower()
    if extension not in BACKGROUND_EXTS:
        raise SceneError("背景支援 JPG、PNG、WebP、GIF、MP4、MOV、WebM")
    if not path.is_file() or path.stat().st_size == 0:
        raise SceneError("背景檔案是空的")
    if path.stat().st_size > MAX_BACKGROUND_BYTES:
        raise SceneError("背景檔案不可超過 100 MB")
    frame = _first_frame(path)
    background_id = uuid.uuid4().hex[:12]
    root = backgrounds_root()
    root.mkdir(parents=True, exist_ok=True)
    asset = root / f"{background_id}{extension}"
    metadata = root / f"{background_id}.json"
    preview = root / f"{background_id}.preview.jpg"
    label = Path(original_name).stem.strip()[:80] or "背景"
    kind = "gif" if extension in GIF_EXTS else "video" if extension in VIDEO_EXTS else "image"
    # Keep the sidecar last: catalog readers never see a half-published asset.
    try:
        path.replace(asset)
        thumb = _cover(frame, 320, 180)
        if not cv2.imwrite(str(preview), thumb):
            raise SceneError("無法儲存背景預覽")
        metadata.write_text(
            json.dumps({"id": background_id, "label": label, "extension": extension,
                        "kind": kind}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        asset.unlink(missing_ok=True)
        preview.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        raise
    return {"id": background_id, "label": label, "kind": kind,
            "preview_url": f"/api/backgrounds/{background_id}/preview"}


def list_backgrounds() -> list[dict[str, Any]]:
    root = backgrounds_root()
    if not root.is_dir():
        return []
    items = []
    for metadata in sorted(root.glob("*.json")):
        try:
            background_id = metadata.stem
            asset, _, preview = _asset_paths(background_id)
            info = json.loads(metadata.read_text(encoding="utf-8"))
            items.append({"id": background_id, "label": str(info.get("label") or background_id),
                          "kind": info.get("kind", "image"),
                          "preview_url": f"/api/backgrounds/{background_id}/preview" if preview.is_file() else None,
                          "bytes": asset.stat().st_size})
        except (SceneError, OSError, ValueError):
            continue
    return items


def preview_path(background_id: str) -> Path:
    _, _, preview = _asset_paths(background_id)
    if not preview.is_file() or preview.is_symlink():
        raise SceneError("找不到背景預覽")
    return preview


def _archived_background_files(archive_name: str) -> tuple[str, Path, Path, Path, dict[str, Any]]:
    match = _ARCHIVE_NAME.fullmatch(archive_name)
    if match is None:
        raise SceneError("無效的封存背景")
    background_id = match.group(1)
    folder = backgrounds_root() / ".deleted" / archive_name
    if not folder.is_dir() or folder.is_symlink():
        raise SceneError("找不到封存背景")
    metadata = folder / f"{background_id}.json"
    try:
        if metadata.is_symlink():
            raise ValueError("symlink")
        info = json.loads(metadata.read_text(encoding="utf-8"))
        extension = info["extension"]
        if info.get("id") != background_id or extension not in BACKGROUND_EXTS:
            raise ValueError("invalid metadata")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SceneError("封存背景資料損壞") from exc
    asset = folder / f"{background_id}{extension}"
    preview = folder / f"{background_id}.preview.jpg"
    if any(not path.is_file() or path.is_symlink() for path in (asset, preview)):
        raise SceneError("封存背景檔案不完整")
    return background_id, asset, metadata, preview, info


def archive_background(background_id: str) -> Path:
    """Move an inactive background and its preview into the local recycle bin."""
    asset, metadata, preview = _asset_paths(background_id)
    preview_path(background_id)
    recycle_bin = backgrounds_root() / ".deleted"
    recycle_bin.mkdir(parents=True, exist_ok=True)
    destination = recycle_bin / f"{background_id}-{uuid.uuid4().hex[:12]}"
    destination.mkdir()
    moved: list[tuple[Path, Path]] = []
    try:
        # Move metadata last so catalog readers stop seeing this asset only
        # after its image and preview have been archived.
        for source in (asset, preview, metadata):
            target = destination / source.name
            source.replace(target)
            moved.append((source, target))
    except Exception:
        for source, target in reversed(moved):
            target.replace(source)
        destination.rmdir()
        raise
    return destination


def list_archived_backgrounds() -> list[dict[str, str]]:
    recycle_bin = backgrounds_root() / ".deleted"
    if not recycle_bin.is_dir():
        return []
    items = []
    for folder in sorted(recycle_bin.iterdir()):
        try:
            background_id, _, _, _, info = _archived_background_files(folder.name)
            items.append({"archive_name": folder.name, "id": background_id,
                          "label": str(info.get("label") or background_id),
                          "kind": str(info.get("kind") or "image")})
        except SceneError:
            continue
    return items


def restore_background(archive_name: str) -> str:
    background_id, asset, metadata, preview, _ = _archived_background_files(archive_name)
    root = backgrounds_root()
    sources = (asset, preview, metadata)
    targets = tuple(root / source.name for source in sources)
    if any(target.exists() or target.is_symlink() for target in targets):
        raise SceneError("同 ID 背景已存在，無法復原")
    moved: list[tuple[Path, Path]] = []
    try:
        for source, target in zip(sources, targets):
            source.replace(target)
            moved.append((source, target))
    except Exception:
        for source, target in reversed(moved):
            target.replace(source)
        raise
    (backgrounds_root() / ".deleted" / archive_name).rmdir()
    return background_id


def _cover(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    source_height, source_width = frame.shape[:2]
    scale = max(width / source_width, height / source_height)
    scaled_width = max(width, int(round(source_width * scale)))
    scaled_height = max(height, int(round(source_height * scale)))
    method = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(frame, (scaled_width, scaled_height), interpolation=method)
    left = (scaled_width - width) // 2
    top = (scaled_height - height) // 2
    return resized[top:top + height, left:left + width]


class _BackgroundSource:
    def __init__(self, path: Path):
        self.path = path
        self.kind = "gif" if path.suffix == ".gif" else "video" if path.suffix in VIDEO_EXTS else "image"
        self._frame = _first_frame(path)
        self._sequence = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cached: tuple[int, int, int, np.ndarray] | None = None
        if self.kind != "image":
            self._thread = threading.Thread(target=self._run, name="stage-background", daemon=True)
            self._thread.start()

    def _publish(self, frame: np.ndarray) -> None:
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.shape[0] * frame.shape[1] > MAX_BACKGROUND_PIXELS:
            return
        with self._lock:
            self._frame = frame
            self._sequence += 1
            self._cached = None

    def _run(self) -> None:
        if self.kind == "gif":
            self._run_gif()
        else:
            self._run_video()

    def _run_gif(self) -> None:
        try:
            with Image.open(self.path) as image:
                while not self._stop.is_set():
                    for index in range(getattr(image, "n_frames", 1)):
                        if self._stop.is_set():
                            return
                        image.seek(index)
                        frame = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
                        self._publish(frame)
                        duration = min(1.0, max(0.02, float(image.info.get("duration", 100)) / 1000))
                        if self._stop.wait(duration):
                            return
        except (OSError, UnidentifiedImageError, ValueError):
            return  # Keep the last valid frame visible.

    def _run_video(self) -> None:
        cap = cv2.VideoCapture(str(self.path))
        try:
            if not cap.isOpened():
                return
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 25)
            if not 1 <= fps <= 120:
                fps = 25
            interval = 1 / fps
            deadline = time.monotonic()
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                    if not ok:
                        return
                self._publish(frame)
                deadline += interval
                if self._stop.wait(max(0, deadline - time.monotonic())):
                    return
                if deadline < time.monotonic() - interval:
                    deadline = time.monotonic()
        finally:
            cap.release()

    def raw_frame(self) -> np.ndarray:
        with self._lock:
            return self._frame

    def frame(self, width: int, height: int) -> np.ndarray:
        with self._lock:
            seq, raw, cached = self._sequence, self._frame, self._cached
        if cached is not None and cached[:3] == (seq, width, height):
            return cached[3]
        scaled = _cover(raw, width, height)
        with self._lock:
            if self._sequence == seq:
                self._cached = (seq, width, height, scaled)
        return scaled

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)


# Foreground at excess <= 20; fully green screen at excess >= 85. The
# smoothstep ramp (instead of a linear one) avoids a banding seam at either end.
_KEY_LOW = 20
_KEY_HIGH = 85
_ramp = np.clip((np.arange(256, dtype=np.float64) - _KEY_LOW) / (_KEY_HIGH - _KEY_LOW), 0.0, 1.0)
_ALPHA_LUT = np.rint(255.0 * (1.0 - _ramp * _ramp * (3.0 - 2.0 * _ramp))).astype(np.uint8)
del _ramp

# Measured on real green-screen source footage (ambient bounce light around
# hair/shoulders): the spill halo runs 15-20px wide at 1920px frame height,
# far past a fixed few-pixel band. Scale with frame height so shorter/taller
# source recordings get a proportional despill radius.
_DESPILL_RADIUS_MIN = 6.0
_DESPILL_RADIUS_MAX = 40.0
_DESPILL_RADIUS_RATIO = 0.01
# Pixels within this many pixels of the transition always get full-strength
# despill, matching the immediate fringe the previous fixed edge band caught;
# only beyond it does strength taper out to `radius`.
_DESPILL_CORE_PX = 2.0


def chroma_composite(foreground: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Soft green key on the *final* MuseTalk frame, including its visual transition."""
    if foreground.shape != background.shape:
        raise ValueError("人物與背景尺寸不一致")
    # This runs on the render thread for every frame (40ms budget at 25fps), so
    # full-frame work stays in uint8 OpenCV ops; float math touches only the
    # silhouette band (~5% of a portrait frame) that is blended or despilled.
    blue, green, red = cv2.split(foreground)
    excess = cv2.subtract(green, cv2.max(blue, red))
    raw_alpha = cv2.LUT(excess, _ALPHA_LUT)
    alpha = cv2.GaussianBlur(raw_alpha, (5, 5), 1.0)

    # Ambient green spill bleeds well beyond the alpha transition itself, so
    # despill strength falls off with distance from any keyed pixel.
    radius = float(np.clip(foreground.shape[0] * _DESPILL_RADIUS_RATIO,
                           _DESPILL_RADIUS_MIN, _DESPILL_RADIUS_MAX))
    keyed = cv2.compare(excess, _KEY_LOW, cv2.CMP_GT)
    distance = cv2.distanceTransform(cv2.bitwise_not(keyed), cv2.DIST_L2, 3)
    near_edge = cv2.compare(distance, radius + _DESPILL_CORE_PX, cv2.CMP_LT)
    band = cv2.bitwise_and(
        cv2.bitwise_or(cv2.inRange(alpha, 1, 254), near_edge),
        cv2.compare(alpha, 0, cv2.CMP_GT),
    )

    out = background.copy()
    cv2.copyTo(foreground, cv2.compare(alpha, 255, cv2.CMP_EQ), out)
    ys, xs = np.nonzero(band)
    if ys.size == 0:
        return out
    pixels = foreground[ys, xs].astype(np.float32)
    bg_strength = 1.0 - raw_alpha[ys, xs].astype(np.float32) / 255.0
    tapered = np.maximum(0.0, distance[ys, xs] - _DESPILL_CORE_PX)
    despill = np.maximum(np.clip(1.0 - tapered / radius, 0.0, 1.0), bg_strength)
    green_px = pixels[:, 1]
    clean_green = np.minimum(green_px, np.maximum(pixels[:, 0], pixels[:, 2]))
    pixels[:, 1] = green_px * (1.0 - despill) + clean_green * despill
    weight = (alpha[ys, xs].astype(np.float32) / 255.0)[:, None]
    blended = pixels * weight + background[ys, xs].astype(np.float32) * (1.0 - weight)
    out[ys, xs] = np.clip(np.rint(blended), 0, 255).astype(np.uint8)
    return out


class SceneService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._background_id = ""
        self._source: _BackgroundSource | None = None
        self._previous_frame: np.ndarray | None = None
        self._changed_at = 0.0
        self._fade_seconds = 0.2
        self._revision = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"background_id": self._background_id, "revision": self._revision}

    def select(self, background_id: str, *, fade_seconds: float | None = None) -> dict[str, Any]:
        background_id = str(background_id or "").strip()
        with self._lock:
            if background_id == self._background_id:
                return self.snapshot()
        path = _asset_paths(background_id)[0] if background_id else None
        incoming = _BackgroundSource(path) if path else None
        with self._lock:
            previous = self._source
            self._previous_frame = previous.raw_frame() if previous is not None else None
            self._source = incoming
            self._background_id = background_id
            self._changed_at = time.monotonic()
            if fade_seconds is not None:
                self._fade_seconds = max(0.0, min(1.0, float(fade_seconds)))
            self._revision += 1
            result = self.snapshot()
        if previous is not None:
            previous.close()
        return result

    def background_frame(self, width: int, height: int, *, transition: bool = True) -> np.ndarray | None:
        with self._lock:
            source = self._source
            previous = self._previous_frame
            changed_at = self._changed_at
            fade_seconds = self._fade_seconds
        if source is None:
            return None
        current = source.frame(width, height)
        elapsed = time.monotonic() - changed_at
        if not transition or previous is None or fade_seconds <= 0 or elapsed >= fade_seconds:
            return current
        old = _cover(previous, width, height)
        ratio = max(0.0, min(1.0, elapsed / fade_seconds))
        return cv2.addWeighted(old, 1 - ratio, current, ratio, 0)

    def compose(self, frame: np.ndarray, *, green_screen: bool, preview: bool = False) -> np.ndarray:
        if not green_screen:
            return frame
        background = self.background_frame(frame.shape[1], frame.shape[0], transition=not preview)
        if background is None:
            return frame
        return chroma_composite(frame, background)

    def close(self) -> None:
        with self._lock:
            source, self._source = self._source, None
        if source is not None:
            source.close()


scene_service = SceneService()


def render_avatar_preview(avatar_id: str, scene: SceneService = scene_service) -> bytes:
    """Return the same foreground/background combination for console still previews."""
    from src.avatars.catalog import avatar_uses_green_screen, resolve_preview_path

    path = resolve_preview_path(avatar_id)
    if path is None or not path.is_file():
        raise SceneError("找不到數字人預覽圖")
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise SceneError("無法讀取數字人預覽圖")
    composed = scene.compose(frame, green_screen=avatar_uses_green_screen(avatar_id), preview=True)
    ok, encoded = cv2.imencode(".jpg", composed, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise SceneError("無法產生場景預覽圖")
    return encoded.tobytes()
