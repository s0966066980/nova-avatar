# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Exercise reservation, negotiation and cleanup through the real offer route."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
import pytest
from src.config.schema import Config
from src.server.state import state
from src.server.routes import webrtc


@pytest.fixture
def rtc(monkeypatch):
    config = Config()
    for name, value in dict(config=config, model_ready=True, model=object(), avatar=object(),
                            switching=False, settings_applying=False, shutting_down=False, avatar_streams={},
                            voice_sessions={}, session_roles={}, pcs=set(), presentation=None).items():
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
        def addTrack(self, track):
            if not hasattr(self, 'tracks'): self.tracks = {}
            self.tracks[track.kind] = track
        def getTransceivers(self): return []
        async def setRemoteDescription(self, value):
            if value.sdp == 'bad': raise ValueError('invalid SDP')
            if value.sdp == 'microphone': self.handlers['track'](SimpleNamespace(kind='audio'))
        async def createAnswer(self): return SimpleNamespace(sdp='answer', type='answer')
        async def setLocalDescription(self, value): self.localDescription = value
        async def close(self): self.connectionState = 'closed'
    def voice(*args, **kwargs):
        value = MagicMock()
        value.sessionid = args[0]
        value.prepare = AsyncMock()
        value.close = AsyncMock()
        voices.append(value)
        return value
    monkeypatch.setattr(webrtc, 'RTCPeerConnection', Peer)
    monkeypatch.setattr(webrtc, 'HumanPlayer', lambda *a, **k: SimpleNamespace(
        audio=SimpleNamespace(kind='audio'), video=SimpleNamespace(kind='video'),
        discard_stale_media=Mock()))
    monkeypatch.setattr(webrtc, 'VoiceTurnSession', voice)
    monkeypatch.setattr(webrtc, 'create_avatar', lambda *a: object())
    def request(role='console', sdp='good'):
        result = AsyncMock()
        result.json.return_value = dict(client_role=role, sdp=sdp, type='offer')
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


def test_recvonly_offer_does_not_prepare_speech_models(rtc):
    async def run():
        result = await webrtc.offer(rtc.request())
        assert result.status == 200
        rtc.voices[0].prepare.assert_not_awaited()

    asyncio.run(run())



def test_microphone_preparation_runs_in_parallel_with_negotiation(rtc):
    async def run():
        release = asyncio.Event()
        rtc.voices.clear()
        original = webrtc.VoiceTurnSession
        def voice(*args, **kwargs):
            value = original(*args, **kwargs)
            value.prepare.side_effect = release.wait
            return value
        from unittest.mock import patch
        with patch.object(webrtc, 'VoiceTurnSession', voice):
            response = await asyncio.wait_for(webrtc.offer(rtc.request(sdp='microphone')), .5)
        assert response.status == 200
        await asyncio.sleep(0)
        rtc.voices[0].prepare.assert_awaited_once()
        assert rtc.voices[0]._preparing is True
        release.set()
        await asyncio.sleep(0)
        await rtc.peers[0].handlers['connectionstatechange']()
    asyncio.run(run())


def test_voice_cleanup_failure_still_closes_the_peer(rtc):
    async def run():
        await webrtc.offer(rtc.request())
        rtc.voices[0].close.side_effect = RuntimeError("voice cleanup failed")
        rtc.peers[0].connectionState = "failed"
        await rtc.peers[0].handlers["connectionstatechange"]()
        assert rtc.peers[0].connectionState == "closed"
        assert not state.pcs
        assert not state.avatar_streams
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
        assert not state.voice_sessions
    asyncio.run(run())


def test_disconnect_releases_all_role_llm_parents(rtc, monkeypatch):
    import json
    from src.llm import service
    monkeypatch.setattr(service, '_session_llm_instances', {})
    monkeypatch.setattr(service, '_active_profiles', {})
    async def run():
        response = await webrtc.offer(rtc.request())
        sid = json.loads(response.text)['sessionid']
        service._session_llm_instances[(sid, 'main')] = SimpleNamespace(parent=object())
        service._session_llm_instances[(sid, 'weather')] = SimpleNamespace(parent=object())
        service.select_session_profile(sid, 'weather')
        rtc.peers[0].connectionState = 'failed'
        await rtc.peers[0].handlers['connectionstatechange']()
        assert not service._session_llm_instances
        assert sid not in service._active_profiles
    asyncio.run(run())


def test_single_profile_config_drives_new_voice_sessions_without_handoff(rtc, monkeypatch):
    from copy import deepcopy
    from unittest.mock import Mock
    effective = deepcopy(state.config)
    effective.profile_id = 'main'
    effective.profile_rag = {'enabled': True, 'dataset_ids': ['a'*32],
        'document_scope': 'selected', 'document_ids': ['c'*32]}
    roles = SimpleNamespace(enabled=False, profiles_applied=True, phase='disabled', _apply_waiting=False,
        config_for_session=lambda: effective, data_for_session=lambda: object(),
        register=Mock(), unregister=Mock(), apply_pending=AsyncMock())
    monkeypatch.setattr(state, 'roles', roles)
    monkeypatch.setattr(webrtc, 'create_avatar', lambda *args: SimpleNamespace(config=args[0]))
    original = webrtc.VoiceTurnSession
    captured = []
    def voice(sessionid, config, avatar, **kwargs):
        captured.append((config, avatar.config))
        return original(sessionid, config, avatar, **kwargs)
    monkeypatch.setattr(webrtc, 'VoiceTurnSession', voice)
    async def run():
        response = await webrtc.offer(rtc.request())
        assert response.status == 200
        assert captured[0][0] is captured[0][1] is effective
        assert captured[0][0].profile_rag['document_ids'] == ['c'*32]
        rtc.peers[0].connectionState = 'failed'
        await rtc.peers[0].handlers['connectionstatechange']()
    asyncio.run(run())


