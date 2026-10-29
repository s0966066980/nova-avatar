# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""PC-specific contracts where independent Jetson sessions meet role handoffs."""
from copy import deepcopy
from io import BytesIO
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from PIL import Image
import pytest
import yaml

from src.llm import service
from src.llm.history import TransactionalHistory
from src.profiles.store import profile_config
from src.server import conversations
from src.server.state import state
from tests.test_role_coordinator import async_test, connect, field, wait_until  # noqa: F401


def picture():
    output = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(output, format='PNG')
    return output.getvalue()


def engine(text='earlier question'):
    history = TransactionalHistory(max_turns=10)
    history.append_message('user', text)
    return SimpleNamespace(
        _history=history, context_usage=None, conversation_history=history.snapshot(),
        get_last_board=lambda: None, clear_history=history.clear,
        set_last_board=lambda _: None,
    )


@async_test
async def test_short_clear_keeps_all_roles_until_full_reset(field, monkeypatch):
    voice, events = connect(field, 8, 'stage')
    voice.greetings.close()
    voice.greetings = Mock()
    voice._role_coordinator = None
    a, b = engine(), engine('specialist question')
    service._session_llm_instances.update({(8, 'main'): a, (8, 'weather'): b})
    voice.attachments.add_batch([('receipt.png', picture())], 0)
    voice._composer_has_draft = True
    voice._conversation_dirty = True
    waits = []

    async def advance(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            assert a._history.snapshot() and b._history.snapshot()
            assert voice.attachments.snapshot()['files']
            assert any(e['type'] == 'answer_clear' for e in events)
            assert not any(e['type'] == 'conversation_reset' for e in events)

    monkeypatch.setattr('src.server.voice_session.asyncio.sleep', advance)
    await voice._reset_after_idle(60)
    assert waits == [15, 45]
    assert not a._history.snapshot() and not b._history.snapshot()
    assert not voice.attachments.snapshot()['files']
    assert not voice._composer_has_draft
    assert any(e['type'] == 'conversation_reset' for e in events)
    await voice.close()


@pytest.mark.parametrize('profile_id', ['main', 'weather'])
@pytest.mark.parametrize('presenter', ['stage', 'console'])
@async_test
async def test_idle_deadlines_clear_display_then_reset_and_return_from_each_role(field, profile_id, presenter):
    field.state.config.stage.clear_display_seconds = .04
    field.state.config.stage.idle_reset_seconds = .2
    voice, events = connect(field, 8, presenter)
    console, console_events = connect(field, 9, 'console')
    roles = voice._role_coordinator
    voice._media_player = None
    roles.edge = lambda *_: dict(kind='effect', effect='fade', duration=.001)
    main, weather, separate = engine('main memory'), engine('weather memory'), engine('console memory')
    try:
        if profile_id != 'main':
            await roles._switch(profile_id, voice)
        service._session_llm_instances.update({(8, 'main'): main, (8, 'weather'): weather, (9, 'main'): separate})
        voice.attachments.add_batch([('receipt.png', picture())], 0)
        voice._composer_has_draft = True
        voice._conversation_dirty = True
        console._turn_id = 'other-conversation-answer'
        voice._refresh_gate()
        assert voice._idle_reset_task is not None, 'an idle specialist must start the same reset countdown'
        await wait_until(lambda: any(e['type'] == 'answer_clear' for e in events))
        assert main._history.snapshot() and weather._history.snapshot()
        assert voice.attachments.snapshot()['files']
        assert roles.current_id == profile_id
        await wait_until(lambda: any(e['type'] == 'conversation_reset' for e in events))
        await wait_until(lambda: roles.current_id == 'main' and not voice._greeting_returning)
        assert not main._history.snapshot() and not weather._history.snapshot()
        assert not voice.attachments.snapshot()['files']
        assert not voice._composer_has_draft
        assert not voice._conversation_dirty
        assert separate._history.snapshot()
        assert console._turn_id == 'other-conversation-answer'
        assert not any(e['type'] == 'conversation_reset' for e in console_events)
    finally:
        await voice.close()
        await console.close()


@pytest.mark.parametrize('presenter', ['stage', 'console'])
@async_test
async def test_idle_deadlines_resume_after_weather_handoff_and_answer_playback(field, monkeypatch, presenter):
    field.state.config.stage.clear_display_seconds = .04
    field.state.config.stage.idle_reset_seconds = .2
    field.weather.query = AsyncMock(return_value={'status': 'available', 'source': 'CWA', 'series': {}})
    monkeypatch.setattr('src.server.voice_session.llm_response', Mock(return_value='天氣回答'))
    voice, events = connect(field, 8, presenter)
    roles = voice._role_coordinator
    voice._media_player = None
    roles.edge = lambda *_: dict(kind='effect', effect='fade', duration=.001)

    def finish_audio():
        _, audio = voice.avatar.messages[-1]
        voice.on_output_audio_frame({**audio, 'fragment_end': True}, True)
        voice.on_output_audio(True)
        for _ in range(3):
            voice.on_output_audio(False)

    try:
        await voice.start_text_turn('明天天氣如何？')
        await voice._turn_task
        assert roles.phase == 'announcement'
        finish_audio()
        await voice._tail_task
        await wait_until(lambda: voice._turn_task is None)
        assert roles.current_id == 'weather'
        assert voice.avatar.messages[-1][0] == '天氣回答'
        voice.attachments.add_batch([('receipt.png', picture())], 0)
        finish_audio()
        await voice._tail_task
        assert voice._idle_reset_task is not None
        await wait_until(lambda: any(e['type'] == 'answer_clear' for e in events))
        assert voice.attachments.snapshot()['files']
        await wait_until(lambda: any(e['type'] == 'conversation_reset' for e in events))
        await wait_until(lambda: roles.current_id == 'main' and not voice._greeting_returning)
        assert not voice.attachments.snapshot()['files']
    finally:
        await voice.close()


@pytest.mark.parametrize('presenter', ['console', 'stage'])
@async_test
async def test_both_conversations_report_the_effective_idle_deadlines(field, presenter):
    field.state.config.stage.clear_display_seconds = 15
    field.state.config.stage.idle_reset_seconds = 60
    voice, _ = connect(field, 8, presenter)
    try:
        snapshot = conversations.snapshot(voice)
        assert snapshot['idle_reset_seconds'] == 15
        assert snapshot['full_reset_seconds'] == 60
        voice.config.stage.idle_reset_seconds = 0
        snapshot = conversations.snapshot(voice)
        assert snapshot['idle_reset_seconds'] == snapshot['full_reset_seconds'] == 0
    finally:
        await voice.close()


@pytest.mark.parametrize('record', ['inactive_role_history', 'attachment', 'draft'])
@async_test
async def test_any_visitor_record_blocks_greeting_but_console_records_do_not(field, record):
    field.state.config.stage.idle_greeting_enabled = True
    voice, _ = connect(field, 8, 'stage')
    voice.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=True, interaction=True)))
    service._session_llm_instances[(9, 'main')] = engine('console test')
    service.remember_greeting(8, 'Welcome!', profile_id='main')
    assert voice.greeting_conditions() == (True, True, True)
    if record == 'inactive_role_history':
        service._session_llm_instances[(8, 'weather')] = engine()
    elif record == 'attachment':
        voice.attachments.add_batch([('receipt.png', picture())], 0)
    else:
        voice._composer_has_draft = True
    voice.greetings.tick()
    assert not voice.greeting_conditions()[2]
    assert voice.greetings.deadline is None
    await voice.close()


