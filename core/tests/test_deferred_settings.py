# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.config.schema import Config
from src.server import deferred_settings
from src.server.routes import settings
from src.server.state import state


@pytest.fixture
def pending(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'config', Config())
    monkeypatch.setattr(state, 'config_path', str(tmp_path / 'config.yaml'))
    monkeypatch.setattr(state, 'avatar_streams', {1: object(), 2: object()})
    monkeypatch.setattr(state, 'switching', False)
    monkeypatch.setattr(state, 'settings_applying', False)
    monkeypatch.setattr(deferred_settings, '_stores', {})
    apply = Mock(return_value={})
    monkeypatch.setattr(settings, 'apply_stt_settings', apply)
    return apply


def test_saved_resource_settings_wait_for_both_peers_and_survive_restart(pending, monkeypatch):
    async def run():
        request = SimpleNamespace(json=AsyncMock(return_value={'type': 'whisper', 'model_size': 'small'}))
        response = await settings.set_stt_settings(request)
        assert response.status == 202
        assert json.loads(response.text)['pending']
        pending.assert_not_called()
        # Reload the persisted queue as a restarted backend would.
        monkeypatch.setattr(deferred_settings, '_stores', {})
        assert deferred_settings.snapshot()['items'] == ['語音辨識']
        state.avatar_streams.pop(1)
        await deferred_settings.apply_pending()
        pending.assert_not_called()
        state.avatar_streams.pop(2)
        await deferred_settings.apply_pending()
        pending.assert_called_once()
        assert pending.call_args.kwargs['session_count'] == 0
        assert pending.call_args.args[1]['model_size'] == 'small'
        assert not deferred_settings.snapshot()['items']
        assert not state.switching
        assert not state.settings_applying
    asyncio.run(run())


def test_resource_update_failure_preserves_pending_settings(pending):
    async def run():
        await settings.set_stt_settings(SimpleNamespace(json=AsyncMock(return_value={'type': 'unknown'})))
        pending.side_effect = settings.SettingsError('invalid engine')
        state.avatar_streams.clear()
        await deferred_settings.apply_pending()
        assert deferred_settings.snapshot()['items'] == ['語音辨識']
        assert deferred_settings.snapshot()['error']
        assert not state.switching
        assert not state.settings_applying
    asyncio.run(run())


def test_body_finishing_after_last_disconnect_applies_without_waiting_for_another_peer(pending):
    async def body():
        state.avatar_streams.clear()
        return {'type': 'whisper', 'model_size': 'small'}
    async def run():
        response = await settings.set_stt_settings(SimpleNamespace(json=body))
        assert response.status == 200
        pending.assert_called_once()
        assert not deferred_settings.snapshot()['items']
        assert not state.settings_applying
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['disconnect', 'request'])
def test_queue_write_failure_keeps_settings_retryable(pending, monkeypatch, mode):
    async def run():
        payload = {'type': 'whisper', 'model_size': 'small'}
        request = SimpleNamespace(json=AsyncMock(return_value=payload))
        await settings.set_stt_settings(request)
        state.avatar_streams.clear()
        with monkeypatch.context() as patch:
            patch.setattr(deferred_settings.os, 'replace', Mock(side_effect=OSError('disk full')))
            if mode == 'disconnect':
                await deferred_settings.apply_pending()
            else:
                response = await settings.set_stt_settings(request)
                assert response.status == 503
            assert deferred_settings.snapshot()['items'] == ['語音辨識']
            assert deferred_settings.snapshot()['error']
        # Retrying in the same process must work, without requiring a restart
        # to recover the original queue from disk.
        await deferred_settings.apply_pending()
        assert pending.call_count == 2
        assert not deferred_settings.snapshot()['items']
        assert not deferred_settings.snapshot()['error']
        restored = deferred_settings.PendingSettings(deferred_settings._store().path)
        assert not restored.values
    asyncio.run(run())
