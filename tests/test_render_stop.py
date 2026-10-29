# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Disconnects and renderer failures must not wedge the kiosk."""
import asyncio
import json
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pytest

from src.utils.webrtc import HumanPlayer


def test_echo_without_roles_reports_success_after_speaking_once():
    from src.server.routes.chat import human
    from src.server.state import state

    request = AsyncMock()
    request.json.return_value = {"type": "echo", "text": "你好", "sessionid": 7}
    avatar = SimpleNamespace(put_msg_txt=Mock())
    with (
        patch.object(state, "avatar_streams", {7: avatar}),
        patch.object(state, "roles", None, create=True),
    ):
        response = asyncio.run(human(request))

    payload = json.loads(response.text)
    assert payload["code"] == 0
    assert payload["response"] == "你好"
    avatar.put_msg_txt.assert_called_once_with("你好")


class StubbornRenderer:
    """A renderer that keeps working briefly after it is told to quit."""

    def __init__(self, linger: float):
        self.linger = linger
        self.started = threading.Event()

    def render(self, quit_event, loop, audio_track, video_track):
        self.started.set()
        quit_event.wait()
        time.sleep(self.linger)


def test_track_stop_does_not_block_the_event_loop():
    async def run():
        renderer = StubbornRenderer(linger=1.0)
        player = HumanPlayer(renderer)
        player._start(player.audio)
        player._start(player.video)
        assert await asyncio.to_thread(renderer.started.wait, 1)

        began = time.perf_counter()
        player.audio.stop()
        player.video.stop()
        assert time.perf_counter() - began < 0.2

        # The renderer is still winding down, yet other requests are served.
        ticks = 0
        async def tick():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(0.01)
                ticks += 1
        await asyncio.wait_for(tick(), 0.5)
        assert ticks == 5
        await asyncio.wait_for(player.render_stopped, 3)

    asyncio.run(run())


def test_track_stop_gives_up_on_a_renderer_that_never_quits(monkeypatch):
    import src.utils.webrtc as module

    monkeypatch.setattr(module, "RENDER_THREAD_JOIN_TIMEOUT", 0.1)
    release = threading.Event()

    class Hung:
        def render(self, quit_event, loop, audio_track, video_track):
            release.wait(5)

    async def run():
        player = HumanPlayer(Hung())
        player._start(player.audio)
        player.audio.stop()
        await asyncio.wait_for(player.render_stopped, 1)

    try:
        asyncio.run(run())
    finally:
        release.set()


def _silent_batch(batch_size):
    audio_frames = queue.Queue()
    for _ in range(batch_size * 2):
        audio_frames.put((np.zeros(320, np.float32), 1, None))
    features = queue.Queue()
    features.put([np.zeros((16, 32, 32), np.float32)] * batch_size)
    return features, audio_frames


def test_ultralight_inference_stops_when_result_queue_is_full():
    from src.avatars.ultralight import avatar as module

    quit_event = threading.Event()
    features, audio_frames = _silent_batch(2)
    results = queue.Queue(1)
    results.put("nobody consumes this")
    worker = threading.Thread(
        target=module.inference,
        args=(quit_event, 2, [np.zeros((168, 168, 3), np.uint8)], features, audio_frames, results, None),
        daemon=True,
    )
    worker.start()
    time.sleep(0.2)
    quit_event.set()
    worker.join(1)
    assert not worker.is_alive()


@pytest.mark.parametrize("module_name,cls_name", [
    ("src.avatars.ultralight.avatar", "UltralightAvatar"),
    ("src.avatars.musetalk.avatar", "MuseTalkAvatar"),
])
def test_render_stops_workers_when_its_loop_fails(monkeypatch, module_name, cls_name):
    import importlib

    module = importlib.import_module(module_name)
    seen = {}
    process_quit = []

    def inference(infer_quit, *_args):
        infer_quit.wait()
        # Joining inference before telling the frame processor to stop was
        # the Wav2Lip/UltraLight deadlock.
        seen["process_quit_set"] = process_quit[0].wait(1) if process_quit else False

    def process_frames(quit_event, *_args):
        process_quit.append(quit_event)
        quit_event.wait()

    monkeypatch.setattr(module, "inference", inference)
    avatar = getattr(module, cls_name).__new__(getattr(module, cls_name))
    avatar.batch_size = 2
    avatar.max_tts_audio_wait_seconds = .2
    avatar.init_customindex = lambda: None
    avatar.process_frames = process_frames
    avatar.tts = SimpleNamespace(render=lambda _: None, has_pending_work=lambda: False)

    def explode():
        raise RuntimeError("audio step failed")

    avatar.audio_stream = SimpleNamespace(
        queue=SimpleNamespace(qsize=lambda: 0, empty=lambda: True),
        startup_batch_emitted=True, startup_batch_size=2,
        first_speech_batch_pending=lambda: False,
        feat_queue=None, output_queue=None, run_step=explode,
    )
    for name in ('face_list_cycle', 'model', 'input_latent_list_cycle', 'res_frame_queue',
                 'vae', 'unet', 'pe', 'timesteps'):
        setattr(avatar, name, None)
    for name in ('accepts_media', 'record_stale_drop', 'mark_stage_end', 'asset_snapshot'):
        setattr(avatar, name, lambda *a, **k: None)

    quit_event = threading.Event()
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="audio step failed"):
        avatar.render(quit_event)
    assert time.perf_counter() - started < 0.9
    assert quit_event.is_set()
    assert seen["process_quit_set"] is True
    assert process_quit[0].is_set()


def test_process_frames_failure_ends_speaking_state():
    from src.avatars.base import BaseAvatar

    async def run():
        quit_event = threading.Event()
        avatar = BaseAvatar.__new__(BaseAvatar)
        avatar.config = SimpleNamespace(sessionid=7, video=SimpleNamespace(max_height=0))
        avatar.res_frame_queue = queue.Queue()
        avatar.frame_list_cycle = [np.zeros((32, 32, 3), dtype=np.uint8)]
        avatar.custom_index = {}
        avatar.custom_img_cycle = {}
        avatar.speaking = False
        avatar.accepts_media = lambda *_a: True
        avatar.mark_stage_end = lambda *_a: None
        avatar.paste_back_frame = lambda _frame, _idx: np.zeros((32, 32, 3), np.uint8)
        avatar.record_audio_data = lambda _frame: None
        failures = []

        def record_video_data(_frame):
            failures.append(avatar.speaking)
            quit_event.set()
            raise RuntimeError("encoder exploded")

        avatar.record_video_data = record_video_data
        speech = [(np.zeros(320, np.float32), 0, None)] * 2
        avatar.res_frame_queue.put((np.zeros((32, 32, 3), np.uint8), 0, speech))

        class Track:
            async def enqueue(self, frame, eventpoint=None):
                return True

        await asyncio.wait_for(asyncio.to_thread(
            avatar.process_frames, quit_event, asyncio.get_running_loop(), Track(), Track()), 2)
        assert failures == [True]
        assert avatar.speaking is False

    asyncio.run(run())
