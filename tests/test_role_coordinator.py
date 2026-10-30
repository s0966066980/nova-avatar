# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import asyncio
from copy import deepcopy
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
        def close(self): pass
    route = route_question(field.state.config, field.library, 'main', text, [], confirmed, client_factory=Client)
    assert route['route'] == expected


def test_routing_reuses_one_client_across_concurrent_turns_until_shutdown(field):
    from concurrent.futures import ThreadPoolExecutor
    from src.profiles.routing import RoutingClients
    result = dict(route='answer')
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])
    built = []
    class Client:
        def __init__(self, **options):
            self.options, self.closed = options, False
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
            built.append(self)
        def close(self): self.closed = True
    roles = RoleCoordinator(field.state, field.store, field.library, weather=field.weather,
                            routing_clients=RoutingClients(Client))
    config = field.state.config
    with ThreadPoolExecutor(4) as pool:
        routes = list(pool.map(lambda text: roles.router(config, roles.library, 'main', text, [], {}),
                               ['公司地址？', '營業時間？', '有停車場嗎？', '怎麼預約？']))
    assert [r['route'] for r in routes] == ['answer'] * 4
    assert len(built) == 1
    assert built[0].options['max_retries'] == 0
    asyncio.run(roles.close())
    assert built[0].closed
    # A turn that outlives shutdown cannot reopen a connection.
    with pytest.raises(RuntimeError):
        roles.router(config, roles.library, 'main', '公司地址？', [], {})


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


@pytest.mark.parametrize('presenter', ['console', 'stage'])
@async_test
async def test_both_pages_accept_input_with_the_other_page_connected(field, presenter):
    console, _ = connect(field, 7, 'console')
    stage, _ = connect(field, 8, 'stage')
    voice = console if presenter == 'console' else stage
    try:
        console._refresh_gate()
        stage._refresh_gate()
        assert console._gate_open and stage._gate_open
        accepted = await voice.start_text_turn('各自朗讀', _speak_only=True)
        await voice._turn_task
        assert accepted['turn_id'] == voice._turn_id
        other = stage if voice is console else console
        assert other._gate_open
    finally:
        await console.close()
        await stage.close()


@async_test
async def test_stage_role_switch_does_not_cancel_console_answer(field):
    console, console_events = connect(field, 7, 'console')
    stage, _ = connect(field, 8, 'stage')
    console._media_player = stage._media_player = None
    stage._role_coordinator.edge = lambda *_: dict(kind='effect', effect='fade', duration=.001)
    try:
        # Exercise role cancellation separately from input permission.
        console._turn_id = 'console-answer'
        generation = console._generation
        await stage._role_coordinator._switch('weather', stage)
        assert console._turn_id == 'console-answer'
        assert console._generation == generation
        assert console.config.profile_id == 'main'
        assert stage.config.profile_id == 'weather'
        assert not any(e['type'] == 'role_clear' for e in console_events)
    finally:
        await console.close()
        await stage.close()


