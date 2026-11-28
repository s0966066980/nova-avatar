# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""設定 API：LLM 模型、回覆規則與助手設定。"""
from __future__ import annotations

import asyncio
import json
from nova_core.server.runtime_settings import (
    SettingsError,
    apply_llm_model,
    apply_llm_behavior,
    current_snapshot,
    fetch_llm_catalog,
    apply_reply_rules,
    reply_rules_snapshot,
)
from nova_core.server.deferred_settings import defer_when_connected
from nova_core.server.state import state
from nova_core.utils.logging import logger
from nova_core.server.routes.settings.shared import _json


async def get_llm_rules(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    return _json({"code": 0, "data": reply_rules_snapshot(state.config)})


async def set_llm_rules(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_reply_rules(
            state.config,
            params.get("rules"),
            params.get("expected_revision"),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("更新 LLM 回覆規則失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


async def list_llm_models(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    result = await fetch_llm_catalog(state.config, llm=state.llm)
    return _json({"code": 0, "data": result})


async def set_llm_behavior(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        result = apply_llm_behavior(state.config, params.get("assistant_profile"),
                                    params.get("rules"), params.get("expected_revision"),
                                    llm=state.llm)
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("儲存 Prompt 與規則失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)


@defer_when_connected("對話模型", lambda config: current_snapshot(config, tts=state.tts, avatars=state.avatar_service)["llm"])
async def set_llm_model(request):
    if not state.config:
        return _json({"code": -1, "msg": "服務尚未就緒"}, status=503)
    try:
        params = await request.json()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: apply_llm_model(
                state.config,
                params.get("model", ""),
                params.get("endpoint", ""),
                params.get("system_prompt"),
                params.get("response_max_chars"),
                params.get("reply_mode"),
                params.get("board_max_items"),
                params.get("assistant_profile"),
                params.get("semantic_wait_seconds"),
                llm=state.llm,
            ),
        )
        return _json({"code": 0, "msg": "ok", "data": result})
    except SettingsError as exc:
        return _json({"code": -1, "msg": exc.message, **exc.extra}, status=exc.status)
    except Exception as exc:
        logger.exception("切換 LLM 模型失敗")
        return _json({"code": -1, "msg": str(exc)}, status=500)
