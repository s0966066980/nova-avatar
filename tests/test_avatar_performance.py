# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Playback boundary checks for the optional performance experiments."""

import asyncio
import queue
from threading import Event, Lock
from types import SimpleNamespace

import numpy as np
import pytest

from src.avatars.base import BaseAvatar


@pytest.mark.parametrize(
    "max_height,expected",
    [(960, (540, 960)), (0, (1080, 1920)), (2160, (1080, 1920))],
)
def test_renderer_limits_output_height_without_stretching_or_upscaling(
    max_height, expected
):
    async def run():
        quit_event = Event()
        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(sessionid=7, video=SimpleNamespace(max_height=max_height))
        avatar.res_frame_queue = queue.Queue()
        avatar.frame_list_cycle = [np.zeros((1920, 1080, 3), dtype=np.uint8)]
        avatar.custom_index = {}
        avatar.custom_img_cycle = {}
        avatar.record_video_data = lambda _frame: None
        avatar.record_audio_data = lambda _frame: None
        avatar.res_frame_queue.put((None, 0, [(np.zeros(320, np.float32), 1, None)] * 2))

        class Track:
            def __init__(self, kind):
                self.kind, self.items = kind, []

            async def enqueue(self, frame, eventpoint=None):
                self.items.append(frame)
                if self.kind == "video":
                    quit_event.set()
                return True

        audio, video = Track("audio"), Track("video")
        await asyncio.wait_for(
            asyncio.to_thread(
                avatar.process_frames, quit_event,
                asyncio.get_running_loop(), audio, video,
            ),
            2,
        )
        assert (video.items[0].width, video.items[0].height) == expected
        assert [frame.samples for frame in audio.items] == [320, 320]

    asyncio.run(run())


def test_direct_audio_keeps_playing_when_mouth_inference_queue_is_full():
    """An actual bounded mouth queue must not block independent PCM output."""
    from src.avatars.musetalk.audio_stream_handler import MuseAudioStreamHandler

    async def run():
        current = [True]
        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(
            model=SimpleNamespace(batch_size=8),
            audio=SimpleNamespace(fps=50, l=10, r=10, av_offset_ms=0),
        )
        avatar.recording = False
        avatar.configure_media_fence(
            media_guard=lambda *_: current[0], on_stale_drop=lambda *_: None
        )
        avatar.audio_stream = MuseAudioStreamHandler(avatar.config, avatar, None)
        avatar.audio_stream.queue.put_nowait((np.zeros(320, np.float32), None))
        avatar.audio_stream.queue.maxsize = 1

        class Track:
            def __init__(self):
                self.items = []

            async def enqueue(self, frame, eventpoint=None):
                self.items.append(frame)
                return True

        track = Track()
        avatar.configure_audio_output(track, asyncio.get_running_loop())
        pending = asyncio.create_task(
            asyncio.to_thread(
                avatar.put_audio_frame, np.ones(320, np.float32) * 0.1,
                {"turn_id": "turn-1", "generation": 0, "fragment_sequence": 0},
            )
        )
        try:
            await asyncio.sleep(0.08)
            assert track.items, "PCM stalled behind the full mouth inference queue"
        finally:
            current[0] = False
            await pending

    asyncio.run(run())


def test_independent_track_supplies_idle_silence_without_waiting_for_renderer():
    from src.utils.webrtc import HumanPlayer

    async def run():
        player = HumanPlayer(None)
        player._start = lambda _track: None
        player.audio.enable_independent_audio()
        try:
            frames = [
                await asyncio.wait_for(player.audio.recv(), 0.1)
                for _ in range(5)
            ]
            assert [frame.pts for frame in frames] == [0, 320, 640, 960, 1280]
            assert all(np.count_nonzero(frame.to_ndarray()) == 0 for frame in frames)
        finally:
            player.audio.stop()
            player.video.stop()

    asyncio.run(run())


def test_independent_renderer_never_enqueues_duplicate_idle_audio():
    async def run():
        quit_event = Event()
        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(sessionid=7)
        avatar.res_frame_queue = queue.Queue()
        avatar.frame_list_cycle = [np.zeros((32, 32, 3), dtype=np.uint8)]
        avatar.custom_index = {}
        avatar.custom_img_cycle = {}
        avatar.record_video_data = lambda _frame: None
        avatar.record_audio_data = lambda _frame: None

        class Track:
            def __init__(self, kind):
                self.kind, self.items = kind, []

            async def enqueue(self, frame, eventpoint=None):
                self.items.append(frame)
                if self.kind == "video":
                    quit_event.set()
                return True

        audio, video = Track("audio"), Track("video")
        avatar.configure_audio_output(audio, asyncio.get_running_loop())
        avatar.res_frame_queue.put((None, 0, [(np.zeros(320, np.float32), 1, None)] * 2))
        await asyncio.wait_for(
            asyncio.to_thread(
                avatar.process_frames, quit_event,
                asyncio.get_running_loop(), audio, video,
            ),
            1,
        )
        assert not audio.items
        assert len(video.items) == 1

    asyncio.run(run())


def test_invalid_output_height_is_rejected_at_configuration_boundary():
    from src.config.loader import dict_to_config

    with pytest.raises(ValueError, match="max_height"):
        dict_to_config({"video": {"max_height": -1}})


def test_closing_direct_audio_releases_a_producer_waiting_for_playback():
    from src.utils.webrtc import HumanPlayer

    async def run():
        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.record_audio_data = lambda _frame: None
        player = HumanPlayer(None)
        avatar.configure_audio_output(player.audio, asyncio.get_running_loop())
        # No receiver consumes this actual bounded PCM queue.
        for _ in range(player.audio.max_buffer_frames):
            await player.audio.enqueue(None)
        pending = asyncio.create_task(
            asyncio.to_thread(
                avatar._enqueue_direct_audio, np.zeros(320, np.float32), {}
            )
        )
        await asyncio.sleep(0.03)
        assert not pending.done()
        avatar.stop_audio_output()
        assert await asyncio.wait_for(pending, 0.5) is False
        player.audio.stop()
        player.video.stop()

    asyncio.run(run())


def test_accelerated_vae_falls_back_for_unsupported_inputs():
    import torch
    from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder

    original_calls = []
    expected = np.zeros((1, 256, 256, 3), np.uint8)

    def decode(latents):
        original_calls.append(latents)
        return expected

    # Unsupported CPU input must be recoverable even without a GPU engine.
    decoder = TensorRTVAEDecoder.__new__(TensorRTVAEDecoder)
    decoder.original = SimpleNamespace(decode_latents=decode, scaling_factor=0.18215)
    decoder._lock, decoder._failed, decoder._stream = Lock(), False, None
    latents = torch.zeros((1, 4, 32, 32))
    assert decoder.decode_latents(latents) is expected
    assert decoder.decode_latents(latents) is expected
    assert len(original_calls) == 2
    assert decoder.scaling_factor == 0.18215
