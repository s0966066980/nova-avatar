# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""First playable speech must not wait for board JSON or a cold client."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from src.config.schema import Config
from src.llm.base import BaseLLM, response_token_budget
from src.llm.router import ReplyMode
from src.llm.engines.openai import OpenAILLM
from src.llm.prewarm import prewarm_local_llm


def test_local_prewarm_finishes_the_disposable_completion_before_readiness():
    config = Config()
    config.llm.provider = "llamacpp"
    consumed = []

    class WarmCompletion(Completion):
        def __iter__(self):
            for text in ('[[SPEECH]]', '準備完成。'):
                consumed.append(text)
                yield SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content=text), finish_reason=None,
                )])

    completion = WarmCompletion()
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = completion
    with patch('src.llm.engines.openai.OpenAI', return_value=client):
        assert prewarm_local_llm(config)
    assert consumed == ['[[SPEECH]]', '準備完成。'], 'readiness interrupted the prompt warmup'
    assert completion.closed


def test_startup_keeps_the_edge_prewarm_result():
    from src.server.app import _start_edge_tts_prewarm, _await_edge_tts_prewarm

    for ready in (False, True):
        with patch('src.tts.engines.edge.prewarm_edge_tts', return_value=ready):
            worker = _start_edge_tts_prewarm(Config())
            assert _await_edge_tts_prewarm(worker) is ready


def test_disabled_prewarm_does_not_contact_edge():
    from src.server.app import _start_edge_tts_prewarm
    config = Config()
    config.app.prewarm = False
    with patch('src.tts.engines.edge.prewarm_edge_tts') as warm:
        assert _start_edge_tts_prewarm(config) is None
    warm.assert_not_called()


def test_health_exposes_incomplete_prewarm_without_disabling_runtime_recovery():
    import asyncio
    import json
    from src.server.routes.health import health_check
    from src.server.state import state

    status = {'enabled': True, 'edge_tts': False, 'local_llm': True}
    with (
        patch.object(state, 'server_ready', True),
        patch.object(state, 'prewarm_status', status),
    ):
        payload = json.loads(asyncio.run(health_check(None)).text)
    assert payload['ready'] is True
    assert payload['prewarm'] == status


def test_listening_preparation_warms_stt_inference_once_without_a_turn():
    from src.asr.base import BaseASR
    from src.server.voice_session import VoiceTurnSession
    from tests.test_voice_session import FakeAvatar

    inferences = []

    class Recognizer(BaseASR):
        def _load_model(self):
            pass

        def _transcribe(self, audio_path):
            inferences.append(audio_path)
            return {'text': '', 'language': 'zh'}

    config = Config()
    engine = Recognizer(config)
    avatar = FakeAvatar()
    session = VoiceTurnSession(7, config, avatar)
    with (
        patch('src.server.voice_session.create_segmenter', return_value=MagicMock()),
        patch('src.server.voice_session.get_asr_engine', return_value=engine),
    ):
        session._prepare_sync()
        session._prepare_sync()
    assert len(inferences) == 1, 'STT was loaded but first-utterance inference remained cold'
    assert not avatar.messages
    assert session._turn_id is None


def test_failed_stt_warmup_can_retry_and_removes_temporary_audio():
    from pathlib import Path
    from src.asr.base import BaseASR

    paths = []

    class Recognizer(BaseASR):
        def _load_model(self):
            pass

        def _transcribe(self, audio_path):
            paths.append(Path(audio_path))
            if len(paths) == 1:
                raise RuntimeError('transient')
            return {'text': ''}

    engine = Recognizer(Config())
    with pytest.raises(RuntimeError):
        engine.prewarm()
    assert not engine._prewarmed
    engine.prewarm()
    engine.prewarm()
    assert len(paths) == 2
    assert all(not path.exists() for path in paths)


