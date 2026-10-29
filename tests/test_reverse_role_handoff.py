# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A specialist hands non-specialist questions back through the playback fence."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src.llm import service
from src.profiles.routing import route_question
from tests.test_role_coordinator import async_test, connect, field, wait_until  # noqa: F401


def use_weather(voice):
    roles = voice._role_coordinator
    roles._bind(voice, roles.library['pair']['specialist'])
    roles.current_id = roles.library['pair']['specialist']
    return roles


async def play_announcement(voice):
    _, audio = voice.avatar.messages[-1]
    voice.on_output_audio_frame({**audio, 'fragment_end': True}, True)
    voice.on_output_audio(True)
    for _ in range(3):
        voice.on_output_audio(False)
    await wait_until(lambda: voice._role_coordinator.phase == 'transition')


@pytest.mark.parametrize('presenter', ['console', 'stage'])
@pytest.mark.parametrize('locale', ['zh-TW', 'en-US'])
@pytest.mark.parametrize('input_source', ['text', 'voice'])
@async_test
async def test_reverse_handoff_answers_once_after_playback_with_own_identity(
        field, monkeypatch, presenter, locale, input_source):
    field.router = Mock(return_value={'route': 'answer', 'context': '訪客想了解服務'})
    voice, events = connect(field, 7, presenter)
    other, _ = connect(field, 8, 'stage' if presenter == 'console' else 'console')
    voice._conversation['locale'] = locale
    # The main role keeps its own earlier history when the visitor returns.
    service.prepare_spoken_history('之前的服務問題', voice.avatar, 'prior-main')
    service.commit_session_history(7, 'prior-main', assistant_text='主角色自己的記憶', terminal_reason='completed')
    roles = use_weather(voice)
    service.prepare_spoken_history('之前的天氣問題', voice.avatar, 'prior-weather')
    service.commit_session_history(7, 'prior-weather', assistant_text='天氣角色自己的記憶', terminal_reason='completed')
    roles.library['handoff'].update(return_announcement='請主數位人接續為您介紹。',
                                    return_announcement_en='Our main avatar will introduce our services.')
    other._turn_id = 'other-conversation'
    other_generation = other._generation
    voice._conversation['voice_en_us'] = 'en-US-JennyNeural'
    roles.confirmed[7] = {'county': '臺南市', 'town': '安平區'}
    llm = Mock(return_value='主角色的服務介紹')
    monkeypatch.setattr('src.server.voice_session.llm_response', llm)
    question = '介紹你們的服務' if locale == 'zh-TW' else 'Please introduce your services.'
    try:
        if input_source == 'text':
            started = await voice.start_text_turn(question)
            source_turn = started['turn_id']
            await voice._turn_task
        else:
            # Both text and ASR transcripts enter this real generation seam.
            source_turn = voice._turn_id = uuid4().hex
            voice._start_turn_context(source_turn)
            await voice._generate_turn(question, source_turn, voice._generation, input_source='voice')
        assert roles.phase == 'announcement'
        assert roles.current_id == 'weather'
        announcement = roles.library['handoff']['return_announcement_en' if locale == 'en-US' else 'return_announcement']
        assert voice.avatar.messages[-1][0] == announcement
        llm.assert_not_called()
        field.weather.query.assert_not_called()
        await play_announcement(voice)
        assert roles.current_id == 'weather'
        llm.assert_not_called()
        roles.video_committed(7, {'role_transition_id': roles._transition_id, 'role_transition_end': True})
        await voice._tail_task
        await wait_until(lambda: voice._turn_task is None)
        assert roles.current_id == 'main'
        assert voice.config.profile_id == 'main'
        assert voice.config.llm.assistant_profile.assistant_name != '天氣助手'
        assert voice._conversation['locale'] == locale
        assert roles.confirmed[7] == {'county': '臺南市', 'town': '安平區'}
        llm.assert_called_once()
        assert llm.call_args.args[0] == question
        assert '訪客想了解服務' in llm.call_args.kwargs['rag_context']
        assert '本輪氣象工具資料' not in llm.call_args.kwargs['rag_context']
        field.router.assert_called_once()
        assert service.session_history(7, 'main')[-1]['content'] == '主角色自己的記憶'
        assert service.session_history(7, 'weather')[-1]['content'] == announcement
        assert other._turn_id == 'other-conversation'
        assert other._generation == other_generation
        assert other.config.profile_id == 'main'
        assert len([event for event in events if event['type'] == 'role_handoff']) == 1
        await roles.after_playback(voice, source_turn)
        llm.assert_called_once()
        # A new weather question can still hand off in the forward direction.
        field.router.reset_mock()
        roles.router = Mock(return_value={'route': 'specialist', 'county': '臺南市', 'town': '安平區',
            'kind': 'forecast', 'start_date': '2026-10-29', 'end_date': '2026-10-29'})
        async def weather(_query):
            return {'status': 'available', 'source': 'CWA', 'series': {}}
        roles.weather.query = weather
        await voice.start_text_turn('明天台南會下雨嗎？')
        await voice._turn_task
        assert roles.phase == 'announcement'
        assert roles.current_id == 'main'
    finally:
        await voice.close()
        await other.close()


