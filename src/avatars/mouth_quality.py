# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""嘴型貼回與角色製作的畫質參數。

MuseTalk / Wav2Lip 的口型模型輸出固定 256 像素。貼回較大的臉框時，
插值與銳化決定觀感；臉框位移、下巴留白與遮罩則在製作角色時寫入素材。
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Optional

import cv2
import numpy as np

PASTE_INTERPOLATIONS = ("lanczos", "cubic", "linear")
PARSING_MODES = ("jaw", "raw")

INTERPOLATION_FLAGS = {
    "lanczos": cv2.INTER_LANCZOS4,
    "cubic": cv2.INTER_CUBIC,
    "linear": cv2.INTER_LINEAR,
}

DEFAULT_MOUTH_SHARPEN = 0.5
DEFAULT_PASTE_INTERPOLATION = "lanczos"

DEFAULT_MUSETALK = {
    "bbox_shift": 0,
    "extra_margin": 10,
    "parsing_mode": "jaw",
    "left_cheek_width": 90,
    "right_cheek_width": 90,
    "upper_boundary_ratio": 0.5,
    "expand": 1.5,
    "mask_blur_ratio": 0.05,
    "mouth_continuity": True,
    "mouth_continuity_idle_alignment": True,
    "settling_enabled": True,
    "settling_frames": 12,
}

DEFAULT_WAV2LIP = {
    "pad_top": 0,
    "pad_bottom": 10,
    "pad_left": 0,
    "pad_right": 0,
}

_LIMITS = {
    "mouth_sharpen": (0.0, 2.0),
    "bbox_shift": (-30, 30),
    "extra_margin": (0, 40),
    "left_cheek_width": (20, 160),
    "right_cheek_width": (20, 160),
    "upper_boundary_ratio": (0.3, 0.7),
    "expand": (1.2, 2.0),
    "mask_blur_ratio": (0.0, 0.15),
    "settling_frames": (1, 50),
    "pad_top": (0, 40),
    "pad_bottom": (0, 40),
    "pad_left": (0, 40),
    "pad_right": (0, 40),
}


class QualityError(ValueError):
    pass


def default_quality() -> dict[str, Any]:
    return {
        "mouth_sharpen": DEFAULT_MOUTH_SHARPEN,
        "paste_interpolation": DEFAULT_PASTE_INTERPOLATION,
        "musetalk": dict(DEFAULT_MUSETALK),
        "wav2lip": dict(DEFAULT_WAV2LIP),
    }


def quality_from_model(model: Any) -> dict[str, Any]:
    payload = default_quality()
    if model is None:
        return payload
    payload["mouth_sharpen"] = float(
        getattr(model, "mouth_sharpen", payload["mouth_sharpen"])
    )
    interpolation = str(
        getattr(model, "paste_interpolation", payload["paste_interpolation"])
    ).strip().lower()
    payload["paste_interpolation"] = (
        interpolation if interpolation in PASTE_INTERPOLATIONS else DEFAULT_PASTE_INTERPOLATION
    )
    payload["musetalk"] = _mapping_or_defaults(
        getattr(model, "musetalk", None), DEFAULT_MUSETALK
    )
    payload["wav2lip"] = _mapping_or_defaults(
        getattr(model, "wav2lip", None), DEFAULT_WAV2LIP
    )
    return payload


