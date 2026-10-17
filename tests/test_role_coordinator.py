# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import asyncio
from datetime import datetime
import json
from functools import wraps
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config.schema import Config
from src.llm import service
from src.profiles.coordinator import RoleCoordinator
from src.profiles.media import RolePresentation
from src.profiles.routing import route_question
from src.profiles.store import ProfileStore, profile_config
from src.server.voice_session import VoiceTurnSession


class Avatar:
    def __init__(self, config, sid):
        self.config, self.sessionid = config, sid
        self.messages = []
        self._asset_epoch = 0
        self._role_presentation = RolePresentation()

    def configure_media_fence(self, **callbacks):
        self.callbacks = callbacks

    def put_msg_txt(self, text, data):
        self.messages.append((text, data))
        self.callbacks['on_fragment_queued'](text, data)

    def flush_talk(self):
        pass

    def bind_profile(self, config, _data):
        self.config = config
        self._asset_epoch += 1


@pytest.fixture
def field(tmp_path, monkeypatch):
    monkeypatch.setattr(service, '_session_llm_instances', {})
    monkeypatch.setattr(service, '_active_profiles', {})
    monkeypatch.setattr('src.profiles.store.avatar_settings', lambda _: {'enabled': False, 'dataset_ids': []})
    config = Config()
    config.model.type = 'musetalk'
    config.model.avatar_id = 'musetalk_angela'
    config.reply_streaming.enabled = False
    store = ProfileStore(tmp_path / 'profiles.yaml')
    library = store.initialize(config)
    library['enabled'] = True
    state = SimpleNamespace(config=config, voice_sessions={}, avatar_streams={},
        avatar=object(),
        count_sessions=lambda kind: sum(v._presenter == kind for v in state.voice_sessions.values()))
    weather = SimpleNamespace(configured=True, query=Mock())
    route = {'route': 'specialist', 'county': '臺北市', 'town': '中正區', 'kind': 'forecast',
        'start_date': datetime.now().date().isoformat(), 'end_date': datetime.now().date().isoformat(),
        'context': '已確認臺北市中正區'}
    roles = RoleCoordinator(state, store, library, router=lambda *_: dict(route), weather=weather)
    roles.phase = 'ready'
    roles.assets = {'musetalk_angela': object(), 'musetalk_1': object()}
    return roles


def connect(roles, sid=7, presenter='console'):
    config = profile_config(roles.state.config, roles.profiles[roles.current_id])
    avatar = Avatar(config, sid)
    voice = VoiceTurnSession(sid, config, avatar, presenter=presenter)
    voice._media_player = SimpleNamespace(discard_stale_media=lambda: None)
    roles.state.voice_sessions[sid] = voice
    roles.state.avatar_streams[sid] = avatar
    roles.register(voice)
    events = []
    voice.attach_event_sink(lambda raw: events.append(json.loads(raw)))
    return voice, events


@pytest.mark.parametrize('text,confirmed,expected', [
    ('中正區明天會下雨嗎', {}, 'clarify'),
    ('新竹明天的天氣', {}, 'clarify'),
    ('臺北市中正區明天的天氣', {}, 'specialist'),
    ('那明天呢', {'county': '臺北市', 'town': '中正區'}, 'specialist'),
])
def test_routing_does_not_guess_a_county_for_an_ambiguous_district(field, text, confirmed, expected):
    result = dict(route='specialist', county='臺北市', town='中正區', kind='forecast')
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])
    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
        def __enter__(self): return self
        def __exit__(self, *_): pass
    route = route_question(field.state.config, field.library, 'main', text, [], confirmed, client_factory=Client)
    assert route['route'] == expected


async def wait_until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(poll(), timeout=3)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


@pytest.mark.parametrize('apply_waiting', [False, True])
@async_test
async def test_handoff_waits_for_completed_audio_and_transition_video_before_one_delivery(field, monkeypatch, apply_waiting):
    roles = field
    voice, events = connect(roles)
    weather = {'status': 'available', 'source': 'CWA', 'series': {}}
    async def query(_):
        return weather
    roles.weather.query = query
    llm = Mock(return_value='專門角色依資料回答')
    monkeypatch.setattr('src.server.voice_session.llm_response', llm)
    try:
        accepted = await voice.start_text_turn('明天臺北市中正區會下雨嗎')
        await voice._turn_task
        assert roles.phase == 'announcement'
        assert roles.current_id == 'main'
        llm.assert_not_called()
        roles._apply_waiting = apply_waiting
        _, audio = voice.avatar.messages[0]
        voice.on_output_audio_frame({**audio, 'fragment_end': True}, True)
        voice.on_output_audio(True)
        for _ in range(3):
            voice.on_output_audio(False)
        await wait_until(lambda: roles.phase == 'transition')
        assert roles.current_id == 'main'
        llm.assert_not_called()
        roles.video_committed(voice.sessionid, {'role_transition_id': 'stale', 'role_transition_end': True})
        assert not roles._transition_event.is_set()
        roles.video_committed(voice.sessionid, {'role_transition_id': roles._transition_id, 'role_transition_end': True})
        await voice._tail_task
        await wait_until(lambda: voice._turn_task is None)
        assert roles.current_id == 'weather'
        llm.assert_called_once()
        assert llm.call_args.args[0] == '明天臺北市中正區會下雨嗎'
        assert '本輪氣象工具資料' in llm.call_args.kwargs['rag_context']
        assert voice.config.llm.assistant_profile.assistant_name == '天氣助手'
        assert len([e for e in events if e['type'] == 'role_handoff']) == 1
        assert service.session_history(7, 'main')[-1]['content'] == roles.library['handoff']['announcement']
        assert accepted['turn_id'] != voice._turn_id
    finally:
        await voice.close()
        await roles.close()