@async_test
async def test_text_stage_can_greet_without_microphone_but_manual_pause_blocks_it(field):
    field.state.config.stage.composer_enabled = True
    field.state.config.stage.idle_greeting_enabled = True
    voice, _ = connect(field, 8, 'stage')
    voice.handle_control(json.dumps(dict(type='capture', enabled=False, manual_pause=False)))
    voice.handle_control(json.dumps(dict(type='stage_ready', audible=True, microphone=False, interaction=True)))
    assert voice.greeting_conditions() == (True, True, True)
    assert voice.greetings.deadline is not None
    voice.handle_control(json.dumps(dict(type='capture', enabled=False, manual_pause=True)))
    assert not voice.greeting_conditions()[0]
    assert voice.greetings.deadline is None
    await voice.close()


@async_test
async def test_role_binding_keeps_english_and_uses_each_roles_own_voice(field):
    field.profiles['main']['tts']['voice_en_us'] = 'en-US-JennyNeural'
    field.profiles['weather']['tts']['voice_en_us'] = 'en-US-GuyNeural'
    voice, _ = connect(field)
    voice._conversation['locale'] = 'en-US'
    voice._role_coordinator._bind(voice, 'weather')
    assert voice.config.llm.assistant_profile.output_locale == 'en-US'
    assert voice.config.tts.ref_file == 'en-US-GuyNeural'
    voice._role_coordinator._bind(voice, 'main')
    assert voice.config.llm.assistant_profile.output_locale == 'en-US'
    assert voice.config.tts.ref_file == 'en-US-JennyNeural'
    assert field.profiles['main']['assistant_profile']['output_locale'] == 'zh-TW'
    await voice.close()


