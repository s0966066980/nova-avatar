"""LLM 服務模組"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable, Optional

from src.avatars.base import BaseAvatar
from src.llm.engines import OpenAILLM
from src.llm.router import ReplyMode
from src.utils.logging import logger

_session_llm_instances = {}


def llm_response(
    message: str,
    avatar_stream: BaseAvatar,
    api_key: str = os.getenv("DASHSCOPE_API_KEY"),
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    model: str = "qwen-plus",
    *,
    stream_to_avatar: bool = True,
    datainfo: Optional[dict] = None,
    chunk_guard: Optional[Callable[[int], bool]] = None,
    defer_history_commit: bool = False,
    reply_mode: Optional[ReplyMode | str] = None,
) -> str:
    """呼叫 LLM 並將響應流式推送到 avatar"""
    try:
        from src.server.state import state as server_state

        config = getattr(avatar_stream, 'config', None) or server_state.config
        _ensure_llamacpp_if_needed(config)
        if config is not None and getattr(config, "llm", None) is not None:
            base_url = config.llm.base_url or base_url
            model = config.llm.model or model
            api_key = config.llm.api_key or api_key
        sessionid = getattr(avatar_stream, 'sessionid', 0)
        
        # 為每個 session 維護獨立的 LLM 例項(保留對話歷史)
        if sessionid not in _session_llm_instances:
            logger.info(f"Creating new LLM instance for session {sessionid}")
            _session_llm_instances[sessionid] = OpenAILLM(
                config=config,
                parent=avatar_stream,
                api_key=api_key,
                base_url=base_url,
                model=model,
                max_history=10  # 保留最近10輪對話
            )
        
        llm = _session_llm_instances[sessionid]
        llm.base_url = base_url
        llm.model = model
        if api_key:
            llm.api_key = api_key

        generation_datainfo = dict(datainfo or {})
        rules_snapshot = getattr(avatar_stream, "_reply_rules_snapshot", None)
        if rules_snapshot is not None:
            generation_datainfo["rules_snapshot"] = rules_snapshot
        mode_callback = getattr(avatar_stream, "_reply_mode_callback", None)
        if callable(mode_callback):
            generation_datainfo["on_mode"] = mode_callback
        if getattr(avatar_stream, "_incremental_board", False):
            generation_datainfo["incremental_board"] = True
        return llm.generate_response(
            message,
            avatar_stream,
            stream_to_avatar=stream_to_avatar,
            datainfo=generation_datainfo,
            chunk_guard=chunk_guard,
            defer_history_commit=defer_history_commit,
            reply_mode=reply_mode,
        )
        
    except Exception as e:
        logger.error("LLM service failed: %s", type(e).__name__)
        raise


def _ensure_llamacpp_if_needed(config) -> None:
    if config is None or getattr(config, "llm", None) is None:
        return
    if getattr(config.llm, "provider", "") != "llamacpp":
        return
    from src.llm.llamacpp import ensure_server, server_status

    host = getattr(config.llm, "llamacpp_host", "127.0.0.1") or "127.0.0.1"
    port = int(getattr(config.llm, "llamacpp_port", 8080) or 8080)
    if server_status(host, port)["running"]:
        return
    logger.warning("llama-server 未在執行，正在自動啟動...")
    base_url = ensure_server(
        config.llm.model,
        extra_dir=getattr(config.llm, "llamacpp_dir", "") or "",
        host=host,
        port=port,
        ctx=int(getattr(config.llm, "llamacpp_ctx", 8192) or 8192),
        threads=int(getattr(config.llm, "llamacpp_threads", 0) or 0),
    )
    config.llm.base_url = base_url


def clear_session_history(sessionid: int):
    """清空指定會話的對話歷史與看板快照"""
    if sessionid in _session_llm_instances:
        llm = _session_llm_instances[sessionid]
        llm.clear_history()
        set_board = getattr(llm, "set_last_board", None)
        if callable(set_board):
            set_board(None)
        logger.info(f"Cleared history and board for session {sessionid}")


def get_session_board(sessionid: int):
    """取得指定會話最近一次成功生成的看板上下文"""
    if sessionid in _session_llm_instances:
        llm = _session_llm_instances[sessionid]
        get_board = getattr(llm, "get_last_board", None)
        if callable(get_board):
            return get_board()
    return None


def acknowledge_session_board_item(
    sessionid: int,
    *,
    turn_id: str,
    board_id: str,
    item_index: int,
    presenter: str,
) -> bool:
    """Commit one board item only after its assigned presenter rendered it."""
    llm = _session_llm_instances.get(sessionid)
    acknowledge = getattr(llm, "acknowledge_board_display", None)
    if not callable(acknowledge):
        return False
    return bool(
        acknowledge(
            turn_id=turn_id,
            board_id=board_id,
            item_index=item_index,
        )
    )


def commit_session_history(
    sessionid: int,
    turn_id: str,
    *,
    assistant_text: str,
    terminal_reason: str,
) -> bool:
    """Commit exactly what crossed the playback boundary for one voice turn."""
    llm = _session_llm_instances.get(sessionid)
    commit = getattr(llm, "commit_pending_history_turn", None)
    if not callable(commit):
        return False
    return bool(
        commit(
            turn_id,
            assistant_text=assistant_text,
            terminal_reason=terminal_reason,
        )
    )


def remove_session(sessionid: int):
    """刪除指定會話的 LLM 例項"""
    if sessionid in _session_llm_instances:
        del _session_llm_instances[sessionid]
        logger.info(f"Removed LLM instance for session {sessionid}")


def switch_llm_model(model: str):
    """更新已有會話的 LLM 模型名，保留對話歷史。"""
    switch_llm_endpoint(model=model)


def switch_llm_endpoint(
    model: str,
    base_url: str = None,
    extra_body=None,
    api_key: str = None,
    max_tokens: int = None,
    response_max_chars: int = None,
    system_prompt: str = None,
    reset_history: bool = False,
):
    """更新已有會話的模型與介面，base_url 變化時重建客戶端。"""
    for sessionid, llm in _session_llm_instances.items():
        llm.model = model
        if base_url:
            llm.base_url = base_url
            llm._client = None
        if extra_body is not None:
            llm.extra_body = dict(extra_body)
        if api_key:
            llm.api_key = api_key
            llm._client = None
        if max_tokens is not None:
            llm.max_tokens = int(max_tokens)
        if response_max_chars is not None:
            llm.response_max_chars = int(response_max_chars)
        if system_prompt is not None:
            llm.system_prompt = system_prompt
        if reset_history:
            llm.clear_history()
            set_board = getattr(llm, "set_last_board", None)
            if callable(set_board):
                set_board(None)
        logger.info(
            f"Updated LLM for session {sessionid}: model={llm.model}, base_url={llm.base_url}"
        )


__all__ = [
    "llm_response",
    "clear_session_history",
    "get_session_board",
    "acknowledge_session_board_item",
    "commit_session_history",
    "remove_session",
    "switch_llm_model",
    "switch_llm_endpoint",
]
