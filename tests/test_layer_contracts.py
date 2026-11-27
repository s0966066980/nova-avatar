# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Each layer's adapter honours its ``nova_contracts`` protocol, using the fake engines.

These run on a machine with no GPU and no model weights.
"""
import threading
import time
from types import SimpleNamespace

from nova_contracts import (
    HandoffRequest,
    ReplyDone,
    ReplyModeEvent,
    ReplyRequest,
    SpokenTextDelta,
    SynthesizeRequest,
)

from src.asr.adapter import SttAdapter
from src.asr.engines.fake import FAKE_TRANSCRIPT, FakeASR
from src.avatars.fake import FakeAvatar
from src.config.schema import Config
from src.llm.adapter import LlmAdapter
from src.llm.engines.fake import FAKE_REPLY, FakeLLM
from src.server.speech import tts_speech_factory
from src.tts.adapter import TtsAdapter
from src.tts.base import State


def fake_config():
    config = Config()
    config.tts.type = "fake"
    config.llm.provider = "fake"
    return config


# ---- STT ---------------------------------------------------------------------
def test_stt_returns_the_contract_result():
    adapter = SttAdapter(FakeASR(Config()))
    adapter.prewarm()
    adapter.set_language("zh")

    result = adapter.transcribe(b"not really audio", language="auto")

    assert result.text == FAKE_TRANSCRIPT
    assert result.confidence == 1.0
    assert result.language == "auto"


# ---- TTS ---------------------------------------------------------------------
def test_tts_streams_pcm_of_the_requested_length_in_20ms_frames():
    adapter = TtsAdapter(fake_config())

    chunks = list(adapter.synthesize(SynthesizeRequest(text="你好")))

    assert all(len(chunk) == 640 for chunk in chunks)  # 320 samples * int16
    assert len(chunks) == 25  # 0.5 s at 50 fps
    assert not any(any(chunk) for chunk in chunks)  # silence


def test_tts_serves_one_fragment_after_another():
    adapter = TtsAdapter(fake_config())

    first = list(adapter.synthesize(SynthesizeRequest(text="一")))
    second = list(adapter.synthesize(SynthesizeRequest(text="二", turn_id="t", generation=1)))

    assert len(first) == len(second) == 25


def test_closing_a_synthesis_early_cancels_the_engine():
    adapter = TtsAdapter(fake_config())
    stream = adapter.synthesize(SynthesizeRequest(text="你好"))

    next(stream)
    stream.close()

    assert adapter._engine.state == State.PAUSE


# ---- LLM ---------------------------------------------------------------------
def test_llm_reply_is_mode_then_spoken_deltas_then_done():
    config = fake_config()
    adapter = LlmAdapter(config, FakeLLM(config))

    events = list(adapter.stream_reply(ReplyRequest(message="嗨", turn_id="t1", generation=0)))

    assert isinstance(events[-1], ReplyDone) and events[-1].text == FAKE_REPLY
    spoken = [event.text for event in events if isinstance(event, SpokenTextDelta)]
    assert "".join(spoken).strip() == FAKE_REPLY
    modes = [index for index, event in enumerate(events) if isinstance(event, ReplyModeEvent)]
    assert modes and modes[0] < events.index(next(e for e in events if isinstance(e, SpokenTextDelta)))


def test_closing_a_reply_stops_generation():
    config = fake_config()
    produced = []
    finished = threading.Event()

    class Endless(FakeLLM):
        def chat_stream(self, message, system_prompt=None, **kwargs):
            try:
                wire = "[[MODE:SIMPLE]]\n[[SPEECH]]\n" + "好。" * 500
                for start in range(0, len(wire), 2):
                    produced.append(start)
                    time.sleep(0.002)
                    yield wire[start:start + 2]
            finally:
                finished.set()

    stream = LlmAdapter(config, Endless(config)).stream_reply(
        ReplyRequest(message="嗨", turn_id="t1", generation=0))
    next(event for event in stream if isinstance(event, SpokenTextDelta))
    stream.close()

    assert finished.wait(5)
    assert len(produced) < 500


def test_llm_handoff_returns_the_contract_decision():
    config = fake_config()
    reply = '{"target": "a", "clarification": "", "context": ""}'
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))]))),
        close=lambda: None,
    )

    decision = LlmAdapter(config, client_factory=lambda **_: client).route(HandoffRequest(
        members=[{"id": "a", "name": "A", "main": True}], current_id="a", text="嗨"))

    assert decision.target == "a" and decision.decided_by == "model"


# ---- avatar rendering --------------------------------------------------------
def test_renderer_forwards_text_to_its_speech_source_and_reports_speaking():
    config = fake_config()
    avatar = FakeAvatar(config, tts_speech_factory)

    avatar.put_msg_txt("你好", {"turn_id": "t"})
    assert avatar.tts.has_pending_work()

    avatar.put_audio_frame([0.0] * 320, {"turn_id": "t"})
    assert avatar.is_speaking() and len(avatar.audio_frames) == 1

    avatar.flush_talk()
    assert not avatar.is_speaking() and not avatar.tts.has_pending_work()
    assert (avatar.video_frame() == avatar.video_frame()).all()


# ---- the console never offers a fake engine ----------------------------------
def test_fake_engines_are_not_offered_in_the_console():
    from src.server.runtime_settings import STT_ENGINE_META
    from src.tts.voice_library import ENGLISH_TTS_ENGINES, TTS_ENGINES

    assert "fake" not in STT_ENGINE_META
    assert "fake" not in TTS_ENGINES and "fake" not in ENGLISH_TTS_ENGINES
