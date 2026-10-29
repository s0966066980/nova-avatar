# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""健康檢查路由"""
import json
from aiohttp import web

from src.server.state import state


def _llm_full_gpu() -> dict:
    """One boolean for the console warning; layer counts and VRAM holders stay in the log."""
    llm = getattr(state.config, "llm", None) if state.config else None
    if getattr(llm, "provider", "") != "llamacpp":
        return {}
    from src.llm.llamacpp import gpu_offload_status

    offload = gpu_offload_status()
    return {} if offload is None else {"llm_full_gpu": bool(offload.get("full"))}


async def health_check(request):
    """健康檢查介面，用於前端判斷後端是否完全啟動"""
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {
                "code": 0,
                "ready": state.server_ready,
                "model_ready": bool(getattr(state, "model_ready", False)),
                **({"prewarm": state.prewarm_status} if getattr(state, "prewarm_status", None) else {}),
                **_llm_full_gpu(),
                "avatar": {
                    "type": getattr(getattr(state.config, "model", None), "type", None) if state.config else None,
                    "avatar_id": getattr(getattr(state.config, "model", None), "avatar_id", None) if state.config else None,
                },
                "vad": {
                    "enabled": bool(getattr(getattr(state.config, "vad", None), "enabled", False)) if state.config else False,
                    "type": getattr(getattr(state.config, "vad", None), "type", None) if state.config else None,
                },
            }
        ),
    )