@pytest.mark.parametrize('apply_waiting', [False, True])
@pytest.mark.parametrize('question,town', [
    ('明天臺北市中正區會下雨嗎', '中正區'),
    ('今天台北天氣如何？', ''),
])
@async_test
async def test_handoff_waits_for_completed_audio_and_transition_video_before_one_delivery(field, monkeypatch, apply_waiting, question, town):
    roles = field
    router = roles.router
    roles.router = lambda *args: {**router(*args), 'town': town}
    voice, events = connect(roles)
    runtime = voice._role_coordinator
    weather = {'status': 'available', 'source': 'CWA', 'series': {}}
    async def query(_):
        return weather
    roles.weather.query = query
    llm = Mock(return_value='專門角色依資料回答')
    monkeypatch.setattr('src.server.voice_session.llm_response', llm)
    try:
        accepted = await voice.start_text_turn(question)
        await voice._turn_task
        assert runtime.phase == 'announcement', voice.avatar.messages
        assert runtime.current_id == 'main'
        # The main answer generated beside routing (ADR 0022) is never delivered.
        source_calls = llm.call_count
        assert source_calls <= 1
        assert [text for text, _ in voice.avatar.messages] == [roles.library['handoff']['announcement']]
        roles._apply_waiting = apply_waiting
        _, audio = voice.avatar.messages[0]
        voice.on_output_audio_frame({**audio, 'fragment_end': True}, True)
        voice.on_output_audio(True)
        for _ in range(3):
            voice.on_output_audio(False)
        await wait_until(lambda: runtime.phase == 'transition')
        assert runtime.current_id == 'main'
        assert llm.call_count == source_calls
        runtime.video_committed(voice.sessionid, {'role_transition_id': 'stale', 'role_transition_end': True})
        assert not runtime._transition_event.is_set()
        runtime.video_committed(voice.sessionid, {'role_transition_id': runtime._transition_id, 'role_transition_end': True})
        await voice._tail_task
        await wait_until(lambda: voice._turn_task is None)
        assert runtime.current_id == 'weather'
        assert llm.call_count == source_calls + 1
        assert llm.call_args.args[0] == question
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
    runtime = voice._role_coordinator
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
        assert not runtime.pending
        assert runtime.phase == 'ready'
        assert runtime.current_id == 'main'
        assert runtime.input_allowed(voice)
    finally:
        await voice.close()


@async_test
async def test_stage_reset_is_scheduled_even_while_console_is_answering(field):
    console, _ = connect(field, 7, 'console')
    stage, _ = connect(field, 8, 'stage')
    try:
        console._turn_id = 'console-answer'
        stage._conversation_dirty = True
        stage._schedule_idle_reset()
        assert stage._idle_reset_task is not None
        assert stage._role_coordinator.input_allowed(stage)
        assert console._role_coordinator.input_allowed(console)
    finally:
        await console.close()
        await stage.close()


@async_test
async def test_disabling_handoff_applies_main_profile_for_existing_and_new_peers(field, monkeypatch):
    roles = field
    voice, _ = connect(roles, presenter='stage')
    try:
        voice._role_coordinator._bind(voice, 'weather')
        disabled = dict(roles.library, enabled=False)
        # The saved main role may refer to material that was never preloaded.
        disabled['profiles'][0]['avatar_id'] = 'new_saved_material'
        disabled['profiles'][0]['assistant_profile']['assistant_name'] = '單角色接待員'
        disabled['profiles'][0]['rag'] = {'enabled': True, 'dataset_ids': ['a'*32],
            'document_scope': 'selected', 'document_ids': ['c'*32]}
        monkeypatch.setattr('src.avatars.catalog.avatar_bootable', lambda *_: (True, ''))
        roles.loader = Mock(return_value=object())
        monkeypatch.setattr('src.llm.llamacpp.ensure_server', lambda *_args, **_kwargs: 'http://localhost:8080/v1')
        await roles.apply(disabled)
        assert not roles.enabled
        assert voice.config.profile_id == 'weather'
        voice.reset_conversation()
        await voice._role_reset_task
        assert voice.config.model.avatar_id == roles.config_for_session().model.avatar_id
        assert voice.config.profile_id == 'main'
        assert voice.config.llm.assistant_profile.assistant_name == '單角色接待員'
        assert voice.config.profile_rag['document_ids'] == ['c'*32]
        assert roles.config_for_session().profile_rag == voice.config.profile_rag
        assert roles.data_for_session() is roles.assets['new_saved_material']
        assert roles.snapshot()['profiles_applied']
        assert roles.snapshot()['active_avatar_id'] == 'new_saved_material'
        assert voice.avatar._role_presentation is None
    finally:
        await voice.close()


@async_test
async def test_stage_reconnect_accepts_input_during_console_answer(field):
    console, _ = connect(field)
    console._turn_id = 'ongoing-console-turn'
    stage, events = connect(field, 8, 'stage')
    try:
        assert field.input_allowed(stage)
        assert field.input_allowed(console)
        assert stage._gate_open
        assert any(e['type'] == 'role_state' and e['active_profile_id'] == 'main' for e in events)
        assert console._turn_id == 'ongoing-console-turn'
    finally:
        await console.close()
        await stage.close()


