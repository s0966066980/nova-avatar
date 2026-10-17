# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Validate a role's explicit dataset and document retrieval scope."""
import re

_ID = re.compile(r"[a-fA-F0-9]{32}")


def ragflow_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("知識庫或文件識別碼不正確")
    return value


def validate_selection(value):
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
