# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""LFM's production request and launcher must agree on its thinking envelope."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.config.schema import Config
from src.llm.engines.openai import OpenAILLM
from src.llm.router import ReplyMode
from src.llm.prewarm import prewarm_local_llm


@pytest.mark.parametrize('model', ['Qwen3.5-2B-UD-Q4_K_XL', 'another-local-model'])
def test_model_switch_keeps_the_same_complete_reply_contract(model):
    config = Config()
    config.llm.provider = 'llamacpp'
    config.llm.board.max_items = 12
    config.llm.extra_body = {'grammar': 'root ::= "incompatible"'}
    config.llm.reply_rules.activation = '只有明確要求看板時才使用看板。'
    engine = OpenAILLM(config, api_key='test', model=model)
    engine._client = MagicMock()
    engine._client.chat.completions.create.return_value = []
    engine.generate_response('你好', stream_to_avatar=False, reply_mode=ReplyMode.AUTO)
    request = engine._client.chat.completions.create.call_args.kwargs
    prompt = request['messages'][0]['content']
    assert '只有明確要求看板時才使用看板。' in prompt
    assert prompt.count(config.llm.reply_rules.activation) == 1
    assert prompt.index(config.llm.reply_rules.activation) > prompt.index('【口語與看板分工】')
    assert '一個流程裡的多個步驟' not in prompt  # Policy belongs to editable Rules.
    assert '[[MODE:SIMPLE]]\n[[SPEECH]]\n' in prompt
    assert '自然、簡短的回答。\n[[END]]' in prompt
    grammar = request['extra_body']['grammar']
    assert '(simple | board)' in grammar
    assert '{0,11}' in grammar
    assert 'incompatible' not in grammar
    assert '</think>' not in grammar


@pytest.mark.parametrize('provider,model,constrained', [
    ('llamacpp', 'LFM2.5-2.6B-Q4_K_M.gguf', True),
    ('llamacpp', 'LFM2.5-2.6B-Q4_K_M', True),
    ('llamacpp', 'Qwen3.5-4B-UD-Q4_K_XL', True),
    ('openai', 'LFM2.5-2.6B-Q4_K_M', False),
])
def test_auto_request_preserves_editable_rules_and_constrains_all_local_models(provider, model, constrained):
    config = Config()
    config.llm.provider = provider
    config.llm.model = model
    config.llm.assistant_profile.system_prompt = '只能根據使用者提供的資訊回答。'
    config.llm.reply_rules.activation = '比較兩個選項時才使用看板。'
    engine = OpenAILLM(config, api_key='test', model=model)
    client = MagicMock()
    stream = MagicMock()
    stream.__iter__.return_value = iter([SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content='[[MODE:SIMPLE]][[SPEECH]]您好。[[END]]'),
        finish_reason='stop',
    )])])
    client.chat.completions.create.return_value = stream
    engine._client = client
    assert engine.generate_response('你好', stream_to_avatar=False, reply_mode=ReplyMode.AUTO) == '您好。'
    request = client.chat.completions.create.call_args.kwargs
    assert '比較兩個選項時才使用看板。' in request['messages'][0]['content']
    extra = request.get('extra_body') or {}
    if constrained:
        assert 'root ::=' in extra['grammar']
        assert ('</think>' in extra['grammar']) == model.startswith('LFM')
        if model.startswith('LFM'):
            assert extra['repeat_penalty'] == 1.1
        assert request['temperature'] == 0.0
    else:
        assert 'grammar' not in extra
        assert request['temperature'] == 0.6
    stream.close.assert_called_once()


def test_lfm_launch_retains_a_bounded_thinking_phase(tmp_path, monkeypatch):
    import src.llm.llamacpp as launcher
    model = tmp_path / 'LFM2.5-2.6B-Q4_K_M.gguf'
    model.write_bytes(b'GGUF')
    binary = tmp_path / 'llama-server'
    binary.touch()
    monkeypatch.setattr(launcher, 'get_project_root', lambda: tmp_path)
    monkeypatch.setattr(launcher, 'resolve_gguf', lambda *_: model)
    monkeypatch.setattr(launcher, 'find_llama_server', lambda: binary)
    monkeypatch.setattr(launcher, 'server_status', lambda *_: {'running': False})
    monkeypatch.setattr(launcher, '_stop_owned_server', lambda: None)
    monkeypatch.setattr(launcher, '_wait_until_ready', lambda *a, **kw: None)
    monkeypatch.setattr(launcher, 'has_cuda_backend', lambda *_: False)
    monkeypatch.setattr(launcher, 'gguf_block_count', lambda *_: 30)
    popen = MagicMock()
    monkeypatch.setattr(launcher.subprocess, 'Popen', popen)
    monkeypatch.setattr(launcher, '_server_proc', None)
    monkeypatch.setattr(launcher, '_loaded_model', '')
    launcher.ensure_server(model.stem)
    command = popen.call_args.args[0]
    assert command[command.index('--reasoning') + 1] == 'on'
    assert command[command.index('--reasoning-budget') + 1] == '64'


def test_lfm_prewarm_reaches_visible_content_after_the_thinking_budget(monkeypatch):
    config = Config()
    config.llm.provider = 'llamacpp'
    config.llm.model = 'LFM2.5-2.6B-Q4_K_M'
    client = MagicMock()
    client.with_options.return_value = client
    def completion(**request):
        stream = MagicMock()
        # A short request ends entirely in reasoning_content, which the
        # production engine correctly keeps out of speech.
        visible = request['max_tokens'] > 80
        stream.__iter__.return_value = iter([SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content='[[MODE:SIMPLE]]' if visible else None,
                                  reasoning_content='internal reasoning'),
            finish_reason='stop',
        )])])
        return stream
    client.chat.completions.create.side_effect = completion
    monkeypatch.setattr('src.llm.engines.openai.OpenAI', lambda **kw: client)
    assert prewarm_local_llm(config)
    request = client.chat.completions.create.call_args.kwargs
    assert request['max_tokens'] == 96
    assert len(request['messages']) == 2
    client.close.assert_called_once()


def test_reasoning_only_completion_produces_audible_recovery_without_leaking_history():
    config = Config()
    config.llm.provider = 'llamacpp'
    engine = OpenAILLM(config, api_key='test', model='LFM2.5-2.6B-Q4_K_M')
    client = MagicMock()
    stream = MagicMock()
    stream.__iter__.return_value = iter([SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=None, reasoning_content='private thinking'),
        finish_reason='length',
    )])])
    client.chat.completions.create.return_value = stream
    engine._client = client
    spoken = []
    avatar = SimpleNamespace(put_msg_txt=lambda text, info: spoken.append(text))
    from src.llm.response_protocol import FORMAT_RECOVERY_MESSAGE
    result = engine.generate_response('你好', avatar, reply_mode=ReplyMode.AUTO)
    assert result == FORMAT_RECOVERY_MESSAGE
    assert ''.join(spoken) == FORMAT_RECOVERY_MESSAGE
    assert 'private thinking' not in repr(engine.conversation_history)
    stream.close.assert_called_once()
