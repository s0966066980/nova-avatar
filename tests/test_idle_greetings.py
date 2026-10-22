# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Proactive content, deadlines, visitor priority and played-only memory."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest

from src.config.loader import dict_to_config
from src.config.schema import Config, GreetingConfig
from src.greetings.content import (GreetingError, greeting_messages, prepare_greeting,
                                  validate_content, validate_interval, visible_length)
from src.llm import service
from src.profiles.store import ProfileStore, profile_config, validate_library
from src.server.voice_session import VoiceTurnSession
from tests.test_voice_session import FakeAvatar, FakeSegmenter


@pytest.mark.parametrize('text,count', [('你好，世界！', 6), ('a e\u0301 👨‍👩‍👧‍👦 🇹🇼\n', 4), ('\t\n　', 0), ('👍🏽！', 2), ('a\u0085b', 2)])
def test_visible_graphemes(text, count):
    assert visible_length(text) == count


@pytest.mark.parametrize('value', [0, -1, True, '60', None, float('inf'), float('nan')])
def test_interval_rejects_invalid(value):
    with pytest.raises(GreetingError):
        validate_interval(value)


@pytest.mark.parametrize('value', [dict(min_chars=0), dict(max_chars=True), dict(min_chars=61),
                                  dict(mode='other'), dict(mode='ai'), dict(scripts=[]),
                                  dict(scripts='hello'), dict(prompt=3)])
def test_required_content(value):
    with pytest.raises(GreetingError):
        validate_content(value, required=True)


def test_old_config_and_profiles_default_off(tmp_path):
    config = dict_to_config({})
    assert config.stage.idle_greeting_enabled is False
    assert config.stage.idle_greeting_seconds == 60
    library = ProfileStore(tmp_path / 'roles.yaml').initialize(config)
    for p in library['profiles']:
        p.pop('greeting')
    library = validate_library(library)
    assert library['profiles'][0]['greeting'] == asdict(GreetingConfig())
    edited = deepcopy(library['profiles'][0])
    edited['greeting'].update(mode='ai', prompt='歡迎訪客', min_chars=10, max_chars=35)
    applied = profile_config(config, edited)
    assert applied.greeting.prompt == '歡迎訪客'
    assert config.greeting.prompt == ''


class ContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripts_deduplicate_and_avoid_repeat_but_allow_single_and_out_of_range(self):
        config = Config(greeting=GreetingConfig(scripts=['甲', '甲', '乙', ' ']))
        for _ in range(5):
            result = await prepare_greeting(config, previous='甲')
            self.assertEqual(result, dict(text='乙', length=1, in_range=False))
        config.greeting.scripts = ['甲']
        self.assertEqual((await prepare_greeting(config, previous='甲'))['text'], '甲')

    async def test_ai_has_only_identity_and_prompt_and_retries_once(self):
        config = Config(greeting=GreetingConfig(mode='ai', prompt='介紹服務', min_chars=4, max_chars=8))
        config.llm.assistant_profile.system_prompt = '你是展館導覽員'
        config.llm.assistant_profile.restriction_prompt = '只回答展館資訊'
        generate = AsyncMock(side_effect=['短', '歡迎來參觀！'])
        result = await prepare_greeting(config, generate=generate)
        self.assertEqual(result['text'], '歡迎來參觀！')
        self.assertEqual(generate.await_count, 2)
        messages = greeting_messages(config, asdict(config.greeting))
        self.assertEqual([m['role'] for m in messages], ['system', 'user'])
        self.assertIn('你是展館導覽員', messages[0]['content'])
        self.assertIn('只回答展館資訊', messages[0]['content'])
        self.assertEqual(messages[1]['content'], '介紹服務')

    async def test_ai_invalid_twice_skips_and_does_not_retry_exception(self):
        config = Config(greeting=GreetingConfig(mode='ai', prompt='介紹'))
        generate = AsyncMock(return_value='短')
        with self.assertRaisesRegex(GreetingError, '字數不合格'):
            await prepare_greeting(config, generate=generate)
        self.assertEqual(generate.await_count, 2)
        generate = AsyncMock(side_effect=RuntimeError('SECRET https://private.example'))
        with self.assertRaisesRegex(GreetingError, '^AI 招呼生成失敗，已略過本次$'):
            await prepare_greeting(config, generate=generate)
        self.assertEqual(generate.await_count, 1)

    async def test_timeout_budget_includes_second_attempt(self):
        config = Config(greeting=GreetingConfig(mode='ai', prompt='介紹'))
        calls = []
        async def generate(*_):
            calls.append(1)
            await asyncio.sleep(.04)
            return '短'
        with self.assertRaisesRegex(GreetingError, '超過 15 秒'):
            await prepare_greeting(config, generate=generate, timeout=.06)
        self.assertEqual(len(calls), 2)


