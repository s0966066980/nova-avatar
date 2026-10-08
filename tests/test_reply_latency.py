# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Readiness and content-free timing regressions for spoken replies."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import asyncio
import json

import numpy as np
import pytest

from src.config.schema import Config
from src.llm.base import response_token_budget
from src.llm.base import BaseLLM
from src.llm.router import ReplyMode
from src.llm.engines.openai import OpenAILLM
from src.llm.prewarm import prewarm_local_llm
from src.server.reply_streaming.metrics import TurnMetrics
from src.server.state import state
from src.vad.segmenter import VADSegmenter
from tests.test_vad import EnergyVAD, tone, silence


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
            yield "JSON]]"
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


@pytest.mark.parametrize("padding", [0, 100, 200])
def test_vad_endpoint_wait_is_independent_of_retained_audio_padding(padding):
    segmenter = VADSegmenter(
        EnergyVAD(sample_rate=16000, frame_ms=20),
        min_speech_ms=100, min_silence_ms=300, speech_pad_ms=padding,
    )
    segments = list(segmenter.process(np.concatenate((tone(400), silence(320)))))
    assert len(segments) == 1
    assert segments[0].endpoint_wait_ms == 300


def test_manual_vad_flush_does_not_fabricate_an_endpoint_wait():
    segmenter = VADSegmenter(EnergyVAD(), min_speech_ms=100)
    assert not list(segmenter.process(tone(400)))
    assert list(segmenter.flush())[0].endpoint_wait_ms is None


def test_timeline_stage_duration_keeps_missing_asr_unmeasured():
    metrics = TurnMetrics("fixture")
    metrics.record_stage_duration("vad_endpoint", 0.3)
    assert metrics.snapshot()["stage_seconds"]["vad_endpoint"] == 0.3
    assert metrics.snapshot()["stage_seconds"]["asr"] is None
    for value in [float("nan"), float("inf"), -1]:
        with pytest.raises(ValueError):
            metrics.record_stage_duration("vad_endpoint", value)


def test_failed_reply_prewarm_never_announces_ready_or_accepts_a_peer():
    from src.server.routes.health import health_check
    from src.server.routes.webrtc import offer

    async def run():
        with patch.object(state, "server_ready", True), patch.object(
            state, "reply_prewarm_ready", False
        ):
            response = await health_check(None)
            assert json.loads(response.text)["ready"] is False
            assert (await offer(None)).status == 503

    asyncio.run(run())


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
