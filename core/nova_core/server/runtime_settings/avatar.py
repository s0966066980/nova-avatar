# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定：數位人切換、嘴型畫質與輸出尺寸。"""
from __future__ import annotations

import gc
from copy import deepcopy
from typing import Any, Dict
from nova_contracts.avatar import AvatarService
from nova_contracts.common import ServiceError
from nova_core.utils.avatar_ids import is_safe_avatar_id
from nova_core.utils.logging import logger
from nova_core.server.runtime_settings import shared
from nova_core.server.runtime_settings.shared import SettingsError, _SWITCH_LOCK


def video_output_snapshot(config, *, avatars: AvatarService) -> Dict[str, Any]:
    """Describe the next connection's output using the source image dimensions."""
    max_height = int(getattr(getattr(config, "video", None), "max_height", 0))
    source_width = source_height = output_width = output_height = None
    source = avatars.source_size(getattr(config.model, "avatar_id", ""))
    if source is not None:
        source_width, source_height = source.width, source.height
        output = avatars.output_size(source.width, source.height, max_height)
        output_width, output_height = output.width, output.height
    return {
        "max_height": max_height,
        "height_options": [450, 540, 720, 960, 1280, 1920, 0],
        "source_width": source_width,
        "source_height": source_height,
        "output_width": output_width,
        "output_height": output_height,
    }


def apply_video_settings(config, params: Dict[str, Any], *, avatars: AvatarService) -> Dict[str, Any]:
    """Persist output size for new sessions; existing recorders keep their size."""
    if not isinstance(params, dict) or "max_height" not in params:
        raise SettingsError("請指定數字人輸出解析度 max_height")
    height = params["max_height"]
    if isinstance(height, bool) or not isinstance(height, int) or (height != 0 and not 2 <= height <= 2160):
        raise SettingsError("輸出高度必須為 0（原始尺寸），或 2–2160 的整數")
    previous = config.video.max_height
    config.video.max_height = height
    try:
        shared.persist_runtime_overrides(config)
    except Exception:
        config.video.max_height = previous
        raise
    return video_output_snapshot(config, avatars=avatars)


def apply_avatar(
    config, engine: str, avatar_id: str, *, session_count: int, avatars: AvatarService,
) -> Dict[str, Any]:
    engine = (engine or "").strip().lower()
    avatar_id = (avatar_id or "").strip()

    if not avatars.knows_engine(engine):
        raise SettingsError(f"不支援的數字人引擎: {engine}")
    if not is_safe_avatar_id(avatar_id):
        raise SettingsError("無效的角色 ID")

    characters = avatars.list_characters()
    engines = {item["id"]: item for item in avatars.list_engines(characters)}
    engine_info = engines[engine]
    if not engine_info["available"]:
        raise SettingsError(engine_info["message"] or f"{engine} 當前不可用")

    match = next((item for item in characters if item["id"] == avatar_id), None)
    if match is None:
        raise SettingsError(f"找不到角色: {avatar_id}")
    if match["type"] != engine:
        raise SettingsError(f"角色 {avatar_id} 屬於 {match['type']}，與所選引擎不一致")

    from nova_core.server.state import state as server_state

    already_selected = config.model.type == engine and config.model.avatar_id == avatar_id
    if already_selected and getattr(server_state, "model_ready", False):
        return {
            "type": engine,
            "avatar_id": avatar_id,
            "reloaded": False,
            "type_changed": False,
        }

    if session_count > 0:
        raise SettingsError(
            "請先斷開當前連線，再切換數字人",
            status=409,
            extra={"sessions": session_count, "need_disconnect": True},
        )

    if not _SWITCH_LOCK.acquire(blocking=False):
        raise SettingsError("正在切換數字人，請稍候", status=409)

    try:
        return _reload_avatar(config, engine, avatar_id, avatars=avatars)
    finally:
        _SWITCH_LOCK.release()


def apply_mouth_quality(config, params: Dict[str, Any], *, avatars: AvatarService) -> Dict[str, Any]:
    """Validate and persist mouth paste-back / character-build quality settings."""
    try:
        quality = avatars.apply_quality(config.model, params or {})
    except ServiceError as exc:
        raise SettingsError(str(exc)) from exc
    shared.persist_runtime_overrides(config)
    return quality


def _reload_avatar(config, engine: str, avatar_id: str, *, avatars: AvatarService) -> Dict[str, Any]:
    from copy import deepcopy

    from nova_core.server.state import state

    previous = f"{config.model.type}/{config.model.avatar_id}"
    pending = deepcopy(config)
    pending.model.type = engine
    pending.model.avatar_id = avatar_id
    type_changed = config.model.type != engine or state.model is None
    old_settings = deepcopy(config.model)
    scene_changed = False

    state.switching = True
    try:
        if type_changed:
            new_model, new_avatar = avatars.prepare_model(pending)
        else:
            new_model, new_avatar = state.model, avatars.load_assets(pending)

        avatars.select_background(getattr(pending.stage, "background_id", ""))
        scene_changed = True
        config.model.type = engine
        config.model.avatar_id = avatar_id
        shared.persist_runtime_overrides(config)

        old_model, old_avatar = state.model, state.avatar
        state.model, state.avatar = new_model, new_avatar
        state.model_ready = new_avatar is not None and new_model is not None

        if type_changed and old_model is not new_model:
            del old_model, old_avatar
            _release_gpu_resources(clear_state=False)

        logger.info(f"數字人已切換: {previous} -> {engine}/{avatar_id}")
        return {
            "type": engine,
            "avatar_id": avatar_id,
            "reloaded": True,
            "type_changed": type_changed,
        }
    except SettingsError:
        config.model = old_settings
        if scene_changed:
            avatars.select_background(getattr(config.stage, "background_id", ""))
        raise
    except Exception as exc:
        config.model = old_settings
        if scene_changed:
            avatars.select_background(getattr(config.stage, "background_id", ""))
        logger.exception("切換數字人失敗")
        raise SettingsError(f"切換數字人失敗: {exc}", status=500) from exc
    finally:
        state.switching = False


def _release_gpu_resources(*, clear_state: bool = True) -> None:
    from nova_core.server.state import state

    if clear_state:
        state.model = None
        state.avatar = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