class SessionTests(unittest.IsolatedAsyncioTestCase):
    def make(self, *, presenter='stage'):
        self.now = 0.
        config = Config(greeting=GreetingConfig(scripts=['歡迎光臨！']))
        config.stage.idle_greeting_enabled = True
        config.stage.idle_greeting_seconds = 60
        config.stage.idle_reset_seconds = 120
        avatar = FakeAvatar()
        avatar.config = config
        session = VoiceTurnSession(111, config, avatar, presenter=presenter, clock=lambda: self.now)
        session._segmenter = FakeSegmenter()
        session._event_loop = asyncio.get_running_loop()
        events = []
        session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
        self.addAsyncCleanup(session.close)
        self.addCleanup(service.remove_session, 111)
        return session, events

    def ready(self, session, **changes):
        session.handle_control(json.dumps(dict(type='stage_ready', audible=True,
                                              microphone=True, interaction=True, **changes)))

    async def trigger(self, session):
        self.ready(session)
        self.now += 60
        session.greetings.tick()
        task = session.greetings.preparation
        if task:
            await task

    async def test_requires_explicit_stage_readiness_then_full_interval(self):
        session, _ = self.make()
        self.now = 1000
        session.greetings.tick()
        self.assertIsNone(session.greetings.deadline)
        self.ready(session)
        self.now += 59
        session.greetings.tick()
        self.assertFalse(session.avatar.messages)
        self.now += 1
        session.greetings.tick()
        await session.greetings.preparation
        self.assertTrue(session.is_greeting)
        self.assertTrue(session._gate_open)
        self.assertFalse(session._conversation_dirty)

    async def test_waits_for_clear_without_restarting_expired_deadline(self):
        session, _ = self.make()
        session._conversation_dirty = True
        self.ready(session)
        self.now = 60
        session.greetings.tick()
        self.assertEqual(session.greetings.status, 'waiting_clear')
        self.assertIsNone(session.greetings.preparation)
        self.now = 120
        session.reset_conversation()
        session.greetings.tick()
        await session.greetings.preparation
        self.assertTrue(session.is_greeting)
        self.assertFalse(session._conversation_dirty)

    async def test_visitor_cancels_ai_and_late_result_cannot_queue(self):
        session, _ = self.make()
        started = asyncio.Event()
        async def stubborn(*_, **__):
            started.set()
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                return dict(text='過期招呼')
        session.greetings.prepare = stubborn
        self.ready(session)
        self.now = 60
        session.greetings.tick()
        task = session.greetings.preparation
        await started.wait()
        session.greetings.reset()
        session._turn_id = 'visitor'
        session._start_turn_context('visitor')
        await task
        self.assertFalse(session.avatar.messages)
        self.assertEqual(session._turn_id, 'visitor')

    async def test_vad_speech_cancels_fenced_tts_without_losing_visitor(self):
        session, _ = self.make()
        await self.trigger(session)
        old = dict(session.avatar.messages[-1][1])
        def speech(_):
            session._segmenter.is_speaking = True
            return []
        session._segmenter.process = speech
        await session.feed_pcm(np.ones(512, dtype=np.int16))
        self.assertFalse(session.is_greeting)
        self.assertFalse(session.accepts_media(old, 'late_tts'))
        self.assertTrue(session._conversation_dirty)
        self.assertTrue(session._gate_open)
        self.assertNotIn(111, service._latest_greetings)

    async def test_only_played_receipt_no_visitor_history_and_full_interval_after_play(self):
        session, _ = self.make()
        with patch('src.server.voice_session.prepare_spoken_history') as history:
            await self.trigger(session)
        history.assert_not_called()
        self.assertNotIn(111, service._latest_greetings)
        metadata = session.avatar.messages[-1][1]
        session.on_output_audio_frame(metadata, True)
        session.on_output_audio(True)
        self.assertFalse(session._gate_open)
        session._commit_history('completed')
        self.assertEqual(service._latest_greetings[111], '歡迎光臨！')
        self.assertEqual(service.session_history(111), [])
        self.now = 70
        session._output_active = False
        await session._finish_tail_guard()
        self.assertEqual(session.greetings.deadline, 130)
        self.assertFalse(session._conversation_dirty)
        self.assertIsNone(session._idle_reset_task)

    async def test_edits_cancel_preparation_but_allow_started_playback_disable_stops(self):
        session, _ = self.make()
        await self.trigger(session)
        old = dict(session.avatar.messages[-1][1])
        session.config.greeting.scripts = ['新版文案']
        session.greetings.refresh()
        self.assertFalse(session.accepts_media(old, 'late_media'))
        self.assertEqual(session.greetings.deadline, 120)
        self.now = 120
        session.greetings.tick()
        await session.greetings.preparation
        session.on_output_audio(True)
        current = session._turn_id
        session.config.greeting.scripts = ['下一版']
        session.greetings.refresh()
        self.assertEqual(session._turn_id, current)
        session.config.stage.idle_greeting_enabled = False
        session.greetings.refresh()
        self.assertIsNone(session._turn_id)
        self.assertFalse(session._output_active)

    async def test_disconnect_and_paused_readiness_cancel_and_resume_full_interval(self):
        session, _ = self.make()
        await self.trigger(session)
        session.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=True, interaction=False)))
        self.assertIsNone(session._turn_id)
        self.assertIsNone(session.greetings.deadline)
        self.now = 100
        self.ready(session)
        self.assertEqual(session.greetings.deadline, 160)
        session.detach_event_sink()
        self.assertIsNone(session.greetings.deadline)

    async def test_input_accepted_before_output_wins_when_vad_worker_finishes_late(self):
        session, _ = self.make()
        await self.trigger(session)
        started = asyncio.Event()
        old = dict(session.avatar.messages[-1][1])
        loop = asyncio.get_running_loop()
        # A blocked real worker models VAD processing across first audio.
        from threading import Event
        worker_release = Event()
        def speech(_):
            loop.call_soon_threadsafe(started.set)
            worker_release.wait(2)
            session._segmenter.is_speaking = True
            return []
        session._segmenter.process = speech
        feeding = asyncio.create_task(session.feed_pcm(np.ones(512, dtype=np.int16)))
        await started.wait()
        session.on_output_audio(True)
        worker_release.set()
        await feeding
        self.assertFalse(session.is_greeting)
        self.assertTrue(session._gate_open)
        self.assertTrue(session._conversation_dirty)
        self.assertFalse(session.accepts_media(old, "stale_tts"))

    async def test_unplayed_cancel_does_not_replace_last_script_selection(self):
        session, _ = self.make()
        session.greetings.previous = '實際播過的文案'
        await self.trigger(session)
        session.cancel_greeting()
        self.assertEqual(session.greetings.previous, '實際播過的文案')
        self.assertIsNone(session._turn_id)

    async def test_muted_playback_cancel_restores_gate_for_later_visitor(self):
        session, _ = self.make()
        await self.trigger(session)
        session.on_output_audio(True)
        session.handle_control(json.dumps(dict(type='stage_ready', audible=False, microphone=True, interaction=True)))
        self.assertIsNone(session._turn_id)
        self.assertTrue(session._gate_open)
        self.ready(session)
        self.assertEqual(session.greetings.deadline, self.now + 60)

    async def test_unspeakable_script_skips_cycle_instead_of_sticking_session(self):
        session, _ = self.make()
        session.config.greeting.scripts = ['😀']
        await self.trigger(session)
        self.assertFalse(session.is_greeting)
        self.assertIn('沒有可朗讀文字', session.greetings.error)
        self.assertFalse(session.avatar.messages)

    async def test_console_never_schedules(self):
        session, _ = self.make(presenter='console')
        self.ready(session)
        self.assertIsNone(session.greetings.deadline)
        self.assertFalse(session.avatar.messages)

    async def test_failure_is_private_and_next_cycle_is_not_immediate(self):
        session, _ = self.make()
        session.greetings.prepare = AsyncMock(side_effect=RuntimeError('secret'))
        await self.trigger(session)
        self.assertNotIn('secret', session.greetings.error)
        self.assertFalse(session.avatar.messages)
        self.assertEqual(session.greetings.deadline, 120)
        session.greetings.tick()
        self.assertIsNone(session.greetings.preparation)


