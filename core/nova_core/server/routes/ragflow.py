# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console API for the optional RAGFlow retrieval service."""
from __future__ import annotations

import json

from aiohttp import web

from nova_contracts.common import ServiceError
from nova_contracts.llm import DocumentsQuery, RetrievalRequest
from nova_core.utils.avatar_ids import is_safe_avatar_id
from nova_core.profiles.knowledge_scope import avatar_settings, ragflow_id, save_avatar_settings, validate_selection
from nova_core.server.state import state


def _json(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(data, ensure_ascii=False),
    )


def _avatar_id(value: object) -> str:
    avatar_id = value.strip() if isinstance(value, str) else ""
    if not is_safe_avatar_id(avatar_id) or len(avatar_id) > 128:
        raise ValueError("數位人識別碼不正確")
    return avatar_id


async def get_ragflow_settings(request):
    try:
        avatar_id = _avatar_id(request.query.get("avatar_id"))
    except ValueError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)
    status = state.llm.ragflow_status()
    return _json({"code": 0, "data": {
        "avatar_id": avatar_id,
        **avatar_settings(avatar_id),
        "configured": status.configured,
        "management_url": status.management_url,
    }})


async def put_ragflow_settings(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("設定內容必須是物件")
        avatar_id = _avatar_id(payload.get("avatar_id"))
        settings = save_avatar_settings(
            avatar_id,
            enabled=payload.get("enabled"),
            dataset_ids=payload.get("dataset_ids"),
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)
    return _json({"code": 0, "data": {"avatar_id": avatar_id, **settings}})


async def list_ragflow_datasets(request):
    try:
        datasets = list((await state.llm.list_ragflow_datasets()).datasets)
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc), "data": {"status": "unavailable"}}, status=503)
    return _json({"code": 0, "data": {"status": "ready", "datasets": datasets}})


async def ragflow_status(request):
    return _json({"code": 0, "data": state.llm.ragflow_status().model_dump()})


async def list_ragflow_documents(request):
    try:
        dataset_id = ragflow_id(request.match_info["dataset_id"])
        page = int(request.query.get("page", "1"))
        if not 1 <= page <= 10000:
            raise ValueError("文件頁碼不正確")
    except (ValueError, TypeError) as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)
    try:
        result = (await state.llm.list_ragflow_documents(
            DocumentsQuery(dataset_id=dataset_id, page=page))).page
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc)}, status=503)
    return _json({"code": 0, "data": result})


async def test_ragflow_retrieval(request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("測試內容必須是物件")
        question = str(payload.get("question") or "").strip()
        if not question or len(question) > 2000:
            raise ValueError("測試問題須為 1 至 2000 字")
        if "profile_id" in payload:
            _avatar_id(payload["profile_id"])
            if "selection" in payload:
                selection = validate_selection(payload["selection"])
            else:
                roles = getattr(state, "roles", None)
                if roles is None:
                    raise ValueError("角色設定服務尚未初始化")
                profile = next((p for p in roles.store.load()["profiles"]
                                if p["id"] == payload["profile_id"]), None)
                if profile is None:
                    raise ValueError("找不到數位人設定檔")
                selection = validate_selection(profile["rag"])
        else:
            avatar_id = _avatar_id(payload.get("avatar_id"))
            selection = avatar_settings(avatar_id)
        if not selection["dataset_ids"]:
            raise ValueError("請先儲存知識庫選擇")
        if selection.get("document_scope") == "selected" and not selection.get("document_ids"):
            raise ValueError("指定文件模式至少需選擇一份文本")
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"code": -1, "msg": str(exc)}, status=400)
    try:
        result = await state.llm.retrieve(RetrievalRequest(
            question=question, dataset_ids=tuple(selection["dataset_ids"]),
            document_ids=(tuple(selection["document_ids"])
                          if selection.get("document_scope") == "selected" else ()),
        ))
    except ServiceError as exc:
        return _json({"code": -1, "msg": str(exc), "data": {"status": "unavailable"}}, status=503)
    return _json({"code": 0, "data": result.model_dump(mode="json")})
