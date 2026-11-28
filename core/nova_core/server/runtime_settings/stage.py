# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定：舞台（字幕、看板、麥克風、訪客重置時間）與舞台背景。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Dict
from nova_core.greetings.content import validate_interval, validate_content
from nova_contracts.avatar import AvatarService
from nova_contracts.common import ServiceError
from nova_core.server.runtime_settings import shared
from nova_core.server.runtime_settings.shared import SettingsError


DEFAULT_STAGE_CAPTION_MAX_CHARS = 120


MIN_STAGE_CAPTION_MAX_CHARS = 20


MAX_STAGE_CAPTION_MAX_CHARS = 2000


DEFAULT_STAGE_IDLE_RESET_SECONDS = 60


MIN_STAGE_IDLE_RESET_SECONDS = 3


MAX_STAGE_IDLE_RESET_SECONDS = 300


DEFAULT_CAPTION_X = 50


DEFAULT_CAPTION_Y = 90


DEFAULT_CAPTION_WIDTH = 100


MIN_CAPTION_WIDTH = 40


BOARD_STYLES = ("glass", "slate", "cue")


BOARD_PRESETS = ("tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br", "custom")


DEFAULT_BOARD_STYLE = "glass"


DEFAULT_BOARD_WIDTH = 252


DEFAULT_BOARD_HEIGHT = 300


DEFAULT_BOARD_TRANSPARENCY = 28


DEFAULT_BOARD_X = 100


DEFAULT_BOARD_Y = 0


DEFAULT_BOARD_PRESET = "tr"


DEFAULT_BOARD_OPEN_X = 50


DEFAULT_BOARD_OPEN_Y = 8


DEFAULT_MIC_X = 50


DEFAULT_MIC_Y = 62


DEFAULT_MIC_PRESET = "custom"


MIN_BOARD_WIDTH = 200


MAX_BOARD_WIDTH = 720


MIN_BOARD_HEIGHT = 180


MAX_BOARD_HEIGHT = 720


def validate_stage_caption_max_chars(value) -> int:
    """驗證舞台字幕顯示上限。"""
    if isinstance(value, bool):
        raise ValueError("舞台字幕顯示上限必須是整數")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("舞台字幕顯示上限必須是整數") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("舞台字幕顯示上限必須是整數")
    if not MIN_STAGE_CAPTION_MAX_CHARS <= normalized <= MAX_STAGE_CAPTION_MAX_CHARS:
        raise ValueError(
            f"舞台字幕顯示上限必須介於 {MIN_STAGE_CAPTION_MAX_CHARS} 到 "
            f"{MAX_STAGE_CAPTION_MAX_CHARS} 之間"
        )
    return normalized


def _validate_int_range(value, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}必須是整數")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}必須是整數") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field}必須是整數")
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{field}必須介於 {minimum} 到 {maximum} 之間")
    return normalized


def validate_board_style(value) -> str:
    style = str(value or "").strip()
    if style not in BOARD_STYLES:
        raise ValueError("看板視窗樣式必須是 glass、slate 或 cue")
    return style


def validate_board_preset(value) -> str:
    preset = str(value or "").strip()
    if preset not in BOARD_PRESETS:
        raise ValueError("看板位置必須是九宮格預設或 custom")
    return preset


