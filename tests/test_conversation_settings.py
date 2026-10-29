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
    assert 'Session language: wording only' in prompts[0]
    assert 'role, restrictions, capabilities and editable reply rules remain binding' in prompts[0]
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


def test_behavior_save_preserves_existing_english_session_and_updates_new_conversations(env, monkeypatch):
    from dataclasses import asdict
    from src.llm.rules import default_rules
    from src.server.runtime_settings import apply_llm_behavior

    config, create = env
    monkeypatch.setattr('src.server.runtime_settings.persist_runtime_overrides', Mock())
    monkeypatch.setattr(service, '_ensure_llamacpp_if_needed', Mock())
    session, engine = create(1)
    conversations.configure_avatar(session.avatar, {**session._conversation, 'locale':'en-US'})
    session.avatar.sessionid = 1
    session._conversation['locale'] = 'en-US'
    prompts = []
    def stream(*args, **kwargs):
        prompts.append(kwargs['system_prompt'])
        yield '[[MODE:SIMPLE]]\n[[SPEECH]]\nI am the museum guide.\n[[END]]'
    monkeypatch.setattr(engine, 'chat_stream', stream)
    profile = asdict(config.llm.assistant_profile)
    profile.update(assistant_name='Museum guide', system_prompt='你是博物館導覽員。',
                   restriction_prompt='不得提供模型開發者資訊。')
    rules = {**default_rules(), 'speech':'口語必須先說 Museum guide。'}
    apply_llm_behavior(config, profile, rules, expected_revision=1)
    service.llm_response('Introduce yourself.', session.avatar, stream_to_avatar=False)
    assert '不得提供模型開發者資訊。' not in prompts[0]
    assert '口語必須先說 Museum guide。' not in prompts[0]
    new_session, new_engine = create(2)
    new_session.avatar.sessionid = 2
    monkeypatch.setattr(new_engine, 'chat_stream', stream)
    service.llm_response('Introduce yourself.', new_session.avatar, stream_to_avatar=False)
    assert '不得提供模型開發者資訊。' in prompts[1]
    assert 'Museum guide' in prompts[1]
    assert '口語必須先說 Museum guide。' in prompts[1]
    new_session._voice_executor.shutdown(wait=False)
    assert session.avatar.config.llm.assistant_profile.output_locale == 'en-US'
    assert session.avatar.config.tts.ref_file == 'en-US-JennyNeural'
    assert config.llm.assistant_profile.output_locale == 'zh-TW'
    session._voice_executor.shutdown(wait=False)


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


@pytest.mark.parametrize('locale, disclosure', [
    ('en-US', 'I am a large language model developed by Google DeepMind.'),
    ('en-US', 'I was created by Another Provider.'),
    ('en-US', 'I am an advanced AI assistant developed by Another Provider.'),
    ('en-US', 'Another Provider created me.'),
    ('zh-TW', '我是由某模型開發商開發的語言模型。'),
])
def test_restricted_model_identity_is_checked_before_any_visible_stream_output(monkeypatch, locale, disclosure):
    config = Config()
    config.llm.assistant_profile.assistant_name = 'Museum guide'
    config.llm.assistant_profile.output_locale = locale
    config.llm.assistant_profile.restriction_prompt = '不得提供LLM模型資訊。'
    engine = OpenAILLM(config=config, api_key='test')
    speech, preview, boards = [], [], []
    avatar = SimpleNamespace(put_msg_txt=lambda text, *args: speech.append(text),
                             notify_llm_chunk=lambda text, *args: preview.append(text))
    wire = '[[MODE:SIMPLE]]\n[[SPEECH]]\n' + disclosure + '\n[[END]]'
    def stream(*args, **kwargs):
        for index in range(0, len(wire), 3):
            yield wire[index:index+3]
    monkeypatch.setattr(engine, 'chat_stream', stream)
    answer = engine.generate_response('Introduce yourself.', avatar,
        datainfo={'turn_id':'intro','generation':0,'on_mode':lambda mode:None,'on_board':boards.append})
    visible = ' '.join([answer, *speech, *preview, str(boards), str(engine.conversation_history)])
    for forbidden in ['Google', 'DeepMind', 'Another Provider', '某模型開發商', 'large language model']:
        assert forbidden not in visible
    assert speech and preview