@pytest.mark.parametrize('source_role', ['console', 'stage'])
@pytest.mark.parametrize('late_join', [False, True])
def test_questions_and_played_answers_stay_on_the_source_page(rtc, monkeypatch, source_role, late_join):
    from src.server.voice_session import VoiceTurnSession

    roles = SimpleNamespace(enabled=False, profiles_applied=False, phase='disabled', _apply_waiting=False, cancel=Mock(), unregister=Mock(), notify=Mock(),
        apply_pending=AsyncMock(),
        config_for_session=lambda: state.config, data_for_session=lambda: state.avatar,
        input_allowed=lambda voice: True)
    roles.register = lambda voice: setattr(voice, '_role_coordinator', roles)
    monkeypatch.setattr(state, 'roles', roles)
    monkeypatch.setattr(webrtc, 'VoiceTurnSession', VoiceTurnSession)
    monkeypatch.setattr(webrtc, 'create_avatar', lambda config, *args: SimpleNamespace(
        config=config, configure_media_fence=Mock(), flush_talk=Mock()))

    async def run():
        events = {}
        try:
            for index, role in enumerate([source_role, 'stage' if source_role == 'console' else 'console']):
                response = await webrtc.offer(rtc.request(role))
                sid = json.loads(response.text)['sessionid']
                events[role] = []
                state.voice_sessions[sid].attach_event_sink(lambda raw, role=role: events[role].append(json.loads(raw)))
                if late_join and index == 0:
                    state.voice_sessions[sid]._emit('user_transcript', turn_id='current-turn', text='目前的問題')
                    state.voice_sessions[sid]._emit('assistant_fragment', turn_id='current-turn', text='實際播出的回答')
            source = next(v for v in state.voice_sessions.values() if v._presenter == source_role)
            if not late_join:
                source._emit('user_transcript', turn_id='current-turn', text='目前的問題')
                source._emit('assistant_fragment', turn_id='current-turn', text='實際播出的回答')
            for role in ['console', 'stage']:
                messages = [(e['type'], e.get('text')) for e in events[role] if e['type'] in {'user_transcript', 'assistant_fragment'}]
                expected = [('user_transcript', '目前的問題'), ('assistant_fragment', '實際播出的回答')] if role == source_role else []
                assert messages == expected
            from unittest.mock import patch
            viewer = next(v for v in state.voice_sessions.values() if v is not source)
            receipt = json.dumps(dict(type='board_displayed', presenter=viewer._presenter,
                turn_id='current-turn', board_id='current-turn', item_index=0))
            with patch('src.server.voice_session.acknowledge_session_board_item', return_value=True) as acknowledge:
                viewer.handle_control(receipt)
                viewer.handle_control(receipt)
                acknowledge.assert_called_once_with(viewer.sessionid, turn_id='current-turn',
                    board_id='current-turn', item_index=0, presenter=viewer._presenter)
        finally:
            for peer in rtc.peers:
                peer.connectionState = 'failed'
                await peer.handlers['connectionstatechange']()

    asyncio.run(run())


def test_new_offer_waits_for_deferred_resource_application(rtc, monkeypatch):
    monkeypatch.setattr(state, 'settings_applying', True)
    async def run():
        response = await webrtc.offer(rtc.request())
        assert response.status == 409
        assert not state.avatar_streams
        assert not rtc.peers
    asyncio.run(run())


@pytest.mark.parametrize('resource', ['engine', 'settings', 'profiles'])
def test_offer_body_finishing_during_resource_update_does_not_create_peer(rtc, monkeypatch, resource):
    async def run():
        request = rtc.request()
        payload = request.json.return_value
        async def body():
            if resource == 'engine':
                monkeypatch.setattr(state, 'switching', True)
            elif resource == 'settings':
                monkeypatch.setattr(state, 'settings_applying', True)
            else:
                monkeypatch.setattr(state, 'roles', SimpleNamespace(phase='ready', _apply_waiting=True))
            return payload
        request.json.side_effect = body
        response = await webrtc.offer(request)
        assert response.status == 409
        assert not state.avatar_streams
        assert not rtc.peers
        assert not rtc.voices
    asyncio.run(run())


def test_disconnect_discards_an_unfinished_recording(rtc, monkeypatch):
    avatar = SimpleNamespace(discard_recording=AsyncMock())
    monkeypatch.setattr(webrtc, 'create_avatar', lambda *a: avatar)
    async def run():
        await webrtc.offer(rtc.request())
        rtc.peers[0].connectionState = 'closed'
        await rtc.peers[0].handlers['connectionstatechange']()
        avatar.discard_recording.assert_awaited_once()
        assert not state.avatar_streams
    asyncio.run(run())


def test_lost_microphone_track_closes_the_peer_so_the_page_reconnects(rtc):
    async def run():
        await webrtc.offer(rtc.request(sdp='microphone'))
        voice = rtc.voices[0]
        on_lost = voice.start_track.call_args.kwargs['on_lost']

        on_lost()
        on_lost()
        for _ in range(50):
            if not state.voice_sessions:
                break
            await asyncio.sleep(0)

        assert rtc.peers[0].connectionState == 'closed'
        voice.close.assert_awaited_once()
        assert not state.voice_sessions and not state.pcs
        assert state.count_sessions('console') == 0
    asyncio.run(run())