def normalize_quality(params: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    source = dict(params or {})
    current = default_quality()
    musetalk_in = source.get("musetalk") if isinstance(source.get("musetalk"), Mapping) else {}
    wav2lip_in = source.get("wav2lip") if isinstance(source.get("wav2lip"), Mapping) else {}
    nested_keys = set(DEFAULT_MUSETALK) | set(DEFAULT_WAV2LIP)
    flat = {key: source[key] for key in nested_keys if key in source}

    mouth_sharpen = source.get("mouth_sharpen", current["mouth_sharpen"])
    interpolation = str(
        source.get("paste_interpolation", current["paste_interpolation"])
    ).strip().lower()
    if interpolation not in PASTE_INTERPOLATIONS:
        raise QualityError("貼回插值只能是 lanczos、cubic 或 linear")

    musetalk = dict(DEFAULT_MUSETALK)
    musetalk.update(musetalk_in)
    for key in DEFAULT_MUSETALK:
        if key in flat:
            musetalk[key] = flat[key]

    wav2lip = dict(DEFAULT_WAV2LIP)
    wav2lip.update(wav2lip_in)
    for key in DEFAULT_WAV2LIP:
        if key in flat:
            wav2lip[key] = flat[key]

    musetalk["bbox_shift"] = _bounded_int(musetalk["bbox_shift"], "bbox_shift")
    musetalk["extra_margin"] = _bounded_int(musetalk["extra_margin"], "extra_margin")
    musetalk["left_cheek_width"] = _bounded_int(
        musetalk["left_cheek_width"], "left_cheek_width"
    )
    musetalk["right_cheek_width"] = _bounded_int(
        musetalk["right_cheek_width"], "right_cheek_width"
    )
    musetalk["upper_boundary_ratio"] = _bounded_float(
        musetalk["upper_boundary_ratio"], "upper_boundary_ratio"
    )
    musetalk["expand"] = _bounded_float(musetalk["expand"], "expand")
    musetalk["mask_blur_ratio"] = _bounded_float(
        musetalk["mask_blur_ratio"], "mask_blur_ratio"
    )
    musetalk["mouth_continuity"] = bool(musetalk.get("mouth_continuity", True))
    musetalk["mouth_continuity_idle_alignment"] = bool(
        musetalk.get("mouth_continuity_idle_alignment", True)
    )
    musetalk["settling_enabled"] = bool(
        musetalk.get("settling_enabled", True)
    )
    musetalk["settling_frames"] = _bounded_int(
        musetalk.get("settling_frames", 12), "settling_frames"
    )
    parsing_mode = str(musetalk.get("parsing_mode", "jaw")).strip().lower()
    if parsing_mode not in PARSING_MODES:
        raise QualityError("融合遮罩只能是 jaw 或 raw")
    musetalk["parsing_mode"] = parsing_mode

    wav2lip["pad_top"] = _bounded_int(wav2lip["pad_top"], "pad_top")
    wav2lip["pad_bottom"] = _bounded_int(wav2lip["pad_bottom"], "pad_bottom")
    wav2lip["pad_left"] = _bounded_int(wav2lip["pad_left"], "pad_left")
    wav2lip["pad_right"] = _bounded_int(wav2lip["pad_right"], "pad_right")

    return {
        "mouth_sharpen": _bounded_float(mouth_sharpen, "mouth_sharpen"),
        "paste_interpolation": interpolation,
        "musetalk": musetalk,
        "wav2lip": wav2lip,
    }


def apply_quality_to_model(model: Any, quality: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_quality(quality)
    model.mouth_sharpen = normalized["mouth_sharpen"]
    model.paste_interpolation = normalized["paste_interpolation"]
    musetalk = getattr(model, "musetalk", None)
    wav2lip = getattr(model, "wav2lip", None)
    _assign_fields(musetalk, normalized["musetalk"])
    _assign_fields(wav2lip, normalized["wav2lip"])
    return normalized


def resize_generated_mouth(
    frame: np.ndarray,
    size: tuple[int, int],
    interpolation: str = DEFAULT_PASTE_INTERPOLATION,
) -> np.ndarray:
    width, height = int(size[0]), int(size[1])
    image = np.asarray(frame)
    if image.size == 0 or width <= 0 or height <= 0:
        return image.astype(np.uint8, copy=False)
    flag = INTERPOLATION_FLAGS.get(
        str(interpolation).strip().lower(), cv2.INTER_LANCZOS4
    )
    return cv2.resize(image.astype(np.uint8), (width, height), interpolation=flag)


def sharpen_mouth(image: np.ndarray, amount: float) -> np.ndarray:
    value = float(amount or 0.0)
    if value <= 0 or image is None or image.size == 0:
        return image
    value = min(value, 2.0)
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=1.0)
    sharp = cv2.addWeighted(image, 1.0 + value, blurred, -value, 0)
    return np.clip(sharp, 0, 255).astype(np.uint8)


def enhance_generated_mouth(
    frame: np.ndarray,
    size: tuple[int, int],
    *,
    interpolation: str = DEFAULT_PASTE_INTERPOLATION,
    sharpen: float = DEFAULT_MOUTH_SHARPEN,
) -> np.ndarray:
    resized = resize_generated_mouth(frame, size, interpolation)
    return sharpen_mouth(resized, sharpen)


def enhance_from_config(
    frame: np.ndarray,
    size: tuple[int, int],
    config: Any,
) -> np.ndarray:
    quality = quality_from_model(getattr(config, "model", None))
    return enhance_generated_mouth(
        frame,
        size,
        interpolation=quality["paste_interpolation"],
        sharpen=quality["mouth_sharpen"],
    )


def _mapping_or_defaults(value: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    payload = dict(defaults)
    if value is None:
        return payload
    if is_dataclass(value) and not isinstance(value, type):
        incoming = asdict(value)
    elif isinstance(value, Mapping):
        incoming = dict(value)
    else:
        incoming = {
            key: getattr(value, key)
            for key in defaults
            if hasattr(value, key)
        }
    for key in defaults:
        if key in incoming and incoming[key] is not None:
            payload[key] = incoming[key]
    return payload


def _assign_fields(target: Any, values: Mapping[str, Any]) -> None:
    if target is None:
        return
    if isinstance(target, dict):
        target.update(values)
        return
    for key, value in values.items():
        if hasattr(target, key):
            setattr(target, key, value)


def _bounded_int(value: Any, name: str) -> int:
    lo, hi = _LIMITS[name]
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise QualityError(f"{name} 必須是整數") from exc
    if number < lo or number > hi:
        raise QualityError(f"{name} 必須介於 {lo} 與 {hi}")
    return number


def _bounded_float(value: Any, name: str) -> float:
    lo, hi = _LIMITS[name]
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise QualityError(f"{name} 必須是數字") from exc
    if number < lo or number > hi:
        raise QualityError(f"{name} 必須介於 {lo} 與 {hi}")
    return number