@async_test
async def test_manual_clear_only_clears_selected_source_and_preserves_role(field, monkeypatch):
    visitor, _ = connect(field, 8, 'stage')
    console, _ = connect(field, 9, 'console')
    visitor._manual_pause = True
    visitor._capture_requested = False
    visitor.interrupt = AsyncMock()
    visitor.attachments.add_batch([('visitor.png', picture())], 0)
    console.attachments.add_batch([('console.png', picture())], 0)
    monkeypatch.setattr(state, 'voice_sessions', {8: visitor, 9: console})
    before = field.current_id
    visitor._role_coordinator.confirmed[8] = {'county': '臺北市'}
    console._role_coordinator.confirmed[9] = {'county': '臺南市'}
    result = await conversations.clear_conversation(SimpleNamespace(match_info={'sessionid': '8'}))
    assert result.status == 200
    assert not visitor.attachments.snapshot()['files']
    assert console.attachments.snapshot()['files']
    assert field.current_id == before
    assert 8 not in visitor._role_coordinator.confirmed
    assert console._role_coordinator.confirmed[9]['county'] == '臺南市'
    assert visitor._manual_pause and not visitor._capture_requested
    await visitor.close()
    await console.close()


@async_test
async def test_unsupported_attachment_handoff_is_rejected_before_role_announcement(field, monkeypatch):
    voice, _ = connect(field)
    item = voice.attachments.add_batch([('receipt.png', picture())], 0)[0]
    voice.attachments.select([{'id': item['id']}])
    monkeypatch.setattr('src.server.attachments.vision_ready', lambda _: False)
    voice._turn_id = 'question'
    voice._start_turn_context('question')
    result = await voice._role_coordinator.before_generate(voice, '明天天氣如何', 'question', voice._generation)
    assert 'fixed' in result
    assert 'handoff_id' not in result
    assert field.current_id == 'main'
    assert voice.attachments.selection
    assert not voice._role_coordinator.pending
    await voice.close()


def test_history_limits_apply_to_all_roles_without_combining_their_context(monkeypatch):
    main, specialist, other = engine(), engine(), engine()
    for entry in (main, specialist):
        for i in range(5):
            entry._history.append_message('user', str(i))
    monkeypatch.setattr(service, '_session_llm_instances', {(8, 'main'): main, (8, 'weather'): specialist, (9, 'main'): other})
    service.set_session_history_limit(8, 3)
    assert main._history.info()['retained_messages'] == 3
    assert specialist._history.info()['retained_messages'] == 3
    assert other._history.info()['max_messages'] == 20
    assert service.session_memory(8, profile_id='main')['retained_messages'] == 3


