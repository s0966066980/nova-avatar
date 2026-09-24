# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""從閉嘴正面影片生成數字人角色素材。"""
from __future__ import annotations

import json
import pickle
import re
import shutil
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from src.avatars.catalog import (
    IMPORTABLE_ENGINES,
    avatars_root,
    is_safe_avatar_id,
    list_avatar_characters,
)
from src.avatars.mouth_quality import QualityError, normalize_quality
from src.utils.logging import logger
from src.utils.paths import get_data_dir

ProgressCb = Optional[Callable[[int, str], None]]

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"}
MAX_FRAMES = 300
COORD_PLACEHOLDER = (0.0, 0.0, 0.0, 0.0)


class BuildError(Exception):
    pass


def slugify_name(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "_", stem)
    stem = stem.strip("_")[:32]
    return stem


def suggest_avatar_id(engine: str, source_name: str, existing: Optional[set] = None) -> str:
    existing = existing if existing is not None else {
        item["id"] for item in list_avatar_characters()
    }
    slug = slugify_name(source_name)
    base = f"{engine}_{slug}" if slug else f"{engine}_avatar"
    if not is_safe_avatar_id(base):
        base = f"{engine}_avatar"
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def uploads_dir() -> Path:
    path = get_data_dir() / "imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_frames(video_path: Path, dest_dir: Path, max_frames: int = MAX_FRAMES) -> int:
    dest_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise BuildError("無法開啟影片檔案，請換成 mp4 / mov / webm")
    count = 0
    try:
        while count < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            # Keep creation assets clean. The live output adds project branding
            # after any green-screen background composition.
            cv2.imwrite(str(dest_dir / f"{count:08d}.png"), frame)
            count += 1
    finally:
        cap.release()
    if count == 0:
        raise BuildError("影片裡沒有可讀的畫面")
    return count


def build_character(
    engine: str,
    video_path: Path,
    avatar_id: str,
    *,
    overwrite: bool = False,
    progress: ProgressCb = None,
    quality: Optional[dict] = None,
    green_screen: bool = False,
) -> dict:
    engine = (engine or "").strip().lower()
    avatar_id = (avatar_id or "").strip()
    if engine not in IMPORTABLE_ENGINES:
        raise BuildError("這個引擎不能從影片生成角色，請改選 MuseTalk 或 Wav2Lip")
    if not is_safe_avatar_id(avatar_id):
        raise BuildError("角色名稱只能使用字母、數字、下劃線和短橫線")
    if not video_path.is_file():
        raise BuildError("找不到上傳的影片")

    dest = avatars_root() / avatar_id
    if dest.exists() and not overwrite:
        raise BuildError(f"角色 {avatar_id} 已存在，請換一個名稱")

    def report(percent: int, message: str) -> None:
        if progress:
            progress(percent, message)
        logger.info(f"[import {avatar_id}] {percent}% {message}")

    work_dir = dest
    if dest.exists() and overwrite:
        shutil.rmtree(dest)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Keep the exact uploaded source with the generated avatar. Import jobs
        # remove their temporary upload after this build finishes.
        source_name = f"source{video_path.suffix.lower()}"
        shutil.copy2(video_path, work_dir / source_name)
        report(5, "正在抽取影片幀")
        full_imgs = work_dir / "full_imgs"
        frame_count = extract_frames(video_path, full_imgs)
        report(20, f"已抽取 {frame_count} 幀，開始做人臉處理")
        try:
            options = normalize_quality(quality)
        except QualityError as exc:
            raise BuildError(str(exc)) from exc
        options["green_screen"] = bool(green_screen) if engine == "musetalk" else False

        if engine == "musetalk":
            _build_musetalk(work_dir, avatar_id, source_name, report, options)
        else:
            _build_wav2lip(work_dir, report, options)

        report(100, "角色製作完成")
        return {
            "type": engine,
            "avatar_id": avatar_id,
            "frames": frame_count,
        }
    except Exception:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise


def _sorted_images(folder: Path) -> list[Path]:
    images = sorted(
        [p for p in folder.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}],
        key=lambda p: int(p.stem) if p.stem.isdigit() else p.stem,
    )
    if not images:
        raise BuildError("沒有抽到可用的圖片幀")
    return images