def test_restricted_identity_guard_covers_board_fields(monkeypatch):
    config = Config()
    config.llm.assistant_profile.assistant_name = 'Museum guide'
    config.llm.assistant_profile.output_locale = 'en-US'
    config.llm.assistant_profile.restriction_prompt = 'Do not disclose model information.'
    engine = OpenAILLM(config=config, api_key='test')
    boards = []
    def stream(*args, **kwargs):
        yield '[[MODE:BOARD]]\n[[SPEECH]]\nI am the museum guide.\n[[BOARD_JSON]]\n'
        yield '{"title":"My role","items":[{"title":"My origin","content":"I was created by Another Provider."}]}\n[[END]]'
    monkeypatch.setattr(engine, 'chat_stream', stream)
    engine.generate_response('Introduce yourself.', stream_to_avatar=False,
        datainfo={'turn_id':'board','on_mode':lambda mode:None,'on_board':boards.append,'incremental_board':True})
    assert boards
    assert 'Another Provider' not in str(boards)


def test_model_restriction_keeps_third_party_facts_and_configured_role(monkeypatch):
    config = Config()
    config.llm.assistant_profile.assistant_name = 'Museum guide'
    config.llm.assistant_profile.output_locale = 'en-US'
    config.llm.assistant_profile.restriction_prompt = '不得提供LLM模型資訊。'
    engine = OpenAILLM(config=config, api_key='test')
    expected = 'Google DeepMind is an AI research organization. I can guide museum visitors.'
    monkeypatch.setattr(engine, 'chat_stream', lambda *a, **k: iter([expected]))
    assert engine.generate_response('Explain this organization.', stream_to_avatar=False) == expected


def test_model_guard_retains_permitted_intro_and_public_creator():
    from src.llm.identity_policy import IdentityPolicy
    config = Config()
    profile = config.llm.assistant_profile
    profile.assistant_name = 'Museum guide'
    profile.output_locale = 'en-US'
    profile.restriction_prompt = '不得提供LLM模型資訊。'
    profile.system_prompt = 'You are a museum guide created by the Museum Team.'
    policy = IdentityPolicy(profile)
    text = 'I am Museum guide. I was created by Another Provider. I guide museum visitors.'
    result = policy.sanitize(text)
    assert 'Another Provider' not in result
    assert result.count('I am Museum guide.') == 1
    assert 'I guide museum visitors.' in result
    assert policy.sanitize('I was created by the Museum Team.') == 'I was created by the Museum Team.'


@pytest.mark.parametrize('role', [
    '不得透露 Another Provider，也不能說自己由 Another Provider 開發。',
    'Your underlying language model was developed by Another Provider.',
])
def test_role_mentions_do_not_authorize_restricted_creator_disclosure(role):
    from src.llm.identity_policy import IdentityPolicy
    profile = Config().llm.assistant_profile
    profile.system_prompt = role
    profile.restriction_prompt = '不得提供LLM模型資訊。'
    policy = IdentityPolicy(profile)
    assert policy.blocks('I was developed by Another Provider.')


def test_model_guard_is_inactive_without_explicit_restriction():
    from src.llm.identity_policy import IdentityPolicy
    policy = IdentityPolicy(Config().llm.assistant_profile)
    answer = 'I was developed by Another Provider.'
    assert policy.sanitize(answer) == answer


