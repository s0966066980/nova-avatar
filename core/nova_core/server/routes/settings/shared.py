# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Helpers shared by the settings routes."""
from __future__ import annotations

import json
from aiohttp import web
from nova_core.server.state import state


def _json(payload: dict, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(payload, ensure_ascii=False),
    )


def _active_session_count() -> int:
    return sum(1 for stream in state.avatar_streams.values() if stream is not None)