@pytest.mark.parametrize('failure', ['interrupt', 'playback_failure', 'transition_failure'])
@async_test
async def test_cancelled_or_failed_reverse_handoff_keeps_weather_role(field, monkeypatch, failure):
    field.router = Mock(return_value={'route': 'answer', 'context': ''})
    voice, events = connect(field)
    roles = use_weather(voice)
    llm = Mock(return_value='must not be delivered')
    monkeypatch.setattr('src.server.voice_session.llm_response', llm)
    try:
        started = await voice.start_text_turn('介紹你們的服務')
        await voice._turn_task
        assert roles.phase == 'announcement'
        if failure == 'interrupt':
            await voice.interrupt()
        elif failure == 'playback_failure':
            voice._fail_playback_turn()
        else:
            bind = roles._bind_async
            async def fail_target(session, target):
                if target == 'main':
                    raise RuntimeError('target unavailable')
                await bind(session, target)
            monkeypatch.setattr(roles, '_bind_async', fail_target)
            _, audio = voice.avatar.messages[-1]
            voice.on_output_audio_frame({**audio, 'fragment_end': True}, True)
            voice.on_output_audio(True)
            for _ in range(3):
                voice.on_output_audio(False)
            await voice._tail_task
        await roles.after_playback(voice, started['turn_id'])
        assert roles.current_id == voice.config.profile_id == 'weather'
        assert roles.phase == 'ready'
        assert not roles.pending and not roles.continuations
        assert not any(e['type'] == 'role_handoff' for e in events)
        llm.assert_not_called()
    finally:
        await voice.close()


@pytest.mark.parametrize('question', ['明天台北會下雨嗎？', '明天適合爬山嗎？', '那週末呢？'])
@async_test
async def test_weather_followups_stay_with_specialist(field, question):
    field.router = Mock(return_value={'route': 'specialist', 'county': '臺北市', 'town': '',
        'kind': 'forecast', 'start_date': '2026-10-29', 'end_date': '2026-10-30'})
    weather = {'status': 'available', 'source': 'CWA', 'series': {}}
    async def query(_):
        return weather
    field.weather.query = query
    voice, _ = connect(field)
    roles = use_weather(voice)
    try:
        voice._turn_id = 'followup'
        voice._start_turn_context('followup')
        plan = await roles.before_generate(voice, question, 'followup', voice._generation)
        assert plan['weather'] == weather
        assert 'handoff_id' not in plan
        assert roles.current_id == 'weather'
        assert not roles.pending
    finally:
        await voice.close()


@async_test
async def test_mixed_question_clarifies_then_can_hand_back_the_nonweather_topic(field):
    field.router = Mock(side_effect=[{'route': 'clarify', 'clarification': '您想先問天氣，還是服務介紹？'},
                                     {'route': 'answer', 'context': '先介紹服務'}])
    voice, _ = connect(field)
    roles = use_weather(voice)
    try:
        await voice.start_text_turn('明天天氣如何？也介紹一下你們的服務')
        await voice._turn_task
        assert voice.avatar.messages[-1][0] == '您想先問天氣，還是服務介紹？'
        assert roles.current_id == 'weather'
        assert not roles.pending
        await voice.start_text_turn('先介紹服務')
        await voice._turn_task
        assert roles.phase == 'announcement'
        assert roles.current_id == 'weather'
    finally:
        await voice.close()


