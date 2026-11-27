# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Persist resource changes and apply them only after every peer disconnects."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from functools import wraps
import json
import os
from pathlib import Path
import tempfile

from aiohttp import web

from src.server.state import state
from src.utils.logging import logger

_handlers = {}
_stores = {}
# Changes saved by a console page that no longer exists; they are dropped.
_RETIRED = {"語音合成": "預設聲音改由主數位人設定檔決定"}


class PendingSettings:
    def __init__(self, path):
        self.path = path
        self.values = {}
        self.error = ""
        if path is not None and path.exists():
            try:
                values = json.loads(path.read_text())
                if not isinstance(values, dict) or any(not isinstance(v, dict) for v in values.values()):
                    raise ValueError("invalid pending settings")
                self.values = values
            except (OSError, ValueError):
                self.error = "待套用設定無法讀取，請重新儲存"

    def save(self, values):
        if self.path is None:
            self.values = values
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.pending-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(values, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            self.values = values
        finally:
            if os.path.exists(name):
                os.unlink(name)


def _store():
    config_path = getattr(state, 'config_path', None)
    path = Path(config_path).resolve().parent / 'pending_settings.json' if config_path else None
    if path not in _stores:
        _stores[path] = PendingSettings(path)
    return _stores[path]


def snapshot():
    pending = _store()
    return {'items': list(pending.values), 'error': pending.error}


class _SavedRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return deepcopy(self.payload)


def defer_when_connected(label, current_snapshot):
    """Resource endpoints publish pending state instead of disconnecting peers."""
    def decorate(handler):
        _handlers[label] = handler
        @wraps(handler)
        async def wrapped(request):
            if state.config is None:
                return await handler(request)
            try:
                payload = await request.json()
            except (ValueError, TypeError):
                return web.json_response({'code': -1, 'msg': '設定格式不正確'}, status=400)
            if not isinstance(payload, dict):
                return web.json_response({'code': -1, 'msg': '設定格式不正確'}, status=400)
            # Read the body before checking peers: the last peer may disconnect
            # while the HTTP body is still arriving.
            request = _SavedRequest(payload)
            pending = _store()
            if state.switching or state.settings_applying or getattr(getattr(state, "roles", None), "_apply_waiting", False):
                return web.json_response({'code': -1, 'msg': '設定正在套用，請稍後再試'}, status=409)
            if state.avatar_streams:
                try:
                    pending.save({**pending.values, label: deepcopy(payload)})
                except OSError:
                    return web.json_response({'code': -1, 'msg': '設定儲存失敗，請重試'}, status=503)
                pending.error = ''
                return web.json_response({'code': 0, 'pending': True,
                    'msg': '設定已儲存，待控制台與舞台皆斷線後套用',
                    'pending_settings': snapshot(),
                    # Snapshots may scan files (voices, models, avatars).
                    'data': await asyncio.to_thread(current_snapshot, state.config)}, status=202)
            state.settings_applying = True
            try:
                response = await handler(request)
                if response.status < 400:
                    try:
                        pending.save({key: value for key, value in pending.values.items() if key != label})
                    except OSError:
                        pending.error = '待套用紀錄儲存失敗，請重試'
                        return web.json_response({'code': -1, 'msg': pending.error,
                            'pending_settings': snapshot()}, status=503)
                    pending.error = ''
                return response
            finally:
                state.settings_applying = False
        return wrapped
    return decorate


async def apply_pending():
    if state.avatar_streams or state.switching or state.settings_applying or state.config is None:
        return
    pending = _store()
    state.settings_applying = True
    try:
        for label, payload in list(pending.values.items()):
            if label in _RETIRED:
                logger.warning('捨棄待套用的「%s」設定：%s', label, _RETIRED[label])
                pending.save({key: value for key, value in pending.values.items() if key != label})
                continue
            handler = _handlers.get(label)
            if handler is None:
                pending.error = '待套用設定版本不相容，請重新儲存'
                break
            try:
                response = await handler(_SavedRequest(payload))
                if response.status >= 400:
                    pending.error = f'{label}尚未套用，請檢查設定後重試'
                    break
                pending.save({key: value for key, value in pending.values.items() if key != label})
                pending.error = ''
            except Exception:
                pending.error = f'{label}尚未套用，請檢查設定後重試'
                logger.exception('Deferred resource update failed')
                break
    finally:
        state.settings_applying = False