def stage_snapshot(config) -> Dict[str, Any]:
    from nova_core.config.stage_composer import snapshot as composer_snapshot
    stage = getattr(config, "stage", None)
    caption = getattr(stage, "caption_max_chars", DEFAULT_STAGE_CAPTION_MAX_CHARS)
    return {
        **composer_snapshot(stage),
        "clear_display_seconds": int(getattr(stage, "clear_display_seconds", 15)),
        "full_reset_seconds": 120,
        "background_id": str(getattr(stage, "background_id", "") or ""),
        "caption_max_chars": validate_stage_caption_max_chars(caption),
        "idle_greeting_enabled": bool(getattr(stage, "idle_greeting_enabled", False)),
        "idle_greeting_seconds": validate_interval(getattr(stage, "idle_greeting_seconds", 30)),
        "idle_reset_seconds": _validate_int_range(
            getattr(stage, "idle_reset_seconds", DEFAULT_STAGE_IDLE_RESET_SECONDS),
            field="舞台閒置清場時間",
            minimum=MIN_STAGE_IDLE_RESET_SECONDS,
            maximum=MAX_STAGE_IDLE_RESET_SECONDS,
        ),
        "caption_x": _validate_int_range(
            getattr(stage, "caption_x", DEFAULT_CAPTION_X),
            field="字幕帶左右位置",
            minimum=0,
            maximum=100,
        ),
        "caption_y": _validate_int_range(
            getattr(stage, "caption_y", DEFAULT_CAPTION_Y),
            field="字幕帶上下位置",
            minimum=0,
            maximum=100,
        ),
        "caption_width": _validate_int_range(
            getattr(stage, "caption_width", DEFAULT_CAPTION_WIDTH),
            field="字幕帶寬度",
            minimum=MIN_CAPTION_WIDTH,
            maximum=100,
        ),
        "board_style": validate_board_style(
            getattr(stage, "board_style", DEFAULT_BOARD_STYLE)
        ),
        "board_width": _validate_int_range(
            getattr(stage, "board_width", DEFAULT_BOARD_WIDTH),
            field="看板寬度",
            minimum=MIN_BOARD_WIDTH,
            maximum=MAX_BOARD_WIDTH,
        ),
        "board_height": _validate_int_range(
            getattr(stage, "board_height", DEFAULT_BOARD_HEIGHT),
            field="看板高度",
            minimum=MIN_BOARD_HEIGHT,
            maximum=MAX_BOARD_HEIGHT,
        ),
        "board_transparency": _validate_int_range(
            getattr(stage, "board_transparency", DEFAULT_BOARD_TRANSPARENCY),
            field="看板背景透明度",
            minimum=0,
            maximum=100,
        ),
        "board_x": _validate_int_range(
            getattr(stage, "board_x", DEFAULT_BOARD_X),
            field="看板左右位置",
            minimum=0,
            maximum=100,
        ),
        "board_y": _validate_int_range(
            getattr(stage, "board_y", DEFAULT_BOARD_Y),
            field="看板上下位置",
            minimum=0,
            maximum=100,
        ),
        "board_preset": validate_board_preset(
            getattr(stage, "board_preset", DEFAULT_BOARD_PRESET)
        ),
        "board_preview": bool(getattr(stage, "board_preview", False)),
        "board_open_x": _validate_int_range(
            getattr(stage, "board_open_x", DEFAULT_BOARD_OPEN_X),
            field="展開看板按鈕左右位置",
            minimum=0,
            maximum=100,
        ),
        "board_open_y": _validate_int_range(
            getattr(stage, "board_open_y", DEFAULT_BOARD_OPEN_Y),
            field="展開看板按鈕上下位置",
            minimum=0,
            maximum=100,
        ),
        "mic_x": _validate_int_range(
            getattr(stage, "mic_x", DEFAULT_MIC_X),
            field="麥克風左右位置",
            minimum=0,
            maximum=100,
        ),
        "mic_y": _validate_int_range(
            getattr(stage, "mic_y", DEFAULT_MIC_Y),
            field="麥克風上下位置",
            minimum=0,
            maximum=100,
        ),
        "mic_preset": validate_board_preset(
            getattr(stage, "mic_preset", DEFAULT_MIC_PRESET)
        ),
    }


