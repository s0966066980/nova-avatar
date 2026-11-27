# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The avatar rendering layer's contract: its DTOs and the in-process adapter."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from nova_contracts.avatar import (
    STAGE_FPS,
    STAGE_FRAME,
    AvatarBootCheck,
    AvatarRenderer,
    AvatarService,
    FrameSize,
)
from nova_contracts.common import ServiceError
from nova_render.scene.service import scene_service


def test_a_boot_check_explains_why_an_avatar_cannot_start():
    refused = AvatarBootCheck(bootable=False, reason="素材不存在")

    assert (refused.bootable, refused.reason) == (False, "素材不存在")
    assert AvatarBootCheck(bootable=True).reason == ""


def test_a_frame_size_is_positive_and_immutable():
    size = FrameSize(width=720, height=1280)

    with pytest.raises(ValidationError):
        FrameSize(width=0, height=1280)
    with pytest.raises(ValidationError):
        size.width = 360  # type: ignore[misc]


def test_the_stage_is_a_portrait_720p_canvas_at_25_fps():
    assert (STAGE_FRAME.width, STAGE_FRAME.height, STAGE_FPS) == (720, 1280, 25)


# One conversation's renderer, as the core sees it.

def _renderer():
    from nova_render.base import BaseAvatar

    return BaseAvatar(SimpleNamespace(
        model=SimpleNamespace(type="none"), audio=SimpleNamespace(fps=50),
        video=SimpleNamespace(max_height=0), sessionid=7, customopt=[],
    ))


def _frame(value):
    return np.full((STAGE_FRAME.height, STAGE_FRAME.width, 3), value, np.uint8)


def test_the_renderer_satisfies_the_avatar_renderer_protocol():
    renderer = _renderer()

    assert isinstance(renderer, AvatarRenderer)
    assert (renderer.sessionid, renderer.chunk, renderer.asset_epoch) == (7, 320, 0)


def test_a_role_transition_holds_the_old_role_until_the_core_starts_it(monkeypatch):
    monkeypatch.setattr(scene_service, "background_frame", lambda *_: None)
    renderer = _renderer()
    renderer.reset_role_presentation(True)
    renderer._present_frame(_frame(10), None)

    renderer.begin_role_transition("t1", {"kind": "effect", "effect": "fade", "duration": .01},
                                   clip=None, started_at=time.monotonic() + 3600)
    held, marker = renderer._present_frame(_frame(200), None)
    assert held.mean() < 50 and marker == {}

    renderer.start_role_transition(time.monotonic() - 1)
    played, marker = renderer._present_frame(_frame(200), {"turn_id": "a"})
    assert played.mean() > 150
    assert marker == {"turn_id": "a", "role_transition_id": "t1", "role_transition_end": True}

    renderer.close_role_transition()
    assert renderer._present_frame(_frame(200), None)[1] == {}


def test_without_role_composition_a_frame_is_only_height_limited():
    renderer = _renderer()
    renderer.reset_role_presentation(False)
    renderer.close_role_transition()
    frame = _frame(30)

    passed, marker = renderer._present_frame(frame, None)
    assert passed is frame and marker is None
    renderer.ensure_role_presentation()
    composed, _ = renderer._present_frame(frame, None)
    assert composed is not frame


# The process-wide service, served in-process.

@pytest.fixture
def avatars(tmp_path, monkeypatch):
    from nova_render.adapter import create_avatar_service

    monkeypatch.setattr("nova_render.catalog.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nova_render.scene.service.get_data_dir", lambda: tmp_path)
    return create_avatar_service()


def _install_avatar(root, avatar_id, size=(40, 80)):
    from PIL import Image

    directory = root / "avatars" / avatar_id
    (directory / "full_imgs").mkdir(parents=True)
    (directory / "mask").mkdir()
    (directory / "latents.pt").write_bytes(b"")
    Image.new("RGB", size).save(directory / "full_imgs" / "00000000.png")
    return directory


def test_the_adapter_is_an_avatar_service(avatars):
    assert isinstance(avatars, AvatarService)