def test_single_role_apply_blocks_new_input_until_settings_are_bound(field):
    field.library['enabled'] = False
    voice = SimpleNamespace(_presenter='console', sessionid=99)
    assert field.input_allowed(voice)
    field._apply_waiting = True
    assert not field.input_allowed(voice)


@pytest.mark.parametrize('text', ['今天台北天氣如何？', '今天臺北市天氣如何？'])
def test_county_weather_question_handoffs_without_inventing_a_district(field, text):
    result = dict(route='specialist', county='臺北市', town='', kind='forecast',
                  start_date=datetime.now().date().isoformat(), end_date=datetime.now().date().isoformat())
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])
    class Client:
        def __init__(self, **_):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
        def close(self): pass
    route = route_question(field.state.config, field.library, 'main', text, [], {}, client_factory=Client)
    assert route['route'] == 'specialist', route
    assert route['county'] == '臺北市'
    assert route.get('town', '') == ''


@async_test
async def test_idle_greeting_starts_fresh_interval_after_automatic_main_return(field):
    roles = field
    roles.state.config.stage.idle_greeting_enabled = True
    roles.state.config.stage.idle_greeting_seconds = 60
    roles.profiles['main']['greeting']['scripts'] = ['主角色的歡迎詞']
    roles.profiles['weather']['greeting']['scripts'] = ['專門角色不可自動招呼']
    voice, _ = connect(roles, 8, 'stage')
    now = [0.]
    voice.greetings.clock = lambda: now[0]
    voice._media_player = None
    voice._role_coordinator.edge = lambda *_: dict(kind='effect', effect='fade', duration=.001)
    try:
        voice.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=True, interaction=True)))
        assert voice.greetings.deadline == 60
        voice._role_coordinator.current_id = 'weather'
        voice._role_coordinator._bind(voice, 'weather')
        voice._conversation_dirty = True
        voice._refresh_gate()
        now[0] = 60
        voice.greetings.tick()
        assert voice.greetings.deadline is None
        voice.reset_conversation()
        assert voice._greeting_returning
        await wait_until(lambda: voice._role_coordinator.current_id == 'main' and not voice._greeting_returning)
        assert voice.greetings.deadline == 120
        assert not voice.avatar.messages
        now[0] = 120
        voice.greetings.tick()
        await wait_until(lambda: bool(voice.avatar.messages))
        assert voice._role_coordinator.current_id == 'main'
        assert voice.avatar.messages[-1][0] == '主角色的歡迎詞'
        assert now[0] == 120  # a complete new interval after return
        assert not voice._conversation_dirty
    finally:
        await voice.close()


@async_test
async def test_console_answer_does_not_cancel_stage_greeting(field):
    roles = field
    roles.library['enabled'] = False
    roles.phase = 'disabled'
    roles.profiles_applied = True
    roles.state.config.stage.idle_greeting_enabled = True
    roles.profiles['main']['greeting']['scripts'] = ['單角色也會招呼']
    stage, _ = connect(roles, 8, 'stage')
    console, _ = connect(roles, 7, 'console')
    now = [0.]
    stage.greetings.clock = lambda: now[0]
    try:
        stage.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=True, interaction=True)))
        now[0] = 60
        stage.greetings.tick()
        await stage.greetings.preparation
        media = dict(stage.avatar.messages[-1][1])
        turn = stage._turn_id
        await console.start_text_turn('控制台朗讀', _speak_only=True)
        await console._turn_task
        assert stage._turn_id == turn
        assert stage.accepts_media(media, 'audio')
        assert roles.input_allowed(stage)
    finally:
        await console.close()
        await stage.close()


