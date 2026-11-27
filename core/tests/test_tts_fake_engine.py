# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The TTS layer's ``fake`` engine, seen through the in-process adapter.

The fake speaks silence of a known length through the same fragment and
``AudioSink`` path as the real engines, so these tests run the layer's contract
(fragment events, the playback fence, cancellation) on a machine with no GPU,
no network and no voice models.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from nova_contracts.tts import (
    PCM_MEDIA_TYPE,
    FragmentEnvelope,
    PlayableFragment,
    SynthesisRequest,
    TtsEngineSettings,
    TtsVoice,
)
from nova_tts.adapter import InProcessTtsService

SETTINGS = TtsEngineSettings(frames_per_second=50)
FAKE_VOICE = TtsVoice(engine="fake")
FRAME_SAMPLES = 320


class RecordingSink:
    """The core's ``AudioSink`` as a test double: records every call, paces playback on request."""

    def __init__(self) -> None:
        self.frames: list[tuple[np.ndarray, dict]] = []
        self.failures: list[tuple[dict, str]] = []
        self.stages: list[str] = []
        self.refused_turns: set[str] = set()
        self.playback_over = threading.Event()
        self.playback_over.set()
        # Backpressure: the sink blocks the frame with this media sequence until released.
        self.hold_first_frame: threading.Event | None = None
        self.hold_media_sequence = 0
        self._lock = threading.Lock()

    def put_audio_frame(self, samples, eventpoint) -> bool:
        if (self.hold_first_frame is not None
                and eventpoint.get("media_sequence") == self.hold_media_sequence):
            assert self.hold_first_frame.wait(timeout=5), "the sink was never released"
        with self._lock:
            self.frames.append((np.asarray(samples, dtype=np.float32).copy(), dict(eventpoint)))
        return True

    def accepts_media(self, eventpoint, stage) -> bool:
        return eventpoint.get("turn_id") not in self.refused_turns

    def fragment_playback_committed(self, eventpoint) -> bool:
        return True

    def fragment_playback_ended(self, eventpoint) -> bool:
        return self.playback_over.is_set()

    def notify_fragment_synthesis_failed(self, eventpoint, reason) -> None:
        self.failures.append((dict(eventpoint), reason))

    def observe_tts_onset_preroll_ms(self, milliseconds) -> None:
        pass

    def observe_tts_retry(self, *, after_commit) -> None:
        pass

    def mark_stage_end(self, stage) -> None:
        self.stages.append(stage)

    def fragments(self) -> list[tuple[str, int]]:
        """The (turn, fragment sequence) pairs in the order their first frame arrived."""
        seen: list[tuple[str, int]] = []
        for _, eventpoint in list(self.frames):
            key = (eventpoint["turn_id"], eventpoint["fragment_sequence"])
            if key not in seen:
                seen.append(key)
        return seen

    def frames_of(self, turn_id: str, sequence: int) -> list[tuple[np.ndarray, dict]]:
        return [(samples, eventpoint) for samples, eventpoint in list(self.frames)
                if (eventpoint["turn_id"], eventpoint["fragment_sequence"]) == (turn_id, sequence)]


def eventpoint(sequence: int = 0, turn_id: str = "turn-1", generation: int = 1) -> dict:
    return {"turn_id": turn_id, "generation": generation, "fragment_sequence": sequence}


def wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def fragment(text: str = "你好。", seconds: float = 0.0) -> PlayableFragment:
    return PlayableFragment(envelope=FragmentEnvelope(turn_id="t", generation=0, sequence=0),
                            text=text, estimated_seconds=seconds)


@pytest.fixture
def engines() -> list:
    """The engines the adapter built, in order, for tests that watch synthesis."""
    return []


@pytest.fixture
def tts(engines) -> InProcessTtsService:
    from nova_tts.factory import create_tts_engine

    def create_engine(kind, config, sink):
        engines.append(create_tts_engine(kind, config, sink))
        return engines[-1]

    return InProcessTtsService(SETTINGS, create_engine=create_engine)


@pytest.fixture
def channel(tts):
    """A fake-voice speech channel on a fresh sink, its worker thread stopped at teardown."""
    sink = RecordingSink()
    opened = tts.open_channel(FAKE_VOICE, sink)
    quit_event = threading.Event()
    opened.run(quit_event)
    yield opened, sink
    quit_event.set()
    sink.playback_over.set()
    if sink.hold_first_frame is not None:
        sink.hold_first_frame.set()


# ---- selection: a configured engine that no console list offers


def test_the_fake_engine_is_built_by_the_factory_like_any_other_engine():
    from nova_tts.base import BaseTTS
    from nova_tts.factory import create_tts_engine

    config = SimpleNamespace(audio=SimpleNamespace(fps=50), tts=SimpleNamespace(type="fake"))

    assert isinstance(create_tts_engine("fake", config, RecordingSink()), BaseTTS)


