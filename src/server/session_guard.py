# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Shared client_id verification for session-scoped HTTP routes."""
from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, NoReturn

from aiohttp import web

from src.server.state import state


def _mapping_str(mapping: Any, key: str) -> str:
    if isinstance(mapping, Mapping):
        value = mapping.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def extract_client_id(request: Any, payload: Any = None) -> str:
    """Read client_id from X-Client-Id header, query string, or JSON body."""
    header = _mapping_str(getattr(request, "headers", None), "X-Client-Id")
    if header:
        return header[:128]
    query = _mapping_str(getattr(request, "query", None), "client_id")
    if query:
        return query[:128]
    body = _mapping_str(payload, "client_id")
    return body[:128] if body else ""


def extract_client_role(request: Any, payload: Any = None) -> str:
    """Read client_role from X-Client-Role header, query string, or JSON body."""
    for source, key in (
        (getattr(request, "headers", None), "X-Client-Role"),
        (getattr(request, "query", None), "client_role"),
        (payload, "client_role"),
    ):
        value = _mapping_str(source, key).lower()
        if value:
            return value
    return ""


def authorize_session_request(
    request: Any,
    sessionid: int,
    *,
    payload: Any = None,
    allow_console_stage_control: bool = False,
) -> bool:
    """Verify caller ownership of a session, preserving explicit console->stage control."""
    owner_client_id = state.session_clients.get(sessionid) or ""
    provided_client_id = extract_client_id(request, payload)
    caller_role = extract_client_role(request, payload)
    session_role = (
        state.session_roles.get(sessionid)
        or getattr(state.voice_sessions.get(sessionid), "_presenter", None)
        or ""
    )

    if allow_console_stage_control and session_role == "stage" and caller_role == "console":
        if not provided_client_id or provided_client_id == owner_client_id:
            return True
        console_clients = {
            cid
            for sid, role in state.session_roles.items()
            if role == "console" and (cid := state.session_clients.get(sid))
        }
        return not console_clients or provided_client_id in console_clients

    if provided_client_id:
        return bool(owner_client_id) and provided_client_id == owner_client_id
    if owner_client_id:
        return False
    return True


def session_forbidden_response() -> web.Response:
    """Return a consistent 403 JSON response when client_id verification fails."""
    return web.json_response({"code": -1, "msg": "無效的連線識別"}, status=403)


def raise_session_forbidden() -> NoReturn:
    """Raise HTTP 403 JSON error for synchronous route guards."""
    raise web.HTTPForbidden(
        content_type="application/json",
        text=json.dumps({"code": -1, "msg": "無效的連線識別"}),
    )