@async_test
async def test_greeting_only_profile_apply_keeps_playing_media_and_avoids_rebinding(field):
    roles = field
    roles.profiles_applied = True
    roles.state.config.stage.idle_greeting_enabled = True
    roles.profiles['main']['greeting']['scripts'] = ['舊招呼']
    voice, _ = connect(roles, 8, 'stage')
    now = [0.]
    voice.greetings.clock = lambda: now[0]
    try:
        voice.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=True, interaction=True)))
        now[0] = 60
        voice.greetings.tick()
        await voice.greetings.preparation
        voice.on_output_audio(True)
        old_turn, old_epoch = voice._turn_id, voice.avatar._asset_epoch
        target = deepcopy(roles.library)
        target['profiles'][0]['greeting']['scripts'] = ['新招呼']
        target['revision'] += 1
        await roles.apply(target)
        assert voice._turn_id == old_turn
        assert voice.avatar._asset_epoch == old_epoch
        assert voice.config.greeting.scripts == ['舊招呼']
        assert roles.profiles['main']['greeting']['scripts'] == ['新招呼']
        assert voice.greetings.status == 'playing'
    finally:
        await voice.close()


@async_test
async def test_greeting_apply_preserves_unapplied_identity_model_and_playing_media(field):
    roles = field
    roles.profiles_applied = True
    roles.state.config.stage.idle_greeting_enabled = True
    roles.profiles['main']['greeting']['scripts'] = ['正在播放的招呼']
    voice, _ = connect(roles, 8, 'stage')
    now = [0.]
    voice.greetings.clock = lambda: now[0]
    try:
        voice.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=True, interaction=True)))
        now[0] = 60
        voice.greetings.tick()
        await voice.greetings.preparation
        voice.on_output_audio(True)
        old_turn, old_epoch = voice._turn_id, voice.avatar._asset_epoch
        old_identity = deepcopy(roles.profiles['main']['assistant_profile'])
        old_model = roles.profiles['main']['llm']['model']
        pending = deepcopy(roles.library)
        pending['profiles'][0]['assistant_profile']['assistant_name'] = '尚未套用的新身分'
        pending['profiles'][0]['llm']['model'] = 'unapplied-model'
        pending['profiles'][0]['greeting']['scripts'] = ['下一次的新招呼']
        saved = roles.store.save(pending, expected_revision=1)
        await roles.apply_greeting('main', expected_revision=saved['revision'])
        assert roles.profiles['main']['greeting']['scripts'] == ['下一次的新招呼']
        assert roles.profiles['main']['assistant_profile'] == old_identity
        assert roles.profiles['main']['llm']['model'] == old_model
        assert roles.library['revision'] == 1  # full role revision is still pending
        assert voice._turn_id == old_turn
        assert voice.avatar._asset_epoch == old_epoch
        assert voice.config.greeting.scripts == ['正在播放的招呼']
        assert voice.config.llm.model == old_model
        assert roles.store.load()['profiles'][0]['llm']['model'] == 'unapplied-model'
    finally:
        await voice.close()


@async_test
async def test_greeting_apply_requires_current_main_and_current_saved_revision(field):
    roles = field
    before = deepcopy(roles.library)
    from src.profiles.store import ProfileError
    with pytest.raises(ProfileError, match='主數位人已變更'):
        await roles.apply_greeting('weather', expected_revision=1)
    with pytest.raises(ProfileError, match='設定已更新'):
        await roles.apply_greeting('main', expected_revision=999)
    assert roles.library == before


@async_test
async def test_two_role_transitions_run_independently(field):
    console, console_events = connect(field, 7, 'console')
    stage, stage_events = connect(field, 8, 'stage')
    for voice in (console, stage):
        voice._media_player = None
        voice._role_coordinator.edge = lambda *_: dict(kind='effect', effect='fade', duration=.001)
    try:
        await asyncio.gather(*(v._role_coordinator._switch('weather', v) for v in (console, stage)))
        assert console._role_coordinator.current_id == stage._role_coordinator.current_id == 'weather'
        assert console._role_coordinator._lock is not stage._role_coordinator._lock
        await console._role_coordinator.return_to_main(console)
        assert console._role_coordinator.current_id == 'main'
        assert stage._role_coordinator.current_id == 'weather'
        assert len([e for e in console_events if e['type'] == 'role_transition_started']) == 2
        assert len([e for e in stage_events if e['type'] == 'role_transition_started']) == 1
    finally:
        await console.close()
        await stage.close()


