# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Exercise language isolation, memory boundaries and the controller API."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.config.schema import Config
from src.llm import service
from src.llm.context_usage import measure_request, ContextCapacityError
from src.llm.engines.openai import OpenAILLM
from src.llm.history import TransactionalHistory
from src.server import conversations
from src.server.state import state
from src.server.voice_session import VoiceTurnSession


@pytest.fixture
def env(monkeypatch):
    config = Config()
    config.stage.idle_reset_seconds = 0
    monkeypatch.setattr(state, 'config', config)
    monkeypatch.setattr(state, 'voice_sessions', {})
    monkeypatch.setattr(service, '_session_llm_instances', {})
    monkeypatch.setattr(conversations, 'warm_voice', AsyncMock())
    def create(number):
        avatar = SimpleNamespace(config=deepcopy(config), flush_talk=Mock())
        session = VoiceTurnSession(number, config, avatar, presenter='stage')
        state.voice_sessions[number] = session
        llm = OpenAILLM(config=avatar.config, api_key='test')
        service._session_llm_instances[number] = llm
        return session, llm
    return config, create


def test_history_limit_defers_and_never_restores_evicted_messages():
    history = TransactionalHistory(max_turns=3)
    for number in range(6):
        history.append_message('user', str(number))
    transaction = history.begin('new', turn_id='turn')
    history.set_limit(2)
    assert len(history.request_messages(transaction)) == 7
    history.commit(transaction, assistant_text='reply', terminal_reason='completed')
    assert [m['content'] for m in history.snapshot()] == ['new', 'reply']
    assert history.info()['evicted_messages'] == 6
    history.set_limit(20)
    assert len(history.snapshot()) == 2
    history.clear()
    assert history.info()['evicted_messages'] == 0


def test_language_switch_preserves_played_history_and_other_sessions(env):
    _, create = env
    async def run():
        first, llm = create(1)
        other, other_llm = create(2)
        first._turn_id = 'old'
        first._start_turn_context('old')
        llm.begin_history_turn('question', turn_id='old')
        first._played_fragments.append('already heard')
        other_llm.add_to_history('user', 'unaffected')
        await first.apply_conversation({'locale': 'en-US'})
        assert first.avatar.config.llm.assistant_profile.output_locale == 'en-US'
        assert first.avatar.config.tts.ref_file == 'en-US-JennyNeural'
        assert [m['content'] for m in llm.conversation_history] == ['question', 'already heard']
        assert other.avatar.config.llm.assistant_profile.output_locale == 'zh-TW'
        assert other_llm.conversation_history[0]['content'] == 'unaffected'
        assert state.config.conversation.locale == 'zh-TW'
        await first.close(); await other.close()
    asyncio.run(run())


def test_failed_voice_switch_keeps_original_settings(env, monkeypatch):
    _, create = env
    monkeypatch.setattr(conversations, 'warm_voice', AsyncMock(side_effect=RuntimeError('voice_unavailable')))
    async def run():
        session, _ = create(1)
        with pytest.raises(RuntimeError, match='voice_unavailable'):
            await session.apply_conversation({'locale': 'en-US'})
        assert session._conversation['locale'] == 'zh-TW'
        assert session.avatar.config.tts.ref_file == 'zh-TW-HsiaoChenNeural'
        assert not session._settings_switching
        await session.close()
    asyncio.run(run())


def test_limit_change_during_turn_applies_at_idle(env):
    _, create = env
    async def run():
        session, llm = create(1)
        for i in range(20): llm.add_to_history('user', str(i))
        session._turn_id = 'active'
        await session.apply_conversation({'history_max_messages': 4})
        assert len(llm.conversation_history) == 20
        assert session._pending_history_limit == 4
        session._turn_id = None
        session._refresh_gate()
        assert len(llm.conversation_history) == 4
        assert llm._history.info()['evicted_messages'] == 16
        await session.close()
    asyncio.run(run())