def apply_stage_settings(config, params: Dict[str, Any], *, greeting_content=None) -> Dict[str, Any]:
    """更新並持久化數字人舞台顯示設定。"""
    from nova_core.config.stage_composer import validate as validate_composer
    stage = getattr(config, "stage", None)
    if stage is None:
        raise SettingsError("當前配置不支援舞台設定，請更新 config.yaml", status=400)
    params = dict(params)
    enabled = params.get("idle_greeting_enabled", config.stage.idle_greeting_enabled)
    if type(enabled) is not bool:
        raise SettingsError("招呼開關須為布林值")
    try:
        interval = validate_interval(params.get("idle_greeting_seconds", config.stage.idle_greeting_seconds))
        if enabled:
            validate_content(greeting_content if greeting_content is not None else asdict(config.greeting), required=True)
    except ValueError as exc:
        raise SettingsError(str(exc)) from exc
    original_stage = config.stage
    stage = deepcopy(original_stage)
    payload = params or {}
    try:
        composer_values = validate_composer(payload, stage)
        if "clear_display_seconds" in payload:
            stage.clear_display_seconds = _validate_int_range(payload['clear_display_seconds'],
                field='舞台畫面清除時間', minimum=1, maximum=3600)
        if "caption_max_chars" in payload:
            stage.caption_max_chars = validate_stage_caption_max_chars(
                payload["caption_max_chars"]
            )
        if "idle_reset_seconds" in payload:
            stage.idle_reset_seconds = _validate_int_range(
                payload["idle_reset_seconds"],
                field="舞台閒置清場時間",
                minimum=MIN_STAGE_IDLE_RESET_SECONDS,
                maximum=MAX_STAGE_IDLE_RESET_SECONDS,
            )
        if "caption_x" in payload:
            stage.caption_x = _validate_int_range(
                payload["caption_x"],
                field="字幕帶左右位置",
                minimum=0,
                maximum=100,
            )
        if "caption_y" in payload:
            stage.caption_y = _validate_int_range(
                payload["caption_y"],
                field="字幕帶上下位置",
                minimum=0,
                maximum=100,
            )
        if "caption_width" in payload:
            stage.caption_width = _validate_int_range(
                payload["caption_width"],
                field="字幕帶寬度",
                minimum=MIN_CAPTION_WIDTH,
                maximum=100,
            )
        if "board_style" in payload:
            stage.board_style = validate_board_style(payload["board_style"])
        if "board_width" in payload:
            stage.board_width = _validate_int_range(
                payload["board_width"],
                field="看板寬度",
                minimum=MIN_BOARD_WIDTH,
                maximum=MAX_BOARD_WIDTH,
            )
        if "board_height" in payload:
            stage.board_height = _validate_int_range(
                payload["board_height"],
                field="看板高度",
                minimum=MIN_BOARD_HEIGHT,
                maximum=MAX_BOARD_HEIGHT,
            )
        if "board_transparency" in payload:
            stage.board_transparency = _validate_int_range(
                payload["board_transparency"],
                field="看板背景透明度",
                minimum=0,
                maximum=100,
            )
        if "board_x" in payload:
            stage.board_x = _validate_int_range(
                payload["board_x"],
                field="看板左右位置",
                minimum=0,
                maximum=100,
            )
        if "board_y" in payload:
            stage.board_y = _validate_int_range(
                payload["board_y"],
                field="看板上下位置",
                minimum=0,
                maximum=100,
            )
        if "board_preset" in payload:
            stage.board_preset = validate_board_preset(payload["board_preset"])
        if "board_preview" in payload:
            stage.board_preview = bool(payload["board_preview"])
        if "board_open_x" in payload:
            stage.board_open_x = _validate_int_range(
                payload["board_open_x"],
                field="展開看板按鈕左右位置",
                minimum=0,
                maximum=100,
            )
        if "board_open_y" in payload:
            stage.board_open_y = _validate_int_range(
                payload["board_open_y"],
                field="展開看板按鈕上下位置",
                minimum=0,
                maximum=100,
            )
        if "mic_x" in payload:
            stage.mic_x = _validate_int_range(
                payload["mic_x"],
                field="麥克風左右位置",
                minimum=0,
                maximum=100,
            )
        if "mic_y" in payload:
            stage.mic_y = _validate_int_range(
                payload["mic_y"],
                field="麥克風上下位置",
                minimum=0,
                maximum=100,
            )
        if "mic_preset" in payload:
            stage.mic_preset = validate_board_preset(payload["mic_preset"])
    except ValueError as exc:
        raise SettingsError(str(exc)) from exc
    for key, value in composer_values.items():
        setattr(stage, key, value)
    stage.idle_greeting_enabled = enabled
    stage.idle_greeting_seconds = interval
    config.stage = stage
    try:
        shared.persist_runtime_overrides(config)
    except Exception:
        config.stage = original_stage
        raise
    return stage_snapshot(config)


def apply_stage_background(config, background_id: str, *, avatars: AvatarService) -> Dict[str, Any]:
    """Switch the shared scene without rebuilding an avatar or WebRTC session."""
    stage = getattr(config, "stage", None)
    if stage is None:
        raise SettingsError("當前配置不支援舞台背景", status=400)
    selected = str(background_id or "").strip()
    previous = str(getattr(stage, "background_id", "") or "")
    try:
        result = avatars.select_background(selected)
    except ServiceError as exc:
        raise SettingsError(str(exc), status=400) from exc
    stage.background_id = selected
    try:
        shared.persist_runtime_overrides(config)
    except Exception:
        stage.background_id = previous
        avatars.select_background(previous)
        raise
    return result
