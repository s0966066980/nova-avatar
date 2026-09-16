# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Non-secret RAGFlow choices, stored independently for each avatar."""
from __future__ import annotations

import os
import re
import tempfile
from threading import RLock
from typing import Any

import yaml

from src.avatars.catalog import is_safe_avatar_id
from src.utils.logging import logger
from src.utils.paths import get_config_dir

SETTINGS_FILE = get_config_dir() / "ragflow_settings.yaml"
_LOCK = RLock()
_DATASET_ID = re.compile(r"[a-fA-F0-9]{32}")
MAX_DATASETS = 8


def _load() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {"avatars": {}}
    try:
        payload = yaml.safe_load(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
        avatars = payload.get("avatars", {}) if isinstance(payload, dict) else {}
        return {"avatars": avatars if isinstance(avatars, dict) else {}}
    except Exception as exc:
        logger.warning(f"讀取 RAGFlow 設定失敗: {type(exc).__name__}")
        return {"avatars": {}}


def avatar_settings(avatar_id: str) -> dict[str, Any]:
    """Return an immutable-by-convention snapshot for one conversation turn."""
    if not is_safe_avatar_id(avatar_id):
        return {"enabled": False, "dataset_ids": []}
    with _LOCK:
        data = _load()["avatars"].get(avatar_id, {})
    if not isinstance(data, dict):
        data = {}
    ids = data.get("dataset_ids", [])
    if not isinstance(ids, list):
        ids = []
    return {
        "enabled": data.get("enabled") is True,
        "dataset_ids": [
            item for item in ids[:MAX_DATASETS]
            if isinstance(item, str) and _DATASET_ID.fullmatch(item)
        ],
    }


def save_avatar_settings(avatar_id: str, *, enabled: Any, dataset_ids: Any) -> dict[str, Any]:
    if not is_safe_avatar_id(avatar_id) or len(avatar_id) > 128:
        raise ValueError("數位人識別碼不正確")
    if not isinstance(enabled, bool):
        raise ValueError("啟用狀態必須是布林值")
    if not isinstance(dataset_ids, list) or len(dataset_ids) > MAX_DATASETS:
        raise ValueError(f"最多只能選擇 {MAX_DATASETS} 個知識庫")
    if any(not isinstance(item, str) or not _DATASET_ID.fullmatch(item) for item in dataset_ids):
        raise ValueError("知識庫識別碼不正確")
    if len(set(dataset_ids)) != len(dataset_ids):
        raise ValueError("知識庫不可重複選擇")
    if enabled and not dataset_ids:
        raise ValueError("啟用檢索前請先選擇知識庫")

    with _LOCK:
        payload = _load()
        payload["avatars"][avatar_id] = {
            "enabled": enabled,
            "dataset_ids": list(dataset_ids),
        }
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=SETTINGS_FILE.parent,
                prefix=f".{SETTINGS_FILE.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = handle.name
                handle.write("# RAGFlow per-avatar choices; API credentials remain in the server environment.\n")
                yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, SETTINGS_FILE)
        except Exception:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
            raise
    return {"enabled": enabled, "dataset_ids": list(dataset_ids)}