def _build_musetalk(
    work_dir: Path,
    avatar_id: str,
    video_path: str,
    report: Callable[[int, str], None],
    options: dict,
) -> None:
    import torch

    from src.avatars.musetalk.utils.blending import get_image_prepare_material
    from src.avatars.musetalk.utils.face_parsing import FaceParsing
    from src.avatars.musetalk.utils.preprocessing import get_landmark_and_bbox

    full_imgs = work_dir / "full_imgs"
    mask_dir = work_dir / "mask"
    mask_dir.mkdir(parents=True, exist_ok=True)
    img_paths = [str(p) for p in _sorted_images(full_imgs)]
    musetalk = options["musetalk"]

    info = {
        "avatar_id": avatar_id,
        "video_path": f"data/avatars/{avatar_id}/{video_path}",
        "source_path": f"data/avatars/{avatar_id}/{video_path}",
        "engine": "musetalk",
        "source_project": "Nova Avatar",
        "source_type": "user_upload",
        "green_screen": bool(options.get("green_screen", False)),
        **musetalk,
        "mouth_sharpen": options["mouth_sharpen"],
        "paste_interpolation": options["paste_interpolation"],
    }
    (work_dir / "avator_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report(30, "正在檢測人臉與關鍵點")
    coord_list, frame_list = get_landmark_and_bbox(img_paths, musetalk["bbox_shift"])
    vae = _musetalk_vae()
    extra_margin = musetalk["extra_margin"]
    latents = []
    kept_coords = []
    kept_frames = []
    for bbox, frame in zip(coord_list, frame_list):
        if tuple(bbox) == COORD_PLACEHOLDER:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox]
        y2 = min(y2 + extra_margin, frame.shape[0])
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        resized = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        latents.append(vae.get_latents_for_unet(resized))
        kept_coords.append([x1, y1, x2, y2])
        kept_frames.append(frame)

    if not latents:
        raise BuildError("沒有檢測到人臉。請使用正面、閉嘴、臉部清晰的短影片")

    report(65, "正在生成口型遮罩")
    # Only frames with matching face coordinates and latents belong in the
    # playable cycle. Removed frames remain recoverable from source_path.
    for image_path in _sorted_images(full_imgs):
        image_path.unlink()
    fp = FaceParsing(
        left_cheek_width=musetalk["left_cheek_width"],
        right_cheek_width=musetalk["right_cheek_width"],
    )
    mask_coords = []
    for index, frame in enumerate(kept_frames):
        cv2.imwrite(str(full_imgs / f"{index:08d}.png"), frame)
        x1, y1, x2, y2 = kept_coords[index]
        mask, crop_box = get_image_prepare_material(
            frame,
            [x1, y1, x2, y2],
            fp=fp,
            mode=musetalk["parsing_mode"],
            upper_boundary_ratio=musetalk["upper_boundary_ratio"],
            expand=musetalk["expand"],
            mask_blur_ratio=musetalk["mask_blur_ratio"],
        )
        cv2.imwrite(str(mask_dir / f"{index:08d}.png"), mask)
        mask_coords.append(crop_box)
        if index == 0 or (index + 1) % 30 == 0:
            report(65 + int(25 * (index + 1) / len(kept_frames)), f"遮罩 {index + 1}/{len(kept_frames)}")

    leftover = list(full_imgs.glob("*.png"))
    keep = {f"{i:08d}.png" for i in range(len(kept_frames))}
    for path in leftover:
        if path.name not in keep:
            path.unlink(missing_ok=True)

    with open(work_dir / "coords.pkl", "wb") as handle:
        pickle.dump(kept_coords, handle)
    with open(work_dir / "mask_coords.pkl", "wb") as handle:
        pickle.dump(mask_coords, handle)
    torch.save(latents, work_dir / "latents.pt")
    del fp


def _musetalk_vae():
    try:
        from src.server.state import state

        if (
            state.config is not None
            and getattr(state.config.model, "type", None) == "musetalk"
            and state.model is not None
        ):
            return state.model[0]
    except Exception:
        pass

    import torch

    from src.avatars.musetalk.utils.utils import load_all_model

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    vae, _unet, _pe = load_all_model(device=device)
    vae.vae = vae.vae.half().to(device)
    return vae


def _build_wav2lip(
    work_dir: Path, report: Callable[[int, str], None], options: dict
) -> None:
    from src.avatars.wav2lip.face_detection import FaceAlignment, LandmarksType

    full_imgs = work_dir / "full_imgs"
    face_imgs = work_dir / "face_imgs"
    face_imgs.mkdir(parents=True, exist_ok=True)
    images = _sorted_images(full_imgs)
    frames = [cv2.imread(str(path)) for path in images]
    frames = [frame for frame in frames if frame is not None]
    if not frames:
        raise BuildError("讀取影片幀失敗")

    report(35, "正在檢測人臉")
    device = "cuda" if _cuda_ready() else "cpu"
    detector = FaceAlignment(LandmarksType._2D, flip_input=False, device=device)
    batch_size = 16
    predictions = []
    try:
        start = 0
        while start < len(frames):
            try:
                chunk = np.array(frames[start:start + batch_size])
                predictions.extend(detector.get_detections_for_batch(chunk))
                start += batch_size
                report(35 + int(40 * start / len(frames)), f"人臉檢測 {min(start, len(frames))}/{len(frames)}")
            except RuntimeError:
                if batch_size == 1:
                    raise BuildError("畫面太大，無法做人臉檢測")
                batch_size //= 2
    finally:
        del detector

    pads = options["wav2lip"]
    pady1, pady2, padx1, padx2 = (
        pads["pad_top"],
        pads["pad_bottom"],
        pads["pad_left"],
        pads["pad_right"],
    )
    raw_boxes = []
    for rect, image in zip(predictions, frames):
        if rect is None:
            raise BuildError("有畫面沒偵測到臉，請使用全程露臉、閉嘴的正面影片")
        y1 = max(0, rect[1] - pady1)
        y2 = min(image.shape[0], rect[3] + pady2)
        x1 = max(0, rect[0] - padx1)
        x2 = min(image.shape[1], rect[2] + padx2)
        raw_boxes.append([x1, y1, x2, y2])

    boxes = _smooth_boxes(np.array(raw_boxes, dtype=np.float32), window=5)
    coords = []
    for index, (box, image) in enumerate(zip(boxes, frames)):
        x1, y1, x2, y2 = [int(v) for v in box]
        y1 = max(0, y1)
        x1 = max(0, x1)
        y2 = min(image.shape[0], y2)
        x2 = min(image.shape[1], x2)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            raise BuildError("人臉裁切失敗，請換一段臉部更居中的影片")
        resized = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        cv2.imwrite(str(face_imgs / f"{index:08d}.png"), resized)
        coords.append((y1, y2, x1, x2))

    with open(work_dir / "coords.pkl", "wb") as handle:
        pickle.dump(coords, handle)


def _smooth_boxes(boxes: np.ndarray, window: int = 5) -> np.ndarray:
    smoothed = boxes.copy()
    length = len(boxes)
    for i in range(length):
        chunk = boxes[i:length] if i + window > length else boxes[i:i + window]
        smoothed[i] = np.mean(chunk, axis=0)
    return smoothed


def _cuda_ready() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False