@async_test
async def test_profile_model_change_stays_pending_until_both_pages_disconnect(field, monkeypatch):
    console, _ = connect(field, 7, 'console')
    stage, _ = connect(field, 8, 'stage')
    field.state.config.llm.endpoints = {
        'ollama': {'provider': 'ollama', 'base_url': field.state.config.llm.base_url},
        'local': {'provider': 'llamacpp', 'base_url': 'http://localhost:8080/v1'}}
    target = deepcopy(field.library)
    target['revision'] += 1
    for profile in target['profiles']:
        profile['llm']['model'] = 'new-local-model'
        profile['llm']['endpoint'] = 'local'
    loader = Mock()
    monkeypatch.setattr('src.llm.llamacpp.ensure_server', loader)
    try:
        result = await field.apply(target)
        assert result['pending']
        assert field.library['revision'] != target['revision']
        assert console.config.llm.model != 'new-local-model'
        assert stage.config.llm.model != 'new-local-model'
        loader.assert_not_called()
        await console.close()
        field.state.avatar_streams.pop(7)
        field.state.voice_sessions.pop(7)
        field.unregister(7)
        await field.apply_pending()
        loader.assert_not_called()
        await stage.close()
        field.state.avatar_streams.pop(8)
        field.state.voice_sessions.pop(8)
        field.unregister(8)
        loader.return_value = 'http://localhost:8080/v1'
        monkeypatch.setattr('src.avatars.catalog.avatar_bootable', lambda *_: (True, ''))
        monkeypatch.setattr('src.avatars.catalog.avatar_uses_green_screen', lambda *_: True)
        await field.apply_pending()
        loader.assert_called_once()
        assert not field.snapshot()['pending']
        assert field.config_for_session().llm.model == 'new-local-model'
    finally:
        await console.close()
        await stage.close()


@async_test
async def test_http_role_controls_require_and_affect_only_the_requested_session(field, monkeypatch):
    from src.server.routes import profiles
    from unittest.mock import AsyncMock
    console, _ = connect(field, 7, 'console')
    stage, _ = connect(field, 8, 'stage')
    monkeypatch.setattr(profiles.state, 'roles', field)
    monkeypatch.setattr(profiles.state, 'voice_sessions', field.state.voice_sessions)
    try:
        console.interrupt = AsyncMock()
        stage.interrupt = AsyncMock()
        request = SimpleNamespace(json=AsyncMock(return_value={'sessionid': 8}))
        response = await profiles.stop(request)
        assert response.status == 200
        stage.interrupt.assert_awaited_once()
        console.interrupt.assert_not_awaited()
        request.json.return_value = {}
        assert (await profiles.stop(request)).status == 404
        assert stage.interrupt.await_count == 1
    finally:
        await console.close()
        await stage.close()


@async_test
async def test_applying_a_breezyvoice_profile_starts_its_server_only_without_live_peers(field, monkeypatch):
    from src.profiles.store import ProfileError

    field.state.config.tts.type = 'breezyvoice'
    target = deepcopy(field.library)
    target['enabled'] = False
    main = next(p for p in target['profiles'] if p['id'] == target['pair']['main'])
    main['tts'].update(type='breezyvoice', ref_file='0123456789abcdef', model='tts/BreezyVoice-tw',
                       tts_server='http://127.0.0.1:50001')
    monkeypatch.setattr('src.avatars.catalog.avatar_bootable', lambda *_: (True, ''))
    start = Mock(return_value='http://127.0.0.1:50001')
    monkeypatch.setattr('src.tts.cosyvoice_runtime.ensure_server', start)
    await field.apply(deepcopy(target))
    start.assert_called_once_with(model_dir='tts/BreezyVoice-tw', host='127.0.0.1', port=50001)

    start.side_effect = RuntimeError('exit=1')
    with pytest.raises(ProfileError, match='BreezyVoice'):
        await field.apply(deepcopy(target))

    # A connected conversation keeps using the running server.
    start.reset_mock(side_effect=True)
    console, _ = connect(field, 7, 'console')
    try:
        await field.apply(deepcopy(target))
        start.assert_not_called()
    finally:
        await console.close()