@async_test
async def test_reverse_handoff_checks_main_attachment_capability_before_announcing(field, monkeypatch):
    from tests.test_pc_conversations import picture
    field.router = Mock(return_value={'route': 'answer'})
    voice, _ = connect(field)
    roles = use_weather(voice)
    item = voice.attachments.add_batch([('question.png', picture())], 0)[0]
    voice.attachments.select([{'id': item['id']}])
    monkeypatch.setattr('src.server.attachments.vision_ready', lambda config: config.profile_id == 'weather')
    try:
        await voice.start_text_turn('說明附件中的公司服務')
        await voice._turn_task
        assert '接手角色目前無法讀取附件' in voice.avatar.messages[-1][0]
        assert roles.current_id == 'weather'
        assert not roles.pending
        assert voice.attachments.selection == [{'id': item['id']}]
    finally:
        await voice.close()


def test_nonweather_routing_is_not_rejected_for_weather_location_fields(field):
    result = {'route': 'answer', 'county': '臺北市', 'town': '中正區'}
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])
    create = Mock(return_value=response)
    class Client:
        def __init__(self, **_): self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        def close(self): pass
    routed = route_question(field.state.config, field.library, 'weather',
        '比較台北和高雄的公司服務', [], {}, client_factory=Client)
    assert routed['route'] == 'answer'
    assert routed['county'] == routed['town'] == ''
    prompt = create.call_args.kwargs['messages'][0]['content']
    assert '不能自動反向交接' not in prompt
    assert '非專長問題' in prompt


@async_test
async def test_a_new_question_supersedes_continuation_waiting_for_attachment_validation(field, monkeypatch):
    from threading import Event
    from tests.test_pc_conversations import picture
    field.router = Mock(return_value={'route': 'answer'})
    voice, _ = connect(field)
    roles = voice._role_coordinator
    roles.continuations[7] = {'id': 'old-handoff', 'target_profile_id': 'main',
                              'context': 'stale context', 'readers': {}}
    item = voice.attachments.add_batch([('question.png', picture())], 0)[0]
    checking, resume = Event(), Event()
    def vision_ready(_):
        checking.set()
        assert resume.wait(3)
        return True
    monkeypatch.setattr('src.server.attachments.vision_ready', vision_ready)
    llm = Mock(return_value='new answer')
    monkeypatch.setattr('src.server.voice_session.llm_response', llm)
    old = asyncio.create_task(voice.start_text_turn('stale continued question',
        _handoff_id='old-handoff', attachments=[{'id': item['id']}]))
    try:
        assert await asyncio.to_thread(checking.wait, 2)
        current = await voice.start_text_turn('New question', attachments=[])
        await voice._turn_task
        resume.set()
        with pytest.raises(ValueError, match='cancelled'):
            await old
        assert voice._turn_id == current['turn_id']
        llm.assert_called_once()
        assert llm.call_args.args[0] == 'New question'
        assert not roles.continuations
    finally:
        resume.set()
        await asyncio.gather(old, return_exceptions=True)
        await voice.close()


@async_test
async def test_stale_handoff_failure_cannot_cancel_a_new_forward_handoff(field, monkeypatch):
    from threading import Event
    from unittest.mock import AsyncMock
    from tests.test_pc_conversations import picture
    field.router = Mock(return_value={'route': 'specialist', 'county': '臺北市', 'town': '',
        'kind': 'forecast', 'start_date': '2026-10-29', 'end_date': '2026-10-29'})
    field.weather.query = AsyncMock(return_value={'status': 'available', 'source': 'CWA', 'series': {}})
    voice, _ = connect(field)
    roles = voice._role_coordinator
    roles.pending[7] = dict(id='old-handoff', source_turn='old-source', target_profile_id='main',
        question='介紹公司服務', context='', readers={})
    # The target was bound by _switch; hold only its attachment acceptance step.
    monkeypatch.setattr(roles, '_switch', AsyncMock())
    item = voice.attachments.add_batch([('question.png', picture())], 0)[0]
    voice.attachments.select([{'id': item['id']}])
    checking, resume = Event(), Event()
    def vision_ready(_):
        checking.set()
        assert resume.wait(3)
        return True
    monkeypatch.setattr('src.server.attachments.vision_ready', vision_ready)
    old = asyncio.create_task(roles.after_playback(voice, 'old-source'))
    try:
        assert await asyncio.to_thread(checking.wait, 2)
        await voice.start_text_turn('明天台北會下雨嗎？', attachments=[])
        await voice._turn_task
        replacement = roles.pending[7]
        assert roles.phase == 'announcement'
        resume.set()
        await old
        assert roles.pending.get(7) is replacement
        assert roles.phase == 'announcement'
        assert roles.error == ''
    finally:
        resume.set()
        await asyncio.gather(old, return_exceptions=True)
        await voice.close()