def test_edge_prewarm_retries_rate_limit_within_one_deadline():
    import aiohttp
    from unittest.mock import AsyncMock
    from src.tts.engines.edge import prewarm_edge_tts

    limited = aiohttp.WSServerHandshakeError(MagicMock(), (), status=429)
    warm = AsyncMock(side_effect=[limited, True])
    sleep = AsyncMock()
    with (
        patch('src.tts.engines.edge._prewarm_edge_tts', warm),
        patch('src.tts.engines.edge.asyncio.sleep', sleep),
    ):
        assert prewarm_edge_tts('zh-TW-HsiaoChenNeural', timeout_seconds=1)
    assert warm.await_count == 2
    assert 0.2 <= sleep.await_args.args[0] <= 0.4


def test_edge_prewarm_swaps_hosts_once_for_each_rejected_attempt():
    import aiohttp
    from unittest.mock import AsyncMock
    from src.tts.engines.edge import prewarm_edge_tts

    rejected = aiohttp.WSServerHandshakeError(MagicMock(), (), status=403)
    with (
        patch('src.tts.engines.edge._prewarm_edge_tts', AsyncMock(side_effect=rejected)),
        patch('src.tts.engines.edge.asyncio.sleep', AsyncMock()),
        patch('src.tts.engines.edge.edge_endpoint.note_failure') as swap,
    ):
        assert not prewarm_edge_tts('zh-TW-HsiaoChenNeural', timeout_seconds=1)
    assert swap.call_count == 2


def test_process_prewarm_switch_is_explicit_and_does_not_change_saved_config(monkeypatch):
    from src.config.loader import load_config
    with patch('src.config.overrides.load_runtime_overrides', return_value={}) as load:
        monkeypatch.setenv('NOVA_AVATAR_PREWARM_ENABLED', '0')
        assert load_config().app.prewarm is False
        monkeypatch.setenv('NOVA_AVATAR_PREWARM_ENABLED', '1')
        assert load_config().app.prewarm is True
        monkeypatch.setenv('NOVA_AVATAR_PREWARM_ENABLED', 'invalid')
        with pytest.raises(ValueError, match='NOVA_AVATAR_PREWARM_ENABLED'):
            load_config()
    assert load.call_count == 3


def _benchmark_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'scripts/benchmark-prewarm.py'
    spec = importlib.util.spec_from_file_location('nova_prewarm_benchmark', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cold_benchmark_leaves_existing_services_untouched():
    import asyncio
    from unittest.mock import AsyncMock

    benchmark = _benchmark_module()
    config = Config()
    config.llm.provider = 'llamacpp'
    args = SimpleNamespace(config='unused', base_url='https://localhost:8010')
    with (
        patch.object(benchmark, 'load_config', return_value=config),
        patch.object(benchmark, 'health', AsyncMock(return_value={'ready': True})),
        patch.object(benchmark.subprocess, 'Popen') as start,
    ):
        with pytest.raises(RuntimeError, match='already running'):
            asyncio.run(benchmark.run(args))
    start.assert_not_called()


def test_cold_benchmark_closes_its_peer_and_backend_if_connection_fails():
    import asyncio
    from unittest.mock import AsyncMock

    benchmark = _benchmark_module()
    process = MagicMock()
    process.poll.return_value = None
    peer = MagicMock()
    peer.connect = AsyncMock(side_effect=RuntimeError('connection failed'))
    peer.close = AsyncMock()
    args = SimpleNamespace(config='unused', client_role='console')
    with (
        patch.object(benchmark, 'health', AsyncMock(return_value={'ready': True, 'model_ready': True})),
        patch.object(benchmark, 'BenchmarkPeer', return_value=peer),
        patch.object(benchmark.subprocess, 'Popen', return_value=process),
    ):
        with pytest.raises(RuntimeError, match='connection failed'):
            asyncio.run(benchmark.trial(None, args, 'https://localhost:8010', None, True))
    peer.close.assert_awaited_once()
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=20)

class Completion:
    def __init__(self):
        self.closed = False

    def __iter__(self):
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="回答。"), finish_reason="stop",
        )])

    def close(self):
        self.closed = True


def test_new_engine_uses_the_same_budget_as_runtime_length_updates():
    config = Config()
    config.llm.response_max_chars = 200
    engine = OpenAILLM(config, api_key="test")
    client = MagicMock()
    completion = Completion()
    client.chat.completions.create.return_value = completion
    engine._client = client
    assert list(engine.chat_stream("問題")) == ["回答。"]
    assert client.chat.completions.create.call_args.kwargs["max_tokens"] == response_token_budget(200)
    assert completion.closed