def test_an_unknown_engine_is_not_bootable_and_says_why(avatars):
    check = avatars.bootable("wav2lip", "someone")

    assert check == AvatarBootCheck(bootable=False, reason="不支援的數字人引擎: wav2lip")
    assert not avatars.knows_engine("wav2lip") and avatars.knows_engine("musetalk")
    assert avatars.can_import("musetalk") and not avatars.can_import("wav2lip")


def test_catalog_refusals_are_service_errors_for_operators(avatars):
    with pytest.raises(ServiceError, match="找不到數字人"):
        avatars.archive_avatar("nobody")
    with pytest.raises(ServiceError, match="找不到封存的數字人"):
        avatars.restore_avatar("nobody-000000000000")
    with pytest.raises(ServiceError):
        avatars.normalize_quality({"mouth_sharpen": "very"})
    with pytest.raises(ServiceError):
        avatars.background_preview("../../etc")


def test_an_archived_avatar_is_named_by_its_archive_and_restores(avatars, tmp_path):
    _install_avatar(tmp_path, "angela")
    assert avatars.avatar_exists("angela")

    archive_name = avatars.archive_avatar("angela")

    assert not avatars.avatar_exists("angela")
    assert avatars.list_archived_avatars() == [{"archive_name": archive_name, "avatar_id": "angela"}]
    assert avatars.restore_avatar(archive_name) == "angela"


def test_the_source_and_output_size_come_from_the_avatar_preview(avatars, tmp_path):
    _install_avatar(tmp_path, "angela", size=(720, 1280))

    assert avatars.source_size("angela") == FrameSize(width=720, height=1280)
    assert avatars.source_size("../angela") is None
    assert avatars.output_size(720, 1280, 640) == FrameSize(width=360, height=640)
    assert avatars.output_size(720, 1280) == FrameSize(width=720, height=1280)