def test_latest_receipt_replaces_and_clears_without_history():
    try:
        service.remember_greeting(222, 'old', profile_id='main')
        service.remember_greeting(222, 'new', profile_id='main')
        assert service._latest_greetings[(222, 'main')] == 'new'
        assert service.session_history(222, 'main') == []
        service.clear_session_history(222)
        assert (222, 'main') not in service._latest_greetings
    finally:
        service.remove_session(222)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setup_field(self):
        from src.server.routes import profiles
        from tempfile import TemporaryDirectory
        from pathlib import Path
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Config()
        store = ProfileStore(Path(directory.name) / 'roles.yaml')
        library = store.initialize(config)
        draft = deepcopy(library['profiles'][0])
        draft['greeting']['scripts'] = ['未儲存的招呼草稿']
        roles = SimpleNamespace(mode='console')
        fake_state = SimpleNamespace(config=config, voice_sessions={})
        fake_state.roles = roles
        patcher = patch.object(profiles, 'state', fake_state)
        patcher.start()
        self.addCleanup(patcher.stop)
        return profiles, fake_state, draft

    async def test_preview_uses_validated_draft_without_publishing(self):
        routes, state, draft = self.setup_field()
        request = SimpleNamespace(json=AsyncMock(return_value={'profile': draft}))
        response = await routes.greeting_preview(request)
        data = json.loads(response.text)
        self.assertEqual(response.status, 200)
        self.assertEqual(data['text'], '未儲存的招呼草稿')
        self.assertFalse(state.config.greeting.scripts)
        self.assertNotIn('api_key', data)
        self.assertFalse(state.voice_sessions)

    async def test_trial_is_console_only_and_uses_draft_voice_snapshot(self):
        routes, state, draft = self.setup_field()
        config = state.config
        avatar = FakeAvatar()
        avatar.config = config
        avatar.tts = SimpleNamespace(config=config)
        voice = VoiceTurnSession(333, config, avatar)
        voice.attach_event_sink(lambda _: None)
        state.voice_sessions[333] = voice
        self.addAsyncCleanup(voice.close)
        self.addCleanup(service.remove_session, 333)
        draft['tts']['ref_file'] = 'draft-voice'
        request = SimpleNamespace(json=AsyncMock(return_value={'profile': draft, 'sessionid': 333}))
        state.roles.mode = 'visitor'
        self.assertEqual((await routes.greeting_try(request)).status, 409)
        state.roles.mode = 'console'
        response = await routes.greeting_try(request)
        self.assertEqual(response.status, 202)
        self.assertEqual(avatar.messages[-1][0], '未儲存的招呼草稿')
        self.assertEqual(avatar.tts.config.tts.ref_file, 'draft-voice')
        self.assertFalse(voice._conversation_dirty)
        voice.cancel_greeting(stop_playing=True)
        self.assertIs(avatar.tts.config, config)

    async def test_pending_trial_cancel_never_publishes_late_text(self):
        routes, state, draft = self.setup_field()
        avatar = FakeAvatar()
        avatar.config = state.config
        voice = VoiceTurnSession(334, state.config, avatar)
        voice.attach_event_sink(lambda _: None)
        state.voice_sessions[334] = voice
        self.addAsyncCleanup(voice.close)
        preparing = asyncio.Event()
        async def slow(*_, **__):
            preparing.set()
            await asyncio.sleep(100)
        request = SimpleNamespace(json=AsyncMock(return_value={'profile': draft, 'sessionid': 334}))
        with patch.object(routes, 'prepare_greeting', slow):
            task = asyncio.create_task(routes.greeting_try(request))
            await preparing.wait()
            # Mode changes and visitor acceptance use this same cancellation seam.
            voice.greetings.reset(stop_playing=True)
            response = await task
        self.assertEqual(response.status, 409)
        self.assertFalse(avatar.messages)
        self.assertIsNone(voice._greeting_trial_preparation)