def test_cancelled_llm_generator_closes_its_http_stream():
    engine = OpenAILLM(Config(), api_key="test")
    engine._client = MagicMock()
    completion = Completion()
    engine._client.chat.completions.create.return_value = completion
    chunks = engine.chat_stream("問題")
    assert next(chunks) == "回答。"
    chunks.close()
    assert completion.closed


def test_complete_speech_channel_is_playable_before_board_generation_finishes():
    config = Config()
    config.reply_streaming.enabled = True
    spoken = []
    avatar = SimpleNamespace(put_msg_txt=lambda text, info: spoken.append(text))

    class BoardLLM(BaseLLM):
        def chat_stream(self, message, system_prompt=None, **kwargs):
            yield "[[MODE:BOARD]][[SPEECH]]規律運動有助維持健康"
            assert not spoken  # An unfinished phrase must stay buffered.
            yield "[[BOARD_"
            assert not spoken  # Neither a partial marker nor its text is speech.
            yield "JSON]"
            assert not spoken  # One closing bracket is still an incomplete tag.
            yield "]"
            assert spoken == ["規律運動有助維持健康"], "Complete speech waited for board JSON"
            yield '{"title":"運動","items":[{"title":"健康","content":"保持規律"}]}[[END]]'

    llm = BoardLLM(config, parent=avatar)
    llm.generate_response(
        "運動有什麼好處", avatar, reply_mode=ReplyMode.AUTO,
        datainfo={"turn_id": "test-turn", "generation": 1},
    )
    assert spoken == ["規律運動有助維持健康"]



def test_local_prewarm_uses_the_current_profile_without_session_history():
    config = Config()
    config.llm.provider = "llamacpp"
    config.llm.assistant_profile.system_prompt = "只使用這個測試設定。"
    client = MagicMock()
    client.with_options.return_value = client
    client.chat.completions.create.return_value = Completion()
    with patch("src.llm.engines.openai.OpenAI", return_value=client):
        assert prewarm_local_llm(config, timeout_seconds=3)
    request = client.chat.completions.create.call_args.kwargs
    assert request["max_tokens"] == 16
    assert len(request["messages"]) == 2
    assert "只使用這個測試設定。" in request["messages"][0]["content"]
    assert "[[SPEECH]]" in request["messages"][0]["content"]
    client.with_options.assert_called_once_with(timeout=3, max_retries=0)
    client.close.assert_called_once()


def test_prewarm_skips_paid_remote_providers_and_reports_local_failure():
    config = Config()
    config.llm.provider = "openai"
    with patch("src.llm.prewarm.OpenAILLM") as constructor:
        assert prewarm_local_llm(config)
        constructor.assert_not_called()
    config.llm.provider = "llamacpp"
    with patch("src.llm.prewarm.OpenAILLM", side_effect=RuntimeError("failed")):
        assert not prewarm_local_llm(config)


def test_prewarm_deadline_closes_stream_and_client_even_if_content_arrives():
    config = Config()
    config.llm.provider = "llamacpp"
    client = MagicMock()
    client.with_options.return_value = client
    completion = Completion()
    client.chat.completions.create.return_value = completion
    with (
        patch("src.llm.engines.openai.OpenAI", return_value=client),
        patch("src.llm.prewarm.time.monotonic", side_effect=[0, 4]),
    ):
        assert not prewarm_local_llm(config, timeout_seconds=3)
    assert completion.closed
    client.close.assert_called_once()


def test_edge_prewarm_requires_decoded_pcm_when_requested():
    from src.tts.engines.edge import prewarm_edge_tts
    from tests.test_edge_tts_worker import _mp3_fixture

    for payload, expected in [(_mp3_fixture(), True), (b"not audio", False)]:
        class Communicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_: Communicate(),
        ):
            assert prewarm_edge_tts(
                "zh-TW-YunJheNeural", decode_pcm=True, timeout_seconds=1,
            ) is expected
