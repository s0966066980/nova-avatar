# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What each avatar or role may draw on: knowledge bases and public web domains.

These choices are profile data the core keeps (ADR 0027); the LLM layer only
receives the chosen dataset ids and allowed domains with each request.
Non-secret RAGFlow choices are stored independently for each avatar.
"""
from __future__ import annotations

import os
import re
import tempfile
from threading import RLock
from typing import Any

import yaml

from src.utils.avatar_ids import is_safe_avatar_id
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


def ragflow_id(value):
    if not isinstance(value, str) or not _DATASET_ID.fullmatch(value):
        raise ValueError("知識庫或文件識別碼不正確")
    return value


def validate_selection(value):
    """A role's explicit dataset and document retrieval scope."""
    if not isinstance(value, dict) or set(value) - {
        "enabled", "dataset_ids", "document_scope", "document_ids"
    }:
        raise ValueError("知識範圍含未知欄位或格式不正確")
    enabled = value.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("檢索啟用狀態必須是布林值")
    datasets = value.get("dataset_ids")
    documents = value.get("document_ids", [])
    for ids, limit in ((datasets, 8), (documents, 200)):
        if not isinstance(ids, list) or len(ids) > limit:
            raise ValueError("知識庫最多 8 個、指定文件最多 200 份")
        for item in ids:
            ragflow_id(item)
        if len(set(ids)) != len(ids):
            raise ValueError("知識庫或文件不可重複選擇")
    scope = value.get("document_scope", "selected" if documents else "all")
    if not isinstance(scope, str) or scope not in {"all", "selected"}:
        raise ValueError("請選擇全部文件或指定文件")
    if enabled and not datasets:
        raise ValueError("啟用檢索前請選擇知識庫")
    if enabled and scope == "selected" and not documents:
        raise ValueError("指定文件模式至少需選擇一份文本")
    if documents and not datasets:
        raise ValueError("指定文件前請選擇所屬知識庫")
    return {"enabled": enabled, "dataset_ids": list(datasets),
            "document_scope": scope, "document_ids": list(documents) if scope == "selected" else []}


def web_access(value=None):
    """A role's public web access policy, independent of composition tools."""
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'enabled', 'allowed_domains'}:
        raise ValueError('網頁搜尋設定不正確')
    enabled = value.get('enabled', False)
    domains = value.get('allowed_domains', [])
    if not isinstance(enabled, bool) or not isinstance(domains, list) or len(domains) > 30:
        raise ValueError('網頁搜尋開關或網域清單不正確')
    normalized = []
    for domain in domains:
        if not isinstance(domain, str):
            raise ValueError('請填寫網域名稱，不含網址或路徑')
        domain = domain.strip().lower()
        if len(domain) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
            raise ValueError('請填寫公開網域名稱，例如 gov.tw，不含網址或路徑')
        if domain not in normalized:
            normalized.append(domain)
    return {'enabled': enabled, 'allowed_domains': normalized}