def test_a_saved_configuration_may_name_the_fake_engine():
    from nova_tts import config_section, voice_library

    values = {"type": "fake"}

    assert voice_library.migrate_tts_values(values, where="設定檔") is False
    assert values["type"] == "fake"
    assert "fake" in config_section.ENGINES
    assert config_section.voice(SimpleNamespace(
        type="fake", ref_file="", tts_server="", model="", edge_persistent_worker=True,
        edge_prefetch=True, edge_connection_reuse=True)).engine == "fake"
    assert "fake" in config_section.ENGLISH_ENGINES


def test_no_console_list_offers_the_fake_engine(tts):
    from nova_core.config.schema import Config
    from nova_core.server.runtime_settings import SettingsError, apply_tts_settings, speech_snapshot

    config = Config()
    config.tts.type = "fake"

    snapshot = speech_snapshot(config, tts=tts)["tts"]

    assert {item["id"] for item in snapshot["engines"]} == {"edgetts", "breezyvoice", "matcha"}
    assert "fake" not in str(tts.catalog().model_dump(mode="json"))
    with pytest.raises(SettingsError):
        apply_tts_settings(config, {"type": "fake"}, session_count=0, tts=tts)


# ---- synthesize: silent 16 kHz s16le PCM of a known length


def test_synthesize_returns_silence_as_long_as_the_fragment_is_estimated_to_last(tts):
    request = SynthesisRequest(fragment=fragment("你好。", seconds=0.5), voice=FAKE_VOICE)

    pcm = b"".join(tts.synthesize(request))

    assert PCM_MEDIA_TYPE == "audio/L16;rate=16000"
    assert len(pcm) == int(0.5 * 16000) * 2
    assert not np.frombuffer(pcm, dtype="<i2").any()


def test_synthesize_without_an_estimate_lasts_as_long_as_the_text_takes_to_say(tts):
    from nova_tts.engines.fake import SECONDS_PER_CHARACTER

    request = SynthesisRequest(fragment=fragment("一二三四"), voice=FAKE_VOICE)

    pcm = b"".join(tts.synthesize(request))

    assert len(pcm) == round(4 * SECONDS_PER_CHARACTER * 16000) * 2


def test_synthesize_stops_at_max_seconds(tts):
    request = SynthesisRequest(fragment=fragment("你好。", seconds=2.0), voice=FAKE_VOICE, max_seconds=0.25)

    assert len(b"".join(tts.synthesize(request))) == int(0.25 * 16000) * 2


def test_synthesize_chunks_stay_within_the_pcm_chunk_size(tts):
    request = SynthesisRequest(fragment=fragment("你好。", seconds=3.0), voice=FAKE_VOICE)

    chunks = list(tts.synthesize(request))

    assert len(chunks) > 1 and all(0 < len(chunk) <= 32 * 1024 for chunk in chunks)


# ---- the live path: frames and fragment events reach the sink as for a real engine


def test_a_spoken_fragment_reaches_the_sink_as_20_ms_silent_frames_with_ordered_events(channel):
    opened, sink = channel

    opened.speak("你好。", eventpoint(0))

    assert wait_until(lambda: sink.frames and sink.frames[-1][1].get("fragment_end"))
    frames = sink.frames_of("turn-1", 0)
    assert all(samples.shape == (FRAME_SAMPLES,) and samples.dtype == np.float32 and not samples.any()
               for samples, _ in frames)
    points = [point for _, point in frames]
    assert [point["media_sequence"] for point in points] == list(range(len(points)))
    assert [point["fragment_start"] for point in points] == [True] + [False] * (len(points) - 1)
    assert [point["fragment_end"] for point in points] == [False] * (len(points) - 1) + [True]
    assert points[0]["status"] == "start"
    assert all((point["turn_id"], point["generation"]) == ("turn-1", 1) for point in points)
    # The same envelope the core cut the fragment with.
    envelope = FragmentEnvelope(turn_id=points[0]["turn_id"], generation=points[0]["generation"],
                                sequence=points[0]["fragment_sequence"])
    assert envelope.sequence == 0
    assert sink.stages[:2] == ["tts_pcm_available", "tts_first_pcm"]
    assert not sink.failures


def test_fragments_are_spoken_in_the_order_they_were_queued(channel):
    opened, sink = channel

    for sequence in range(3):
        opened.speak("好。", eventpoint(sequence))

    assert wait_until(lambda: len(sink.fragments()) == 3 and sink.frames[-1][1].get("fragment_end"))
    assert sink.fragments() == [("turn-1", 0), ("turn-1", 1), ("turn-1", 2)]


def test_visual_markup_alone_is_not_spoken(channel):
    opened, sink = channel

    opened.speak("😀", eventpoint(0))
    opened.speak("好。", eventpoint(1))

    assert wait_until(lambda: sink.fragments() == [("turn-1", 1)])


