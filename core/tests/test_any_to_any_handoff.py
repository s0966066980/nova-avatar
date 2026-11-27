# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Any member hands a question directly to any other (ticket 03, ADR 0023)."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from nova_llm import service
from tests.role_fakes import async_test, connect, field, route_to, wait_until  # noqa: F401

SERVICE_ANNOUNCEMENT = '接下來請客服小幫手為您說明。'
SERVICE_ANNOUNCEMENT_EN = 'Our service assistant will help you next.'


def add_member(roles, pid='service', name='客服小幫手', avatar_id='musetalk_angela', *, enabled=True,
               weather=False, **profile_changes):
    profile = deepcopy(roles.profiles['weather'])
    profile.update(id=pid, name=name, avatar_id=avatar_id, **profile_changes)
    profile['assistant_profile'] = dict(profile['assistant_profile'], assistant_name=name)
    roles.library['profiles'].append(profile)
    roles.library['composition']['members'].append({
        'profile_id': pid, 'revision': 1, 'enabled': enabled, 'description': f'{name}的專長',
        'rules': '', 'announcement': SERVICE_ANNOUNCEMENT if pid == 'service' else f'接下來請{name}說明。',
        'announcement_en': SERVICE_ANNOUNCEMENT_EN if pid == 'service' else '',
        'tools': {'weather': {'enabled': weather, 'county': '', 'town': ''}}})
    return profile


def use_role(voice, profile_id):
    roles = voice._role_coordinator
    roles._bind(voice, profile_id)
    roles.current_id = profile_id
    return roles


async def plan_for(voice, text):
    """Route one turn directly, as the generation seam does."""
    voice._turn_id = 'direct'
    voice._start_turn_context('direct')
    return await voice._role_coordinator.before_generate(voice, text, 'direct', voice._generation)


@pytest.mark.parametrize('locale', ['zh-TW', 'en-US'])
@pytest.mark.parametrize('source,target,expected', [
    ('weather', 'service', (SERVICE_ANNOUNCEMENT, SERVICE_ANNOUNCEMENT_EN)),
    ('service', 'weather', ('接下來請天氣助手為您說明。', 'I will ask our specialist to help with your question.')),
    ('service', 'main', ('接下來請主數位人接續回答您的問題。', 'Our main avatar will help with your question next.')),
])
@async_test
async def test_any_member_hands_off_directly_with_the_target_announcement(
        field, monkeypatch, locale, source, target, expected):
    add_member(field)
    # The weather tool holder needs a place to look up.
    lookup = dict(county='臺北市', kind='forecast') if target == 'weather' else {}
    field.router = Mock(return_value=route_to(target, context='直接交接', **lookup))

    async def query(_):
        return {'status': 'available', 'source': 'CWA', 'series': {}}
    field.weather.query = query
    voice, events = connect(field)
    voice._media_player = None
    voice._conversation['locale'] = locale
    roles = use_role(voice, source)
    roles.edge = lambda *_: dict(kind='effect', effect='fade', duration=.001)
    llm = Mock(return_value='目的角色的回答')
    monkeypatch.setattr('nova_core.server.voice_session.llm_response', llm)
    try:
        await voice.start_text_turn('換個主題的問題')
        await voice._turn_task
        assert roles.phase == 'announcement'
        assert voice.avatar.messages[-1][0] == expected[locale == 'en-US']
        source_calls = llm.call_count
        _, audio = voice.avatar.messages[-1]
        voice.on_output_audio_frame({**audio, 'fragment_end': True}, True)
        voice.on_output_audio(True)
        for _ in range(3):
            voice.on_output_audio(False)
        await wait_until(lambda: roles.current_id == target and voice._turn_task is None and llm.call_count > source_calls)
        assert voice.config.profile_id == target
        assert llm.call_args.args[0] == '換個主題的問題'
        assert '直接交接' in llm.call_args.kwargs['rag_context']
        # Each role keeps its own conversation memory.
        assert service.session_history(7, source)[-1]['content'] == expected[locale == 'en-US']
        assert not any(m['content'] == expected[locale == 'en-US'] for m in service.session_history(7, target))
        started = [e for e in events if e['type'] == 'role_transition_started']
        assert [(e['source_profile_id'], e['target_profile_id']) for e in started] == [(source, target)]
        field.router.assert_called_once()
        assert field.router.call_args.args[2] == source
    finally:
        await voice.close()


@pytest.mark.parametrize('route', [route_to('tour'), route_to('ghost')])
@async_test
async def test_a_target_outside_the_live_members_is_never_handed_to(field, route):
    add_member(field, 'tour', '導覽員', enabled=False)
    field.router = Mock(return_value=route)
    voice, _ = connect(field)
    try:
        plan = await plan_for(voice, '問題')
        assert 'fixed' in plan and 'handoff_id' not in plan
        assert not voice._role_coordinator.pending
    finally:
        await voice.close()