@pytest.mark.parametrize('reopen_capture', [False, True])
def test_language_switch_discards_inflight_old_microphone_frames(env, reopen_capture):
    from threading import Event
    import numpy as np
    _, create = env
    async def run():
        session, _ = create(1)
        started, release = Event(), Event()
        session._segmenter = object()
        session._gate_open = True
        def segment(_pcm):
            started.set()
            assert release.wait(2)
            return False, True, []
        session._segment_pcm_sync = segment
        task = asyncio.create_task(session.feed_pcm(np.zeros(512, dtype=np.int16)))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            session._close_gate()
            session._generation += 1
            session._gate_open = reopen_capture
        finally:
            release.set()
        await task
        assert session._turn_id is None
        await session.close()
    asyncio.run(run())


def test_controller_defaults_and_target_are_separate(env, monkeypatch):
    _, create = env
    persisted = Mock()
    monkeypatch.setattr(conversations, 'persist_runtime_overrides', persisted)
    async def run():
        first, llm = create(1); other, _ = create(2)
        app = web.Application()
        app.router.add_get('/api/conversations', conversations.list_conversations)
        app.router.add_post('/api/conversations/defaults', conversations.save_defaults)
        app.router.add_post('/api/conversations/{sessionid}', conversations.update_conversation)
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/api/conversations/defaults', json={'history_max_messages': 40})
            assert response.status == 200
            assert first._conversation['history_max_messages'] == 20
            response = await client.post('/api/conversations/1', json={'history_max_messages': 8})
            assert response.status == 200
            assert llm._history.info()['max_messages'] == 8
            assert other._conversation['history_max_messages'] == 20
            response = await client.get('/api/conversations')
            body = (await response.json())['data']
            assert body['defaults']['history_max_messages'] == 40
            assert len(body['sessions']) == 2
            response = await client.post('/api/conversations/99', json={'locale': 'en-US'})
            assert response.status == 404
            response = await client.post('/api/conversations/defaults', json={'history_max_messages': True})
            assert response.status == 400
        await first.close(); await other.close()
    asyncio.run(run())


def test_defaults_save_failure_rolls_back(env, monkeypatch):
    config, _ = env
    monkeypatch.setattr(conversations, 'persist_runtime_overrides', Mock(side_effect=OSError('disk failure')))
    async def run():
        request = SimpleNamespace(json=AsyncMock(return_value={'locale': 'en-US'}))
        response = await conversations.save_defaults(request)
        assert response.status == 503
        assert config.conversation.locale == 'zh-TW'
    asyncio.run(run())


def test_clear_selected_session_stops_output_and_preserves_other_history(env):
    _, create = env
    async def run():
        first, llm = create(1); other, other_llm = create(2)
        first._capture_requested = False
        first._manual_pause = True
        llm.add_to_history('user', 'clear this')
        other_llm.add_to_history('user', 'keep this')
        app = web.Application()
        app.router.add_post('/api/conversations/{sessionid}/clear', conversations.clear_conversation)
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/api/conversations/1/clear')
            assert response.status == 200
            assert (await response.json())['data']['memory']['retained_messages'] == 0
            first.avatar.flush_talk.assert_called()
            assert not first._capture_requested and first._manual_pause
            assert other_llm.conversation_history == [{'role':'user','content':'keep this'}]
            response = await client.post('/api/conversations/99/clear')
            assert response.status == 404
        await first.close(); await other.close()
    asyncio.run(run())


def test_context_capacity_uses_deployed_server_not_training_size(monkeypatch):
    from src.llm import context_usage
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value
    monkeypatch.setattr(context_usage.requests, 'get', lambda *a, **k: Response({'default_generation_settings': {'n_ctx': 64}}))
    monkeypatch.setattr(context_usage.requests, 'post', lambda url, **k: Response({'prompt': 'template'} if url.endswith('apply-template') else {'tokens': list(range(40))}))
    result = measure_request('http://local-unique/v1', [{'role': 'system', 'content': 'rule'}, {'role': 'user', 'content': 'question'}], 30, local=True, model='test')
    assert result['capacity'] == 64
    assert result['input_tokens'] == 40
    assert not result['estimated']
    assert result['over_capacity']
    assert result['remaining_tokens'] == 0