def test_profile_english_voice_defaults_preserve_original_chinese_voice(field):
    profile = deepcopy(field.profiles['main'])
    profile['tts']['ref_file'] = 'zh-TW-YunJheNeural'
    config = profile_config(field.state.config, profile)
    assert config.tts.ref_file == 'zh-TW-YunJheNeural'
    assert config.tts.voice_en_us == 'en-US-JennyNeural'


def script(name):
    path = Path(__file__).resolve().parents[1] / 'scripts' / name
    spec = importlib.util.spec_from_file_location('pc_port_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_migration_keeps_existing_models_content_and_enable_switches(tmp_path):
    module = script('migrate-pc-conversations.py')
    original = {'llm': {'model': 'existing-model'}, 'stage': {'idle_reset_seconds': 10,
                'idle_greeting_enabled': True, 'composer_enabled': False},
                'greeting': {'scripts': ['Existing welcome']},
                'tts': {'ref_file': 'zh-TW-YunJheNeural'}, 'custom': {'retain': True}}
    path = tmp_path / 'runtime.yaml'
    path.write_text(yaml.safe_dump(original))
    before = path.read_bytes()
    backup = module.migrate(path, backup_dir=tmp_path / 'backups')
    assert backup.read_bytes() == before
    assert backup.stat().st_mode & 0o777 == 0o600
    values = yaml.safe_load(path.read_text())
    for key in ['llm', 'greeting', 'tts', 'custom']:
        assert values[key] == original[key]
    assert values['stage'] == {**original['stage'], 'clear_display_seconds': 15,
                               'idle_reset_seconds': 60, 'idle_greeting_seconds': 30}
    assert values['asr'] == {'type': 'whisper', 'model_size': 'small', 'language': 'auto'}
    assert module.migrate(path, backup_dir=tmp_path / 'backups') is None
    assert len(list((tmp_path / 'backups').iterdir())) == 1


def test_ragflow_sync_is_additive_and_idempotent_without_changing_defaults(monkeypatch):
    module = script('ragflow_connection.py')
    models = [{'name': 'bge-m3', 'provider_name': 'Ollama', 'instance_name': 'nova-chat'}]
    mutations = []

    def api(key, method, path, body=None):
        if method == 'GET':
            return {
                '/providers': [{'name': 'Ollama'}],
                '/providers/Ollama/instances': [{'instance_name': 'nova-chat'}],
                '/providers/Ollama/instances/nova-chat': {'base_url': module.SHARED_MODEL_URL},
                '/models': models,
            }[path]
        mutations.append((method, path, body))
        assert method == 'POST' and path.endswith('/models')
        models.append({'name': body['model_name'], 'provider_name': 'Ollama', 'instance_name': 'nova-chat'})

    monkeypatch.setattr(module, 'model_api', api)
    monkeypatch.setattr(module, 'ollama_api', lambda path, *args: (
        {'models': [{'name': 'bge-m3:latest'}, {'name': 'new:latest'}]}
        if path == '/api/tags' else {'capabilities': ['completion']}))
    module.sync_models('test-key')
    module.sync_models('test-key')
    assert len(mutations) == 1
    assert mutations[0][2]['model_name'] == 'new:latest'
    assert models[0]['name'] == 'bge-m3'


@async_test
async def test_english_fixed_weather_failure_is_spoken_in_english(field):
    voice, _ = connect(field)
    voice._conversation['locale'] = 'en-US'
    voice._turn_id = 'weather-error'
    voice._start_turn_context('weather-error')
    voice._speak_fixed('Weather?', '目前暫時無法取得所問的最新天氣資料，請稍後再試。',
                       'weather-error', voice._generation, 'text')
    assert 'weather data is temporarily unavailable' in voice.avatar.messages[-1][0]
    await voice.close()
