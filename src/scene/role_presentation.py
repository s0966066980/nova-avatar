# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Role presentation: the stage canvas that carries a role and its transitions.

The renderer composes every video frame through it while role composition is
on; the core directs a transition (which edge, when it starts) through
``AvatarRenderer``. Moved from ``src/profiles/media.py`` (ticket 07).
"""
from __future__ import annotations

import queue
import threading
import time

import cv2
import numpy as np

from nova_contracts.avatar import STAGE_FPS, STAGE_FRAME
from nova_contracts.common import ServiceError
from src.scene.service import chroma_composite, scene_service

WIDTH, HEIGHT, FPS = STAGE_FRAME.width, STAGE_FRAME.height, STAGE_FPS


class TransitionClipReader:
    """A small producer queue; a 30-second clip never becomes 750 raw frames."""
    def __init__(self, path, frames):
        self.frames = frames
        self.queue = queue.Queue(maxsize=3)
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.last = None
        self.last_index = -1
        self._next = None
        self.failed = False
        self.thread = threading.Thread(target=self._run, args=(path,), daemon=True,
                                       name="avatar-transition-video")
        self.thread.start()
        if not self.ready.wait(2) or self.failed:
            self.close()
            raise ServiceError("轉場影片暫時無法播放")

    def _run(self, path):
        capture = cv2.VideoCapture(str(path))
        try:
            for index in range(self.frames):
                if self.stop.is_set():
                    return
                ok, frame = capture.read()
                if not ok:
                    self.failed = True
                    return
                while not self.stop.is_set():
                    try:
                        self.queue.put((index, frame), timeout=.05)
                        self.ready.set()
                        break
                    except queue.Full:
                        continue
        finally:
            capture.release()
            self.ready.set()

    def frame(self, index):
        while True:
            if self._next is None:
                try:
                    self._next = self.queue.get_nowait()
                except queue.Empty:
                    break
            if self._next[0] > index:
                break
            self.last_index, self.last = self._next
            self._next = None
        return self.last

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)


def fit_frame(frame, background=None):
    height, width = frame.shape[:2]
    ratio = min(WIDTH / width, HEIGHT / height)
    resized = cv2.resize(frame, (max(1, round(width * ratio)), max(1, round(height * ratio))),
                         interpolation=cv2.INTER_AREA if ratio < 1 else cv2.INTER_LINEAR)
    canvas = background.copy() if background is not None else np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    y, x = (HEIGHT - resized.shape[0]) // 2, (WIDTH - resized.shape[1]) // 2
    canvas[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
    return canvas


class RolePresentation:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.last_raw = None
        self.transition = None
        self.marker = {}

    def begin(self, transition_id, edge, *, reader=None, started_at=None):
        with self.lock:
            self.close()
            self.transition = dict(id=transition_id, edge=dict(edge), reader=reader,
                                   started=self.clock() if started_at is None else started_at,
                                   previous=self.last_raw.copy() if self.last_raw is not None else None)

    def close(self):
        with self.lock:
            if self.transition and self.transition["reader"]:
                self.transition["reader"].close()
            self.transition = None
            self.marker = {}

    def compose(self, frame, *, green_screen):
        with self.lock:
            canvas = np.full((HEIGHT, WIDTH, 3), (0, 255, 0), np.uint8) if green_screen else None
            raw = fit_frame(frame, canvas)
            self.last_raw = raw
            background = scene_service.background_frame(WIDTH, HEIGHT)
            if background is None:
                background = np.full_like(raw, (0, 255, 0)) if green_screen else np.zeros_like(raw)
            current = chroma_composite(raw, background) if green_screen else raw
            transition = self.transition
            if not transition:
                return current
            if self.clock() < transition["started"]:
                # Keep the source visible while other peers finish binding.
                # Reading frame zero here exposes the clip before its common
                # start time, then makes it appear to play again at that time.
                self.marker = {}
                previous = transition["previous"]
                if previous is None:
                    return current
                return chroma_composite(previous, background) if green_screen else previous.copy()
            edge, reader = transition["edge"], transition["reader"]
            if reader is not None and reader.failed:
                reader.close()
                transition.update(reader=None, started=self.clock(),
                                  edge={"kind": "effect", "effect": "fade", "duration": .6})
                edge, reader = transition["edge"], None
            elapsed = max(0., self.clock() - transition["started"])
            duration = reader.frames / FPS if reader else edge.get("duration", .6)
            progress = min(1., elapsed / duration)
            completed = progress >= 1
            if reader and not reader.failed:
                requested = min(reader.frames - 1, int(elapsed * FPS))
                clip = reader.frame(requested)
                if clip is not None:
                    current = fit_frame(clip, background)
                completed = completed and reader.last_index >= reader.frames - 1
            else:
                previous = transition["previous"] if transition["previous"] is not None else raw
                effect = edge.get("effect", "fade")
                if effect == "fade":
                    old = chroma_composite(previous, background) if green_screen else previous
                    current = cv2.addWeighted(old, 1-progress, current, progress, 0)
                else:
                    old_canvas = np.full_like(raw, (0, 255, 0))
                    new_canvas = old_canvas.copy()
                    if effect in {"slide_left", "slide_right"}:
                        direction = -1 if effect == "slide_left" else 1
                        shift = round(WIDTH * progress) * direction
                        matrix = np.float32([[1, 0, shift], [0, 1, 0]])
                        old_canvas = cv2.warpAffine(previous, matrix, (WIDTH, HEIGHT), borderValue=(0,255,0))
                        matrix[0, 2] = shift - direction * WIDTH
                        new_canvas = cv2.warpAffine(raw, matrix, (WIDTH, HEIGHT), borderValue=(0,255,0))
                    else:
                        for source, target, scale in ((previous, old_canvas, 1-progress), (raw, new_canvas, progress)):
                            if scale > .001:
                                small = cv2.resize(source, (max(1, round(WIDTH*scale)), max(1, round(HEIGHT*scale))))
                                x, y = (WIDTH-small.shape[1])//2, (HEIGHT-small.shape[0])//2
                                target[y:y+small.shape[0], x:x+small.shape[1]] = small
                    current = chroma_composite(new_canvas, chroma_composite(old_canvas, background))
            self.marker = {"role_transition_id": transition["id"], "role_transition_end": completed}
            return current