def test_a_build_borrows_the_running_musetalk_vae(avatars, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("nova_render.builder.build_character",
                        lambda *args, **kwargs: calls.append(kwargs) or {"avatar_id": args[2]})
    vae = object()

    avatars.build_avatar("musetalk", tmp_path / "v.mp4", "angela",
                         running_model=lambda: ("musetalk", (vae, "unet")))
    avatars.build_avatar("musetalk", tmp_path / "v.mp4", "angela", running_model=lambda: None)

    assert calls[0]["loaded_vae"]() is vae
    assert calls[1]["loaded_vae"]() is None


def test_a_failed_build_is_a_service_error(avatars, monkeypatch, tmp_path):
    from nova_render import builder

    def refuse(*_args, **_kwargs):
        raise builder.BuildError("角色 angela 已存在，請換一個名稱")

    monkeypatch.setattr(builder, "build_character", refuse)

    with pytest.raises(ServiceError, match="已存在"):
        avatars.build_avatar("musetalk", tmp_path / "v.mp4", "angela")


# The fake engine, driven through the in-process service like any engine.

CHUNK = 320


def _fake_config():
    from nova_core.config.defaults import get_default_config

    config = get_default_config()
    config.model.type = "fake"
    return config


def _pcm(sequence, value=None):
    """One 20 ms frame whose samples identify it."""
    return np.full(CHUNK, (sequence + 1) / 1000 if value is None else value, np.float32)


def _event(turn="a", generation=0, sequence=0, **flags):
    return {"turn_id": turn, "generation": generation, "media_sequence": sequence, **flags}


class PlaybackTrack:
    """A WebRTC track that plays every frame at once.

    It applies the media guard on enqueue like the real track does, records what was
    queued and reports each tagged boundary back like the player does.
    """

    def __init__(self, kind, guard=None, on_play=None):
        self.kind = kind
        self.items = []
        self.guard = guard
        self.on_play = on_play

    async def enqueue(self, frame, eventpoint=None):
        if (self.guard and isinstance(eventpoint, dict) and eventpoint.get("turn_id")
                and not self.guard(eventpoint, f"webrtc_{self.kind}_enqueue")):
            return False
        self.items.append((frame, eventpoint))
        if self.on_play and eventpoint:
            self.on_play(eventpoint)
        return True

    def spoken(self):
        return [(frame, event) for frame, event in self.items if event and event.get("turn_id")]


class StalledTrack:
    """A track whose consumer is gone: every enqueue waits for room that never comes."""

    async def enqueue(self, frame, eventpoint=None):
        await asyncio.Event().wait()


class Stage:
    """One fake renderer rendering into recording tracks on a background event loop."""

    def __init__(self, service, *, guard=None, audio_track=None, video_track=None):
        config = _fake_config()
        model, assets = service.prepare_model(config)
        self.renderer = service.create_renderer(config, model, assets, 3)
        self.renderer.step_seconds = 0.001
        self.drops = []
        self.renderer.configure_media_fence(
            media_guard=guard or (lambda *_: True),
            on_stale_drop=lambda stage, reason: self.drops.append((stage, reason)),
        )
        self.played = []
        self.audio = audio_track or PlaybackTrack("audio", guard, self.played.append)
        self.video = video_track or PlaybackTrack("video", guard)
        self.quit = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.render_thread = threading.Thread(target=self._render, daemon=True)

    def _render(self):
        self.renderer.render(self.quit, self.loop, self.audio, self.video)

    def __enter__(self):
        self.loop_thread.start()
        self.render_thread.start()
        return self

    def __exit__(self, *_exc):
        self.stop()
        # Let the cancellation of a stalled enqueue finish before the loop closes.
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0.01), self.loop).result(2)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.loop_thread.join(2)
        self.loop.close()

    def stop(self):
        self.quit.set()
        self.render_thread.join(5)
        assert not self.render_thread.is_alive(), "render did not stop on quit_event"

    def wait_for(self, condition, what, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, f"timed out waiting for {what}"
            time.sleep(0.002)


@pytest.fixture
def stage(avatars):
    with Stage(avatars) as running:
        yield running


def test_the_fake_engine_boots_from_config_but_is_not_a_console_choice(avatars):
    assert avatars.bootable("fake", "any") == AvatarBootCheck(bootable=True)
    assert [engine["id"] for engine in avatars.list_engines()] == ["musetalk"]
    assert not avatars.knows_engine("fake") and not avatars.can_import("fake")
    assert not avatars.uses_green_screen("any")


def test_the_fake_engine_loads_opaque_handles_and_a_renderer_for_the_session(avatars):
    config = _fake_config()

    model, _assets = avatars.prepare_model(config)
    renderer = avatars.create_renderer(config, model, avatars.load_assets(config), 9)

    assert isinstance(renderer, AvatarRenderer)
    assert (renderer.sessionid, renderer.chunk, renderer.asset_epoch) == (9, CHUNK, 0)
    assert not renderer.is_speaking() and not renderer.direct_audio_enabled
    assert renderer.accepts_media({"turn_id": "a"}, "any")


def test_an_idle_fake_renderer_outputs_the_fixed_frame_and_silence(stage):
    from nova_render.fake import FAKE_FRAME_COLOR

    stage.wait_for(lambda: len(stage.video.items) >= 3 and len(stage.audio.items) >= 6, "idle media")

    frame, event = stage.video.items[0]
    picture = frame.to_ndarray(format="bgr24")
    assert picture.shape == (STAGE_FRAME.height, STAGE_FRAME.width, 3)
    assert tuple(picture[640, 360]) == FAKE_FRAME_COLOR
    assert event == {"avatar_epoch": 0}
    silence = stage.audio.items[0][0].to_ndarray()
    assert silence.shape == (1, CHUNK) and not silence.any()
    assert not stage.renderer.is_speaking()


def test_reply_audio_is_the_clock_and_its_boundaries_are_played_in_order(stage):
    # Two fragments of three frames each: media_sequence restarts per fragment.
    flags = [{"status": "start", "fragment_start": True}, {}, {"fragment_end": True},
             {"fragment_start": True}, {}, {"status": "end", "fragment_end": True}]
    for n, flag in enumerate(flags):
        fragment = n // 3
        assert stage.renderer.put_audio_frame(
            _pcm(n), _event(sequence=n % 3, fragment_sequence=fragment, **flag))

    stage.wait_for(lambda: len(stage.audio.spoken()) >= 6 and len(stage.video.spoken()) >= 3,
                   "the reply")

    spoken = stage.audio.spoken()[:6]
    pcm = [frame.to_ndarray()[0] for frame, _ in spoken]
    assert [int(samples[0]) for samples in pcm] == [int((n + 1) / 1000 * 32767) for n in range(6)]
    events = [event for _, event in spoken]
    assert [event["media_sequence"] for event in events] == list(range(6))
    assert [event["fragment_media_sequence"] for event in events] == [0, 1, 2, 0, 1, 2]
    assert [bool(event.get("fragment_start")) for event in events] == [True, False, False, True, False, False]
    assert [bool(event.get("fragment_end")) for event in events] == [False, False, True, False, False, True]
    assert (events[0]["status"], events[-1]["status"]) == ("start", "end")
    assert [event for event in stage.played if event.get("turn_id")][:6] == events
    # One 25 fps picture for every two 20 ms audio frames, tagged with the turn it shows.
    assert all(event["turn_id"] == "a" for _, event in stage.video.spoken())
    assert len(stage.video.spoken()) == 3


def test_the_renderer_speaks_while_reply_pcm_plays_and_idles_after(stage):
    stage.renderer.put_audio_frame(_pcm(0), _event(sequence=0, status="start"))
    stage.renderer.put_audio_frame(_pcm(1), _event(sequence=1, status="end"))

    stage.wait_for(lambda: len(stage.audio.spoken()) >= 2, "the reply")
    stage.wait_for(lambda: not stage.renderer.is_speaking(), "idle after the reply")


def test_flushing_drops_queued_reply_media_before_it_renders(avatars):
    stage = Stage(avatars)
    for n in range(40):
        stage.renderer.put_audio_frame(_pcm(n), _event(sequence=n))

    stage.renderer.flush_talk()
    with stage:
        stage.wait_for(lambda: len(stage.audio.items) >= 6, "idle media")

    assert stage.audio.spoken() == [] and stage.video.spoken() == []
    assert not stage.renderer.is_speaking()


def test_an_interrupt_drops_the_old_reply_and_the_next_one_plays(avatars):
    current = {"generation": 0}

    def guard(event, _stage):
        return event["generation"] == current["generation"]

    with Stage(avatars, guard=guard) as stage:
        for n in range(200):
            stage.renderer.put_audio_frame(_pcm(n), _event(generation=0, sequence=n))
        stage.wait_for(stage.audio.spoken, "the old reply to start")

        current["generation"] = 1
        stage.renderer.flush_talk()
        queued_before_flush = len(stage.audio.spoken())

        assert not stage.renderer.put_audio_frame(_pcm(0), _event(generation=0, sequence=999))
        assert ("avatar_audio_enqueue", "stale_generation") in stage.drops
        stage.renderer.put_audio_frame(_pcm(0, 0.5), _event(generation=1, sequence=0, status="start"))
        stage.wait_for(lambda: any(event["generation"] == 1 for _, event in stage.audio.spoken()),
                       "the new reply")

        spoken = stage.audio.spoken()
        assert queued_before_flush < 200
        assert [event["generation"] for _, event in spoken[queued_before_flush:]] == [1]
        assert all(event["generation"] == 0 for _, event in spoken[:queued_before_flush])


def test_stopping_render_cancels_it_even_when_the_tracks_are_stalled(avatars):
    with Stage(avatars, audio_track=StalledTrack(), video_track=StalledTrack()) as stage:
        stage.renderer.put_audio_frame(_pcm(0), _event(sequence=0))
        time.sleep(0.05)

        stage.stop()

        assert not stage.renderer.is_speaking()


def test_binding_another_avatar_bumps_the_epoch_and_drops_the_old_reply(avatars):
    stage = Stage(avatars)
    renderer = stage.renderer
    for n in range(20):
        renderer.put_audio_frame(_pcm(n), _event(sequence=n))
    old_epoch = renderer.asset_epoch

    config = _fake_config()
    renderer.bind_profile(config, avatars.load_assets(config))

    assert renderer.asset_epoch == old_epoch + 1
    assert not renderer.accepts_media({"avatar_epoch": old_epoch}, "webrtc_video_commit")
    assert renderer.accepts_media({"avatar_epoch": renderer.asset_epoch}, "webrtc_video_commit")
    with stage:
        stage.wait_for(lambda: len(stage.audio.items) >= 6, "idle media")
    assert stage.audio.spoken() == []
    assert renderer.sessionid == 3