def test_the_playback_fence_keeps_the_channel_busy_until_the_fragment_has_played(channel):
    opened, sink = channel
    sink.playback_over.clear()

    opened.speak("好。", eventpoint(0))

    assert wait_until(lambda: sink.frames and sink.frames[-1][1].get("fragment_end"))
    time.sleep(0.1)
    assert opened.has_pending_work()
    sink.playback_over.set()
    assert wait_until(lambda: not opened.has_pending_work())


def test_a_fragment_without_a_turn_is_spoken_and_never_waits_for_the_fence(channel):
    opened, sink = channel
    sink.playback_over.clear()

    opened.speak("好。", {})

    assert wait_until(lambda: len(sink.frames) > 0)
    assert wait_until(lambda: not opened.has_pending_work())


# ---- prefetch: one fragment ahead, and cancellation drops it


def test_only_one_fragment_is_synthesised_ahead_of_the_one_being_emitted(channel, engines):
    opened, sink = channel
    sink.hold_first_frame = threading.Event()

    for sequence in range(4):
        opened.speak(f"第{sequence}段。", eventpoint(sequence))

    # Fragment 0 is blocked in the sink and fragment 1 is held; 2 and 3 still wait as text.
    assert wait_until(lambda: engines[0].synthesized == ["第0段。", "第1段。"])
    time.sleep(0.2)
    assert engines[0].synthesized == ["第0段。", "第1段。"]
    assert opened.has_pending_work()
    sink.hold_first_frame.set()
    assert wait_until(lambda: len(sink.fragments()) == 4 and sink.frames[-1][1].get("fragment_end"))
    assert sink.fragments() == [("turn-1", sequence) for sequence in range(4)]


def test_a_flush_drops_the_queued_and_the_held_fragments_and_a_new_turn_plays_without_them(channel):
    opened, sink = channel
    sink.hold_first_frame = threading.Event()
    opened.speak("甲一。", eventpoint(0, "old"))
    opened.speak("甲二。", eventpoint(1, "old"))
    opened.speak("甲三。", eventpoint(2, "old"))
    time.sleep(0.2)

    opened.flush()
    sink.hold_first_frame.set()
    opened.speak("乙一。", eventpoint(0, "new", 2))

    assert wait_until(lambda: ("new", 0) in sink.fragments()
                      and sink.frames[-1][1].get("fragment_end"))
    assert wait_until(lambda: not opened.has_pending_work())
    # Only the frame that was already inside the sink call when the flush came.
    assert len(sink.frames_of("old", 0)) <= 1
    assert [key for key in sink.fragments() if key[0] == "old"] in ([], [("old", 0)])


def test_a_flush_stops_the_fragment_being_emitted_and_nothing_follows_it(channel):
    opened, sink = channel
    sink.hold_media_sequence = 3
    sink.hold_first_frame = threading.Event()
    opened.speak("一二三四五六七八九十。", eventpoint(0, "old"))
    opened.speak("後面。", eventpoint(1, "old"))
    assert wait_until(lambda: len(sink.frames) == 3)  # frame 3 is blocked in the sink

    opened.flush()
    sink.hold_first_frame.set()

    assert wait_until(lambda: not opened.has_pending_work())
    time.sleep(0.1)
    # At most the frame that was already inside the sink call; no end, no later fragment.
    assert len(sink.frames) <= 4
    assert not any(point.get("fragment_end") for _, point in sink.frames)
    assert sink.fragments() == [("old", 0)]


def test_a_fragment_of_a_superseded_turn_is_not_played_even_without_a_flush(channel):
    opened, sink = channel
    sink.hold_first_frame = threading.Event()
    sink.refused_turns.add("stale")
    opened.speak("第一段。", eventpoint(0, "live"))
    opened.speak("過期。", eventpoint(0, "stale"))
    opened.speak("第二段。", eventpoint(1, "live"))
    time.sleep(0.2)

    sink.hold_first_frame.set()

    assert wait_until(lambda: ("live", 1) in sink.fragments() and sink.frames[-1][1].get("fragment_end"))
    assert ("stale", 0) not in sink.fragments()


def test_stopping_the_worker_ends_it_after_the_fragment_being_emitted(tts):
    sink = RecordingSink()
    sink.hold_first_frame = threading.Event()
    opened = tts.open_channel(FAKE_VOICE, sink)
    quit_event = threading.Event()
    opened.run(quit_event)
    opened.speak("一。", eventpoint(0))
    opened.speak("二。", eventpoint(1))
    time.sleep(0.2)

    quit_event.set()
    sink.hold_first_frame.set()
    sink.playback_over.set()

    assert wait_until(lambda: sink.frames and sink.frames[-1][1].get("fragment_end"))
    time.sleep(0.3)
    assert sink.fragments() == [("turn-1", 0)]


def test_changing_the_voice_keeps_speaking_with_the_fake_engine(channel):
    opened, sink = channel

    opened.set_voice(TtsVoice(engine="fake", voice="another"))
    opened.speak("好。", eventpoint(0))

    assert wait_until(lambda: sink.frames and sink.frames[-1][1].get("fragment_end"))
    assert opened.voice.voice == "another"