@pytest.mark.parametrize('holder', ['weather', 'service'])
@async_test
async def test_only_the_weather_tool_holder_queries_weather(field, holder):
    add_member(field, weather=holder == 'service')
    field.library['composition']['members'][0]['tools']['weather']['enabled'] = holder == 'weather'
    weather = {'status': 'available', 'source': 'CWA', 'series': {}}

    async def query(_):
        return weather
    field.weather.query = Mock(side_effect=query)
    voice, _ = connect(field)
    roles = voice._role_coordinator
    try:
        for target in ('weather', 'service'):
            roles.router = Mock(return_value=route_to(target, county='臺北市' if target == holder else '',
                                                      kind='forecast' if target == holder else ''))
            use_role(voice, target)
            plan = await plan_for(voice, '明天臺北天氣')
            if target == holder:
                assert plan['weather'] == weather
            else:
                assert plan == roles.speculative_plan()
        assert field.weather.query.call_count == 1
    finally:
        await voice.close()


def test_transitions_use_the_override_otherwise_the_default(field):
    add_member(field)
    transitions = field.library['composition']['transitions']
    transitions['default'] = dict(kind='effect', effect='zoom', duration=1.0, asset_id='')
    transitions['overrides'] = [dict(source='weather', target='service', kind='effect', effect='slide_left',
                                     duration=0.4, asset_id='')]
    # The two-role view's edges are no longer consulted.
    field.library['transitions'] = [dict(source='main', target='weather', kind='video', effect='fade',
                                         duration=0.6, asset_id='legacy-clip')]
    voice, _ = connect(field)
    roles = voice._role_coordinator
    assert roles.edge('weather', 'service')['effect'] == 'slide_left'
    assert roles.edge('service', 'weather')['effect'] == 'zoom'
    assert roles.edge('main', 'weather')['kind'] == 'effect'


@async_test
async def test_any_member_returns_to_main_on_request_and_on_visitor_reset(field):
    add_member(field)
    voice, _ = connect(field, 8, 'stage')
    voice._media_player = None
    roles = use_role(voice, 'service')
    roles.edge = lambda *_: dict(kind='effect', effect='fade', duration=.001)
    try:
        snapshot = roles.snapshot()
        assert snapshot['can_return'] and snapshot['main_profile_id'] == 'main'
        assert snapshot['member_ids'] == ['weather', 'service'] and 'pair' not in snapshot
        await roles.return_to_main(voice)
        assert roles.current_id == 'main' and voice.config.profile_id == 'main'
        assert not roles.snapshot()['can_return']
        roles = use_role(voice, 'service')
        voice.reset_conversation()
        await wait_until(lambda: voice._role_coordinator.current_id == 'main' and not voice._greeting_returning)
        assert voice.config.profile_id == 'main'
    finally:
        await voice.close()


@async_test
async def test_idle_greeting_only_runs_on_the_main_avatar(field):
    add_member(field)
    field.state.config.stage.idle_greeting_enabled = True
    voice, _ = connect(field, 8, 'stage')
    try:
        voice.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=True, interaction=True)))
        assert voice.greeting_conditions()[0]
        use_role(voice, 'service')
        assert not voice.greeting_conditions()[0]
    finally:
        await voice.close()


@async_test
async def test_apply_loads_each_live_member_avatar_once_and_releases_unused_ones(field, monkeypatch):
    monkeypatch.setattr('nova_render.catalog.avatar_bootable', lambda *_: (True, ''))
    monkeypatch.setattr('nova_render.catalog.avatar_uses_green_screen', lambda *_: True)
    field.state.config.model.avatar_id = 'musetalk_angela'
    add_member(field, 'service', avatar_id='musetalk_angela')           # shares the main avatar
    add_member(field, 'guide', '展覽導覽', avatar_id='guide_avatar')
    add_member(field, 'tour', '導覽員', avatar_id='tour_avatar', enabled=False)
    odd = add_member(field, 'odd', '不相容', avatar_id='odd_avatar')
    odd['tts'] = dict(odd['tts'], type='edgetts' if odd['tts']['type'] != 'edgetts' else 'cosyvoice')
    target = deepcopy(field.library)
    field.assets = {'stale_avatar': object()}
    loaded = []
    field.loader = lambda config: loaded.append(config.model.avatar_id) or f'data:{config.model.avatar_id}'
    await field.apply(target)
    assert sorted(loaded) == ['guide_avatar', 'musetalk_1']
    assert set(field.assets) == {'musetalk_angela', 'musetalk_1', 'guide_avatar'}
    assert field.assets['musetalk_angela'] is field.state.avatar
    assert field.snapshot()['member_ids'] == ['weather', 'service', 'guide']
    # A re-apply reuses what is loaded; a disabled composition keeps only the main avatar.
    loaded.clear()
    await field.apply(deepcopy(target))
    assert loaded == []
    target['composition']['enabled'] = False
    await field.apply(deepcopy(target))
    assert set(field.assets) == {'musetalk_angela'}
    assert not field.enabled
