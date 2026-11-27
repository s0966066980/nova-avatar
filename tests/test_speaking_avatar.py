# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core owns TTS and hands its PCM to the avatar renderer (ADR 0027)."""

import numpy as np

from nova_contracts.tts import TtsVoice
from src.config.schema import Config
from src.server.speaking_avatar import SpeakingAvatar


class FakeRenderer:
    def __init__(self):
        self.config = Config()
        self.chunk = 320
        self.frames = []
        self.flushes = []
        self.accept = True

    def put_audio_frame(self, samples, eventpoint):
        self.frames.append((samples, dict(eventpoint)))
        return self.accept


class FakeTTS:
    """A SpeechChannel that records what the core asks of it."""

    def __init__(self, voice, sink):
        self.voice = voice
        self.sink = sink
        self.messages = []
        self.flushes = 0

    def set_voice(self, voice):
        self.voice = voice

    def speak(self, text, eventpoint):
        self.messages.append((text, eventpoint))

    def flush(self):
        self.flushes += 1


class FakeRuntime:
    def __init__(self, channel=FakeTTS):
        self.channel = channel
        self.created = []

    def open_channel(self, voice, sink):
        self.created.append(self.channel(voice, sink))
        return self.created[-1]


def speaking(renderer=None):
    renderer = renderer or FakeRenderer()
    runtime = FakeRuntime()
    return SpeakingAvatar(renderer, speech=runtime), renderer, runtime.created


def test_the_core_opens_a_speech_channel_in_the_renderer_config_voice_with_itself_as_sink():
    renderer = FakeRenderer()
    renderer.config.tts.ref_file = "zh-TW-HsiaoYuNeural"
    avatar, renderer, created = speaking(renderer)

    assert created == [avatar.tts]
    assert avatar.tts.sink is avatar
    assert avatar.tts.voice == TtsVoice(engine="edgetts", voice="zh-TW-HsiaoYuNeural")


def test_tts_pcm_reaches_the_renderer_through_the_core():
    avatar, renderer, _ = speaking()
    pcm = np.ones(320, dtype=np.float32)
    event = {"turn_id": "t", "generation": 1, "fragment_sequence": 0}

    assert avatar.tts.sink.put_audio_frame(pcm, event) is True
    renderer.accept = False
    assert avatar.tts.sink.put_audio_frame(pcm, event) is False

    assert [frame for frame, _ in renderer.frames] == [pcm, pcm]
    assert renderer.frames[0][1] == event


def test_text_is_cleaned_registered_with_the_session_then_queued_for_tts():
    avatar, _, _ = speaking()
    queued = []
    avatar.configure_media_fence(
        media_guard=lambda _event, _stage: True,
        on_stale_drop=lambda _stage, _reason: None,
        on_fragment_queued=lambda text, event: queued.append((text, event)),
    )
    event = {"turn_id": "t", "generation": 1, "fragment_sequence": 0}

    avatar.put_msg_txt("**你好**😀", event)
    avatar.put_msg_txt("😀", dict(event, fragment_sequence=1))
    avatar.put_msg_txt("沒有輪次")

    assert queued == [("你好", event)]
    assert avatar.tts.messages == [("你好", event), ("沒有輪次", {})]


def test_tts_fragment_questions_and_reports_reach_the_voice_session():
    avatar, renderer, _ = speaking()
    renderer.accepts_media = lambda event, stage: (event, stage) == ("ok", "tts")
    sink = avatar.tts.sink
    seen = []
    avatar.configure_media_fence(
        media_guard=lambda _event, _stage: True,
        on_stale_drop=lambda _stage, _reason: None,
        on_fragment_failed=lambda event, reason: seen.append(("failed", event, reason)),
        fragment_playback_committed=lambda event: event["fragment_sequence"] == 0,
        fragment_playback_ended=lambda event: event["fragment_sequence"] == 1,
        on_tts_onset_preroll_ms=lambda ms: seen.append(("preroll", ms)),
        on_tts_retry=lambda *, after_commit: seen.append(("retry", after_commit)),
        on_stage_end=lambda stage: seen.append(("stage", stage)),
        on_llm_chunk=lambda text, event: seen.append(("chunk", text, event)),
    )
    first = {"turn_id": "t", "generation": 1, "fragment_sequence": 0}

    assert sink.fragment_playback_committed(first) is True
    assert sink.fragment_playback_ended(first) is False
    assert sink.fragment_playback_ended(dict(first, fragment_sequence=1)) is True
    assert sink.accepts_media("ok", "tts") is True
    assert sink.accepts_media("old", "tts") is False
    sink.notify_fragment_synthesis_failed(first, "tts_exhausted_before_audio")
    sink.observe_tts_onset_preroll_ms(12.5)
    sink.observe_tts_retry(after_commit=True)
    sink.mark_stage_end("tts_first_pcm")
    avatar.notify_llm_chunk("你好", first)

    assert seen == [
        ("failed", first, "tts_exhausted_before_audio"),
        ("preroll", 12.5),
        ("retry", True),
        ("stage", "tts_first_pcm"),
        ("chunk", "你好", first),
    ]


def test_an_unfenced_sink_lets_tts_play_without_a_voice_session():
    avatar, _, _ = speaking()
    event = {"turn_id": "t", "generation": 1, "fragment_sequence": 0}

    assert avatar.fragment_playback_committed(event) is False
    assert avatar.fragment_playback_ended(event) is True
    avatar.notify_fragment_synthesis_failed(event, "tts_exhausted_before_audio")
    avatar.observe_tts_onset_preroll_ms(1.0)
    avatar.observe_tts_retry(after_commit=False)
    avatar.mark_stage_end("tts_first_pcm")
    avatar.notify_llm_chunk("你好")


