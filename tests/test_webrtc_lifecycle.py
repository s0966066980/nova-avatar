# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Exercise reservation, negotiation and cleanup through the real offer route."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from src.config.schema import Config
from src.server.state import state
from src.server.routes import webrtc


@pytest.fixture
def rtc(monkeypatch):
    config = Config()
    for name, value in dict(config=config, model_ready=True, model=object(), avatar=object(),
                            switching=False, reply_prewarm_ready=True, avatar_streams={},
                            voice_sessions={}, session_roles={}, pcs=set(),
                            session_cleanups={}, session_clients={}).items():
        monkeypatch.setattr(state, name, value, raising=False)
    peers, voices = [], []
    class Peer:
        def __init__(self, configuration):
            self.configuration = configuration
            self.handlers = {}
            self.connectionState = 'new'
            peers.append(self)
        def on(self, name):
            def attach(fn): self.handlers[name] = fn; return fn
            return attach
        def addTrack(self, track): pass
        def getTransceivers(self): return []
        async def setRemoteDescription(self, value):
            if value.sdp == 'bad': raise ValueError('invalid SDP')
        async def createAnswer(self): return SimpleNamespace(sdp='answer', type='answer')
        async def setLocalDescription(self, value): self.localDescription = value
        async def close(self): self.connectionState = 'closed'
    def voice(*args, **kwargs):
        value = MagicMock()
        value.prepare = AsyncMock()
        value.close = AsyncMock()
        voices.append(value)
        return value
    monkeypatch.setattr(webrtc, 'RTCPeerConnection', Peer)
    monkeypatch.setattr(webrtc, 'HumanPlayer', lambda *a, **k: SimpleNamespace(audio=object(), video=object()))
    monkeypatch.setattr(webrtc, 'VoiceTurnSession', voice)
    monkeypatch.setattr(webrtc, 'create_avatar', lambda *a: object())
    def request(role='console', sdp='good', client_id=None):
        result = AsyncMock()
        result.json.return_value = dict(client_role=role, sdp=sdp, type='offer', client_id=client_id)
        return result
    return SimpleNamespace(request=request, peers=peers, voices=voices)


def test_failed_avatar_creation_releases_role_capacity(rtc, monkeypatch):
    def failed(*args): raise RuntimeError('avatar failed')
    monkeypatch.setattr(webrtc, 'create_avatar', failed)
    async def run():
        with pytest.raises(RuntimeError, match='avatar failed'):
            await webrtc.offer(rtc.request())
        assert state.count_sessions('console') == 0
        assert not state.session_roles
    asyncio.run(run())


def test_failed_sdp_closes_peer_and_voice_and_releases_capacity(rtc):
    async def run():
        with pytest.raises(ValueError, match='invalid SDP'):
            await webrtc.offer(rtc.request(sdp='bad'))
        assert not state.avatar_streams
        assert not state.voice_sessions
        assert not state.pcs
        assert rtc.peers[0].connectionState == 'closed'
        rtc.voices[0].close.assert_awaited_once()
    asyncio.run(run())


def test_recvonly_offer_does_not_wait_for_speech_models_or_external_stun(rtc):
    async def run():
        result = await webrtc.offer(rtc.request())
        assert result.status == 200
        rtc.voices[0].prepare.assert_not_awaited()
        assert rtc.peers[0].configuration.iceServers == []
    asyncio.run(run())


def test_console_and_stage_can_connect_and_same_tab_can_replace_its_session(rtc):
    async def run():
        assert (await webrtc.offer(rtc.request('console', client_id='console-tab'))).status == 200
        assert (await webrtc.offer(rtc.request('stage', client_id='stage-tab'))).status == 200
        assert (await webrtc.offer(rtc.request('console', client_id='console-tab'))).status == 200
        assert state.count_sessions('console') == 1
        assert state.count_sessions('stage') == 1
        assert len(state.pcs) == 2
        assert (await webrtc.offer(rtc.request('console', client_id='different-tab'))).status == 429
    asyncio.run(run())


def test_cancelled_offer_waits_for_worker_then_releases_reservation(rtc, monkeypatch):
    import threading
    entered, finish = threading.Event(), threading.Event()
    def build(*args):
        entered.set()
        finish.wait(2)
        return object()
    monkeypatch.setattr(webrtc, 'create_avatar', build)
    async def run():
        task = asyncio.create_task(webrtc.offer(rtc.request()))
        try:
            while not entered.is_set(): await asyncio.sleep(.005)
            task.cancel()
            await asyncio.sleep(.01)
            assert state.count_sessions('console') == 1
        finally:
            finish.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert state.count_sessions('console') == 0
        assert not state.session_clients
    asyncio.run(run())


def test_switch_cleanup_notifies_and_closes_both_presenters(rtc):
    async def run():
        await webrtc.offer(rtc.request('console', client_id='console-tab'))
        await webrtc.offer(rtc.request('stage', client_id='stage-tab'))
        await webrtc.close_sessions(presentation_change=True)
        assert not state.avatar_streams and not state.pcs
        for voice in rtc.voices:
            voice._emit.assert_called_once_with('presentation_changing')
            voice.close.assert_awaited_once()
    asyncio.run(run())


def test_voice_cleanup_failure_still_closes_peer_and_releases_capacity(rtc):
    async def run():
        await webrtc.offer(rtc.request())
        rtc.voices[0].close.side_effect = RuntimeError('voice cleanup failed')
        with pytest.raises(RuntimeError, match='voice cleanup failed'):
            await webrtc.close_sessions()
        assert rtc.peers[0].connectionState == 'closed'
        assert not state.avatar_streams and not state.pcs
    asyncio.run(run())