@async_test
async def test_read_aloud_obeys_owner_and_uses_turn_media_fences(field):
    roles = field
    voice, _ = connect(roles)
    try:
        roles.mode = 'visitor'
        with pytest.raises(RuntimeError, match='另一個輸入來源'):
            await voice.start_text_turn('不能繞過收音模式', _speak_only=True)
        roles.mode = 'console'
        result = await voice.start_text_turn('朗讀測試', _speak_only=True)
        await voice._turn_task
        text, media = voice.avatar.messages[-1]
        assert text == '朗讀測試'
        assert media['turn_id'] == result['turn_id']
        assert voice.accepts_media(media, 'echo')
        await voice.interrupt()
        assert not voice.accepts_media(media, 'echo')
    finally:
        await voice.close()


@pytest.mark.parametrize('failure', ['interrupt', 'playback_failure'])
@async_test
async def test_cancelled_announcement_never_hands_off_and_recovers_input(field, failure):
    roles = field
    voice, _ = connect(roles)
    cancelled = asyncio.Event()
    async def slow_weather(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    roles.weather.query = slow_weather
    try:
        await voice.start_text_turn('天氣問題')
        await voice._turn_task
        await asyncio.sleep(0)
        if failure == 'interrupt':
            await voice.interrupt()
        else:
            voice._fail_playback_turn()
        await wait_until(cancelled.is_set)
        assert not roles.pending
        assert roles.phase == 'ready'
        assert roles.current_id == 'main'
        assert roles.input_allowed(voice)
    finally:
        await voice.close()


@async_test
async def test_mode_switch_keeps_memories_and_rejects_other_input(field):
    roles = field
    console, _ = connect(roles, 7, 'console')
    stage, _ = connect(roles, 8, 'stage')
    try:
        assert roles.mode == 'visitor'
        with pytest.raises(RuntimeError, match='另一個輸入來源'):
            await console.start_text_turn('不應接受')
        await roles.set_mode('console')
        assert roles.input_allowed(console)
        assert not roles.input_allowed(stage)
        stage._conversation_dirty = True
        stage._schedule_idle_reset()
        assert stage._idle_reset_task is None
        await roles.set_mode('visitor')
        assert roles.input_allowed(stage)
    finally:
        await console.close()
        await stage.close()


@async_test
async def test_disabling_roles_uses_same_single_role_config_for_existing_and_new_peers(field):
    roles = field
    voice, _ = connect(roles)
    try:
        roles._bind(voice, 'weather')
        disabled = dict(roles.library, enabled=False)
        # The saved main role may refer to material that was never preloaded.
        disabled['profiles'][0]['avatar_id'] = 'new_saved_material'
        await roles.apply(disabled)
        assert not roles.enabled
        assert voice.config.model.avatar_id == roles.config_for_session().model.avatar_id
        assert not getattr(voice.config, 'profile_id', '')
        assert voice.avatar._role_presentation is None
    finally:
        await voice.close()


@async_test
async def test_stage_reconnect_waits_for_existing_console_work_then_restores_visitor_mode(field):
    roles = field
    console, _ = connect(roles)
    console._turn_id = 'ongoing-console-turn'
    stage, events = connect(roles, 8, 'stage')
    try:
        assert roles.mode == 'console'
        assert not roles.input_allowed(stage)
        console._turn_id = None
        # A handoff between its source and destination turns is still work.
        roles.pending[7] = {'id': 'handoff'}
        console._refresh_gate()
        assert roles.mode == 'console'
        roles.pending.clear()
        console._refresh_gate()
        assert roles.mode == 'visitor'
        assert roles.input_allowed(stage)
        assert any(e['type'] == 'role_state' and e['mode'] == 'visitor' for e in events)
    finally:
        await console.close()
        await stage.close()