class LifecycleRenderer(FakeRenderer):
    def __init__(self, calls):
        super().__init__()
        self.calls = calls
        self.pending_audio = None

    def configure_pending_audio(self, probe):
        self.pending_audio = probe

    def flush_talk(self):
        self.calls.append("renderer.flush")

    def render(self, quit_event, loop=None, audio_track=None, video_track=None):
        self.calls.append(("renderer.render", quit_event, loop, audio_track, video_track))


class LifecycleTTS(FakeTTS):
    calls: list
    pending = False

    def flush(self):
        self.calls.append("tts.flush")

    def run(self, quit_event):
        self.calls.append(("tts.render", quit_event))

    def has_pending_work(self):
        return self.pending


def lifecycle():
    calls = []
    renderer = LifecycleRenderer(calls)

    def channel(voice, sink):
        tts = LifecycleTTS(voice, sink)
        tts.calls = calls
        return tts

    return SpeakingAvatar(renderer, speech=FakeRuntime(channel)), renderer, calls


def test_barge_in_stops_tts_before_the_renderer_drops_queued_media():
    avatar, _, calls = lifecycle()

    avatar.flush_talk()

    assert calls == ["tts.flush", "renderer.flush"]


def test_tts_runs_for_as_long_as_the_renderer_and_reports_pending_audio():
    from threading import Event

    avatar, renderer, calls = lifecycle()
    quit_event = Event()

    avatar.render(quit_event, "loop", "audio", "video")

    assert calls == [
        ("tts.render", quit_event),
        ("renderer.render", quit_event, "loop", "audio", "video"),
    ]
    assert renderer.pending_audio() is False
    avatar.tts.pending = True
    assert renderer.pending_audio() is True


def test_a_webrtc_session_gets_a_renderer_fed_by_the_tts_runtime(monkeypatch):
    from src.server.routes import webrtc
    from src.server.state import state

    renderer = FakeRenderer()
    built = []
    runtime = FakeRuntime()
    monkeypatch.setattr(webrtc, "create_avatar", lambda *args: built.append(args) or renderer)
    monkeypatch.setattr(state, "tts_runtime", runtime)

    avatar = webrtc.build_speaking_avatar("config", "model", "assets", 7)

    assert built == [("config", "model", "assets", 7)]
    assert avatar.renderer is renderer
    assert runtime.created == [avatar.tts]
    assert avatar.tts.sink is avatar


def test_tts_stops_when_the_renderer_fails_to_start():
    from threading import Event

    import pytest

    avatar, renderer, _ = lifecycle()

    def fail(*_args):
        raise RuntimeError("renderer failed")

    renderer.render = fail
    quit_event = Event()

    with pytest.raises(RuntimeError):
        avatar.render(quit_event)
    assert quit_event.is_set()


def test_a_profile_switch_gives_the_renderer_the_config_and_tts_its_voice():
    avatar, renderer, _ = speaking()
    bound = []
    renderer.bind_profile = lambda config, data: bound.append((config, data))
    config = Config()
    config.tts.type, config.tts.ref_file = "matcha", "role-voice"

    avatar.bind_profile(config, "assets")

    assert bound == [(config, "assets")]
    assert avatar.tts.voice == TtsVoice(engine="matcha", voice="role-voice")
    assert avatar.tts.flushes == 1  # The old role's queued text is not spoken.


def test_renderer_state_is_read_and_written_on_the_renderer():
    avatar, renderer, _ = speaking()
    renderer.is_speaking = lambda: True
    config = Config()
    config.tts.ref_file = "zh-TW-YunJheNeural"

    avatar.config = config
    avatar._role_presentation = "presentation"

    assert renderer.config is avatar.config is config
    assert renderer._role_presentation == "presentation"
    assert avatar._role_presentation == "presentation"
    assert avatar.is_speaking() is True
    assert avatar.tts.voice.voice != "zh-TW-YunJheNeural"  # TTS voice swaps stay explicit.


def test_the_renderer_builds_no_tts_and_asks_the_core_whether_pcm_is_due():
    from types import SimpleNamespace

    from src.avatars.base import BaseAvatar

    renderer = BaseAvatar(SimpleNamespace(
        model=SimpleNamespace(type="none"), audio=SimpleNamespace(fps=50),
        sessionid=1, customopt=[],
    ))

    assert not hasattr(renderer, "tts")
    assert not hasattr(renderer, "put_msg_txt")
    assert renderer.has_pending_audio() is False
    renderer.configure_pending_audio(lambda: True)
    assert renderer.has_pending_audio() is True


def wav(seconds, rate=8000):
    import io

    import soundfile as sf

    output = io.BytesIO()
    sf.write(output, np.full(int(seconds * rate), 0.25, dtype=np.float32), rate, format="WAV")
    return output.getvalue()


def test_an_uploaded_audio_file_plays_as_16k_frames_on_the_renderer():
    avatar, renderer, _ = speaking()

    avatar.put_audio_file(wav(0.5), {"source": "file"})

    assert len(renderer.frames) == 25
    assert all(frame.shape == (320,) for frame, _ in renderer.frames)
    assert all(event == {"source": "file"} for _, event in renderer.frames)


def test_an_overlong_audio_file_is_refused_before_playing(monkeypatch):
    import pytest

    from src.server import speaking_avatar
    from src.vad.audio import AudioTooLongError

    monkeypatch.setattr(speaking_avatar, "MAX_AUDIO_FILE_SECONDS", 0.25)
    avatar, renderer, _ = speaking()

    with pytest.raises(AudioTooLongError):
        avatar.put_audio_file(wav(0.5))
    assert renderer.frames == []