def test_stage_enable_validates_content_and_persists_atomically():
    from src.server.runtime_settings import apply_stage_settings, SettingsError
    config = Config()
    with pytest.raises(SettingsError, match='至少一篇'):
        apply_stage_settings(config, {'idle_greeting_enabled': True})
    assert not config.stage.idle_greeting_enabled
    config.greeting.scripts = ['歡迎！']
    before = config.stage
    with patch('src.server.runtime_settings.persist_runtime_overrides', side_effect=OSError):
        with pytest.raises(OSError):
            apply_stage_settings(config, {'idle_greeting_enabled': True, 'idle_greeting_seconds': 15})
    assert config.stage is before
    with patch('src.server.runtime_settings.persist_runtime_overrides') as persist:
        result = apply_stage_settings(config, {'idle_greeting_enabled': True, 'idle_greeting_seconds': .5})
    assert result['idle_greeting_enabled'] is True
    assert result['idle_greeting_seconds'] == .5
    persist.assert_called_once_with(config)


def test_only_latest_played_greeting_is_injected_into_visitor_followup(monkeypatch):
    config = Config()
    config.profile_id = 'main'
    avatar = SimpleNamespace(config=config, sessionid=444)
    llm = SimpleNamespace(generate_response=Mock(return_value='可以協助您導覽'))
    monkeypatch.setattr(service, '_session_llm_instances', {(444, 'main'): llm})
    monkeypatch.setattr(service, '_latest_greetings', {})
    monkeypatch.setattr(service, '_ensure_llamacpp_if_needed', lambda _: None)
    service.remember_greeting(444, '舊招呼', profile_id='main')
    service.remember_greeting(444, '新的導覽介紹', profile_id='main')
    try:
        service.llm_response('你剛才提到什麼服務？', avatar)
        context = llm.generate_response.call_args.kwargs['rag_context']
        assert '新的導覽介紹' in context
        assert '舊招呼' not in context
        assert service.session_history(444) == []
    finally:
        service.remove_session(444)
