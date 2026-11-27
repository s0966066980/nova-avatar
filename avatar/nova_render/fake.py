# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A fixed-frame avatar engine for tests: no model weights, no GPU, no avatar files.

Select it with ``model.type: fake``. It is deliberately absent from the
console's engine list (``catalog.ENGINE_META``).

It renders the way a real engine does at the media level, so the core's turn,
barge-in and handoff behavior can be exercised against it. Reply PCM is the
clock: every 20 ms frame goes out unchanged with its eventpoint, one picture
goes out for every two audio frames (tagged with the turn it shows) and
silence plus the fixed picture fill the gaps. Only the picture is fake: the
mouth never moves. Media is fenced to the current turn at the same stages as
MuseTalk's (``avatar_audio_enqueue``, ``avatar_audio_consume`` and the result
consumer in ``BaseAvatar``), ``flush_talk`` drops queued reply media, and
``bind_profile`` bumps the asset epoch.
"""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from queue import Queue
from threading import Event, RLock, Thread
from typing import Any, Optional

import numpy as np

from nova_contracts.avatar import STAGE_FRAME
from nova_render.base import BaseAvatar, drain_media_queue, put_until_quit

# BGR; the picture every frame of the fake avatar shows.
FAKE_FRAME_COLOR = (64, 128, 192)

SAMPLE_RATE = 16000
# 20 ms audio frames per 25 fps picture.
AUDIO_FRAMES_PER_PICTURE = 2
# The longest the renderer holds idle media for reply PCM the core says is on the way.
MAX_PENDING_AUDIO_WAIT_SECONDS = 0.20
# The first read of a batch waits this long for reply PCM before idling.
AUDIO_POLL_SECONDS = 0.01


@dataclass(frozen=True)
class FakeModel:
    """The loaded engine; the fake has no weights, so this holds nothing."""


class _FixedFrames:
    """The avatar's source frames: one picture, handed out as a fresh copy each time."""

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    def __len__(self) -> int:
        return 1

    def __getitem__(self, _index: int) -> np.ndarray:
        # The render loop draws on the frame it gets.
        return self._frame.copy()


@dataclass(frozen=True)
class FakeAssets:
    """One avatar's assets: the fixed picture."""

    frames: _FixedFrames


def load_model() -> FakeModel:
    return FakeModel()


def load_avatar(avatar_id: str) -> FakeAssets:
    picture = np.full((STAGE_FRAME.height, STAGE_FRAME.width, 3), FAKE_FRAME_COLOR, np.uint8)
    return FakeAssets(_FixedFrames(picture))


class FakeAudioStream:
    """Reply PCM waiting to be rendered, with the fence checked as it is taken."""

    def __init__(self, parent: BaseAvatar, chunk: int) -> None:
        self._parent = parent
        self._chunk = chunk
        self.queue: Queue = Queue()

    def put_audio_frame(self, samples: np.ndarray, eventpoint: dict) -> bool:
        self.queue.put_nowait((samples, eventpoint))
        return True

    def flush_talk(self) -> None:
        drain_media_queue(self.queue)

    def take(self, count: int) -> list[tuple[np.ndarray, int, Optional[dict]]]:
        """``count`` frames as ``(samples, kind, eventpoint)``: kind 0 reply PCM, 1 idle silence."""
        batch: list[tuple[np.ndarray, int, Optional[dict]]] = []
        block = True
        while len(batch) < count:
            try:
                samples, eventpoint = self.queue.get(block=block, timeout=AUDIO_POLL_SECONDS if block else None)
            except queue.Empty:
                batch.append((np.zeros(self._chunk, np.float32), 1, None))
                block = False
                continue
            block = False
            if not self._parent.accepts_media(eventpoint, "avatar_audio_consume"):
                self._parent.record_stale_drop("avatar_audio_consume", "stale_generation")
                continue
            batch.append((samples, 0, eventpoint))
        return batch


class FakeAvatarRenderer(BaseAvatar):
    """One conversation's renderer of the fake engine."""

    result_poll_seconds = 0.05

    def __init__(self, config: Any, model: FakeModel, assets: FakeAssets) -> None:
        super().__init__(config)
        self._assets_lock = RLock()
        self._asset_epoch = 0
        self.idx = 0
        self.frame_list_cycle = assets.frames
        self.res_frame_queue: Queue = Queue(maxsize=8)
        self.audio_stream = FakeAudioStream(self, self.chunk)
        # How long one picture takes; tests shorten it to render faster than real time.
        self.step_seconds = AUDIO_FRAMES_PER_PICTURE * self.chunk / SAMPLE_RATE

    def paste_back_frame(self, _prediction: Any, idx: int) -> np.ndarray:
        """The picture of a speaking frame: the fixed one, as the mouth never moves."""
        return self.frame_list_cycle[idx]

    def bind_profile(self, config: Any, assets: FakeAssets) -> None:
        """Swap to another avatar's assets; the tracks and media clock stay."""
        self.flush_talk()
        with self._assets_lock:
            self._asset_epoch += 1
            config.sessionid = self.sessionid
            self.config = config
            self.frame_list_cycle = assets.frames
            self.idx = 0

    def render(self, quit_event: Any, loop: Any = None, audio_track: Any = None,
               video_track: Any = None) -> None:
        self.init_customindex()
        process_quit = Event()
        processor = Thread(target=self.process_frames,
                           args=(process_quit, loop, audio_track, video_track))
        processor.start()
        try:
            self._produce(quit_event)
        finally:
            # Stop the consumer even when it waits on a track nobody drains.
            quit_event.set()
            process_quit.set()
            processor.join()
            self.speaking = False

    def _produce(self, quit_event: Any) -> None:
        due = time.monotonic()
        held_since: Optional[float] = None
        while not quit_event.is_set():
            if self._holds_for_pending_audio(held_since := self._hold_start(held_since)):
                quit_event.wait(AUDIO_POLL_SECONDS)
                continue
            held_since = None
            with self._assets_lock:
                epoch = self._asset_epoch
                idx = self.idx
                self.idx = (idx + 1) % len(self.frame_list_cycle)
            batch = self.audio_stream.take(AUDIO_FRAMES_PER_PICTURE)
            if not put_until_quit(self.res_frame_queue, (None, idx, batch, epoch), quit_event):
                return
            # Pace in real time, so idle media does not run ahead of a consumer without backpressure.
            due += self.step_seconds
            now = time.monotonic()
            if due > now:
                quit_event.wait(due - now)
            else:
                due = now

    def _hold_start(self, held_since: Optional[float]) -> Optional[float]:
        """When the current hold for pending reply PCM began, or None when not holding."""
        short = self.audio_stream.queue.qsize() < AUDIO_FRAMES_PER_PICTURE
        if not (short and self.has_pending_audio()):
            return None
        return time.monotonic() if held_since is None else held_since

    @staticmethod
    def _holds_for_pending_audio(held_since: Optional[float]) -> bool:
        return held_since is not None and time.monotonic() - held_since < MAX_PENDING_AUDIO_WAIT_SECONDS