def test_oversized_request_does_not_call_model_or_modify_history(monkeypatch):
    llm = OpenAILLM(config=Config(), api_key='test')
    llm.add_to_history('user', 'retain this')
    client = Mock()
    llm._client = client
    monkeypatch.setattr('src.llm.engines.openai.measure_request', lambda *a, **k: {'over_capacity': True, 'estimated': False})
    transaction = llm.begin_history_turn('oversized', turn_id='large')
    with pytest.raises(ContextCapacityError):
        list(llm.chat_stream('oversized', 'system', history_transaction=transaction))
    client.chat.completions.create.assert_not_called()
    assert llm.conversation_history == [{'role': 'user', 'content': 'retain this'}]
    assert not llm._history._pending


def test_english_session_overrides_language_preferences_without_rewriting_history(monkeypatch):
    config = Config()
    config.llm.assistant_profile.output_locale = 'en-US'
    config.llm.assistant_profile.system_prompt = '請一律使用中文。'
    engine = OpenAILLM(config=config, api_key='test')
    engine.add_to_history('user', '記住 NOVA42')
    prompts = []
    def stream(*args, **kwargs):
        prompts.append(kwargs['system_prompt'])
        yield '[[MODE:SIMPLE]]\n[[SPEECH]]\nThe code is NOVA42.\n[[END]]'
    monkeypatch.setattr(engine, 'chat_stream', stream)
    answer = engine.generate_response('What was the code?', stream_to_avatar=False)
    assert answer == 'The code is NOVA42.'
    assert 'Required session language override' in prompts[0]
    assert 'overrides language preferences' in prompts[0]
    assert engine.conversation_history[0]['content'] == '記住 NOVA42'


def test_request_language_hint_never_enters_retained_user_history():
    config = Config()
    config.llm.assistant_profile.output_locale = 'en-US'
    engine = OpenAILLM(config=config, api_key='test')
    engine.observe_context = False
    client = Mock()
    client.chat.completions.create.return_value = []
    engine._client = client
    transaction = engine.begin_history_turn('請問通關詞？', turn_id='en')
    list(engine.chat_stream('請問通關詞？', 'system', history_transaction=transaction))
    sent = client.chat.completions.create.call_args.kwargs['messages'][-1]['content']
    assert sent.endswith('[Session language: English. Answer in English.]')
    engine.commit_history_turn(transaction, assistant_text='NOVA42.', terminal_reason='completed')
    assert engine.conversation_history[0]['content'] == '請問通關詞？'


def test_english_token_spaces_survive_identity_normalization(monkeypatch):
    config = Config()
    config.llm.assistant_profile.output_locale = 'en-US'
    config.llm.assistant_profile.assistant_name = 'Test assistant'
    engine = OpenAILLM(config=config, api_key='test')
    def stream(*args, **kwargs):
        yield from ['[[MODE:SIMPLE]]\n[[SPEECH]]\n', 'I', ' can', ' help', ' you.', '\n[[END]]']
    monkeypatch.setattr(engine, 'chat_stream', stream)
    assert engine.generate_response('Hello', stream_to_avatar=False) == 'I can help you.'


def test_conversation_defaults_roundtrip(tmp_path, monkeypatch):
    from src.config.overrides import persist_runtime_overrides
    from src.config.loader import dict_to_config, load_yaml_config
    path = tmp_path / 'runtime.yaml'
    monkeypatch.setattr('src.config.overrides.RUNTIME_OVERRIDES_FILE', path)
    config = Config()
    config.conversation.locale = 'en-US'
    config.conversation.history_max_messages = 37
    config.conversation.voice_en_us = 'en-US-GuyNeural'
    persist_runtime_overrides(config)
    restored = dict_to_config(load_yaml_config(path))
    assert restored.conversation == config.conversation


def test_played_english_sentences_keep_word_spacing(env):
    _, create = env
    session, _ = create(1)
    session._played_fragments = ['Hello.', 'How are you?']
    assert session.played_assistant_text == 'Hello. How are you?'
    session._voice_executor.shutdown(wait=False)