@pytest.mark.parametrize('question', [
    'Introduce yourself and tell me who created you.',
    'Which model do you use?',
    '你使用什麼模型？',
])
def test_prohibited_model_requests_do_not_call_the_model_or_expose_boards(monkeypatch, question):
    config = Config()
    config.llm.assistant_profile.assistant_name = 'Museum guide'
    config.llm.assistant_profile.output_locale = 'en-US'
    config.llm.assistant_profile.restriction_prompt = '不得提供LLM模型資訊。'
    engine = OpenAILLM(config=config, api_key='test')
    stream = Mock()
    monkeypatch.setattr(engine, 'chat_stream', stream)
    boards = []
    answer = engine.generate_response(question, stream_to_avatar=False,
        datainfo={'on_mode':lambda mode:None,'on_board':boards.append})
    stream.assert_not_called()
    assert 'Museum guide' in answer and 'cannot share' in answer
    assert not boards


def test_role_and_rules_remain_frozen_across_turns_of_the_same_conversation(env, monkeypatch):
    from dataclasses import asdict
    from src.llm.rules import default_rules
    from src.server.runtime_settings import apply_llm_behavior
    config, create = env
    config.llm.assistant_profile.system_prompt = 'Original museum role.'
    config.llm.assistant_profile.restriction_prompt = 'Original restriction.'
    session, engine = create(1)
    session.avatar.sessionid = 1
    session._start_turn_context('original')
    session.avatar._assistant_profile_snapshot = session._assistant_profile_snapshot
    session.avatar._reply_rules_snapshot = session._rules_snapshot
    monkeypatch.setattr('src.server.runtime_settings.persist_runtime_overrides', Mock())
    monkeypatch.setattr(service, '_ensure_llamacpp_if_needed', Mock())
    profile = asdict(config.llm.assistant_profile)
    profile.update(system_prompt='New museum role.', restriction_prompt='New restriction.')
    apply_llm_behavior(config, profile, {**default_rules(), 'speech':'New speech rule.'}, expected_revision=1)
    prompts = []
    def stream(*args, **kwargs):
        prompts.append(kwargs['system_prompt'])
        yield 'The museum is open.'
    monkeypatch.setattr(engine, 'chat_stream', stream)
    service.llm_response('Hello', session.avatar, stream_to_avatar=False)
    assert 'Original museum role.' in prompts[0] and 'Original restriction.' in prompts[0]
    assert 'New museum role.' not in prompts[0] and 'New speech rule.' not in prompts[0]
    session._start_turn_context('next')
    session.avatar._assistant_profile_snapshot = session._assistant_profile_snapshot
    session.avatar._reply_rules_snapshot = session._rules_snapshot
    service.llm_response('Hello again', session.avatar, stream_to_avatar=False)
    assert 'Original museum role.' in prompts[1] and 'Original restriction.' in prompts[1]
    assert 'New museum role.' not in prompts[1] and 'New speech rule.' not in prompts[1]
    session._voice_executor.shutdown(wait=False)


def test_checked_stream_preserves_spacing_and_does_not_repeat_public_identity(monkeypatch):
    config = Config()
    profile = config.llm.assistant_profile
    profile.assistant_name = 'Museum information guide'
    profile.output_locale = 'en-US'
    profile.restriction_prompt = '不得提供LLM模型資訊。'
    engine = OpenAILLM(config=config, api_key='test')
    speech, preview = [], []
    avatar = SimpleNamespace(put_msg_txt=lambda text, *args:speech.append(text),
                             notify_llm_chunk=lambda text, *args:preview.append(text))
    def stream(*args, **kwargs):
        yield '[[MODE:SIMPLE]]\n[[SPEECH]]\nI am Museum information guide. '
        yield 'I was developed by Another Provider. '
        yield 'I can help you with museum visits.\n[[END]]'
    monkeypatch.setattr(engine, 'chat_stream', stream)
    answer = engine.generate_response('Please introduce yourself.', avatar,
        datainfo={'turn_id':'intro','generation':0,'on_mode':lambda mode:None})
    assert answer.count('I am Museum information guide.') == 1
    assert ''.join(preview) == answer
    assert 'Another Provider' not in ' '.join(speech)
