# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Fragment prefetch shared by the engines that synthesize a whole fragment at once.

While fragment N is emitted and plays, a synthesis thread already turns
fragment N+1 into PCM and holds it (at most ``MAX_HELD_FRAGMENTS``), so the next
fragment follows without waiting for synthesis. ``flush_talk`` bumps an epoch
under the same lock that guards the held fragments and the queue reads: held and
in-flight fragments of an older epoch are dropped, never emitted. A fragment is
emitted through ``TurnPCMEmitter``, so the fragment events and the media fence
(ADR 0007) are the same for every engine built on this class.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from queue import Empty
from typing import Callable

import numpy as np

from nova_tts.base import BaseTTS, State
from nova_tts.pcm_emitter import TurnPCMEmitter
from nova_core.utils.logging import logger

# Fragments synthesised and held ahead of the one being emitted. Synthesis runs
# far faster than real time, so one is enough to hide it behind playback.
MAX_HELD_FRAGMENTS = 1


@dataclass
class _HeldFragment:
    """A synthesised fragment waiting for its turn to be emitted."""

    msg: tuple[str, dict]
    samples: np.ndarray | None
    error: Exception | None = None


class PrefetchingTTS(BaseTTS):
    """An engine that synthesizes one fragment at a time and prefetches the next.

    A subclass implements ``_synthesize_fragment``; everything after it (the
    queue, the epoch, the playback fence, the events) lives here.
    """

    LOG_NAME = "tts"

    def __init__(self, config, sink):
        super().__init__(config, sink)
        # Guards the held fragments, the epoch and the synthesis thread's queue reads.
        self._cv = threading.Condition()
        self._held: deque[_HeldFragment] = deque()
        self._epoch = 0
        self._synthesizing = False

    def _synthesize_fragment(
        self, text: str, textevent: dict, alive: Callable[[], bool] | None = None
    ) -> np.ndarray:
        """The fragment's 16 kHz float32 PCM; ``alive`` turns False once it is cancelled."""
        raise NotImplementedError

    def _new_emitter(self, text: str, textevent: dict, current: Callable[[], bool]) -> TurnPCMEmitter:
        """The emitter of one fragment; it stops handing out frames once ``current`` is False."""
        return TurnPCMEmitter(self, text, textevent, chunk_guard=lambda _sequence: current())

    def txt_to_audio(self, msg: tuple[str, dict]) -> None:
        """Synthesize and emit one fragment now (no prefetch); raises when it fails."""
        text, textevent = msg
        try:
            started_at = time.perf_counter()
            samples = self._synthesize_fragment(text, textevent)
            self._emit_samples(text, textevent, samples, started_at)
        except Exception:
            logger.exception(self.LOG_NAME)
            self.notify_fragment_synthesis_failed(textevent, "tts_exhausted_before_audio")
            raise

    # -- prefetch: one synthesis thread feeds the emitting thread ---------------------

    def put_msg_txt(self, msg: str, datainfo: dict | None = None) -> None:
        super().put_msg_txt(msg, datainfo)
        with self._cv:
            self._cv.notify_all()

    def flush_talk(self) -> None:
        """Drop queued text, held fragments and the in-flight synthesis of the old turn."""
        with self._cv:
            super().flush_talk()
            self._epoch += 1
            self._held.clear()
            self._cv.notify_all()

    def has_pending_work(self) -> bool:
        with self._cv:
            return super().has_pending_work() or self._synthesizing or bool(self._held)

    def process_tts(self, quit_event) -> None:
        synthesis = threading.Thread(
            target=self._synthesis_loop, args=(quit_event,), name="matcha-synthesis", daemon=True
        )
        synthesis.start()
        try:
            self._emission_loop(quit_event)
        finally:
            self.state = State.PAUSE
            with self._cv:
                self._held.clear()
                self._cv.notify_all()
            synthesis.join(timeout=5)
            logger.info("ttsreal thread stop")

    def _synthesis_loop(self, quit_event) -> None:
        """Turn queued text into held fragments, at most ``MAX_HELD_FRAGMENTS`` ahead."""
        while not quit_event.is_set():
            with self._cv:
                msg = None
                if len(self._held) < MAX_HELD_FRAGMENTS:
                    # Read the queue under the lock flush_talk holds, so a message
                    # can never be paired with the epoch of the turn after it.
                    try:
                        msg = self.msgqueue.get_nowait()
                    except Empty:
                        msg = None
                if msg is None:
                    self._cv.wait(0.1)
                    continue
                epoch = self._epoch
                self.state = State.RUNNING
                self._synthesizing = True
            held = self._synthesize_held(msg, lambda: self._epoch == epoch)
            with self._cv:
                self._synthesizing = False
                if epoch == self._epoch:
                    self._held.append(held)
                self._cv.notify_all()

    def _synthesize_held(self, msg: tuple[str, dict], alive: Callable[[], bool]) -> _HeldFragment:
        text, textevent = msg
        try:
            return _HeldFragment(msg, self._synthesize_fragment(text, textevent, alive))
        except Exception as exc:
            logger.exception(self.LOG_NAME)
            # Reported when the fragment's turn in the order comes up, not now:
            # the fragment before it may still be playing.
            return _HeldFragment(msg, None, exc)

    def _emission_loop(self, quit_event) -> None:
        while not quit_event.is_set():
            with self._cv:
                if not self._held:
                    self._cv.wait(0.1)
                    continue
                held = self._held.popleft()
                epoch = self._epoch
                self._synthesis_active.set()
                self._cv.notify_all()
            text, textevent = held.msg
            if held.error is not None:
                self.notify_fragment_synthesis_failed(textevent, "tts_exhausted_before_audio")
            else:
                try:
                    self._emit_samples(text, textevent, held.samples, time.perf_counter(), epoch)
                except Exception:
                    logger.exception(self.LOG_NAME)
                    self.notify_fragment_synthesis_failed(textevent, "tts_exhausted_before_audio")
            self._settle(textevent, epoch, quit_event)

    def _settle(self, eventpoint: dict, epoch: int, quit_event) -> None:
        """Wait for the emitted fragment to finish playing, unless another is ready.

        A held fragment is emitted at once: the bounded playback queue paces it,
        so it follows the current one without a gap. ``_synthesis_active`` stays
        set until nothing is left to say.
        """
        while not quit_event.is_set():
            with self._cv:
                if self._epoch != epoch:
                    break
                if self._held:
                    return
                idle = not self._synthesizing and self.msgqueue.empty()
            if idle and self._playback_ended(eventpoint):
                break
            time.sleep(0.01)
        self._synthesis_active.clear()

    def _playback_ended(self, eventpoint: dict) -> bool:
        if not eventpoint.get("turn_id"):
            return True
        ended = getattr(self.sink, "fragment_playback_ended", None)
        return bool(ended(eventpoint)) if callable(ended) else True

    def _turn_accepted(self, textevent: dict) -> bool:
        """Whether the fragment's turn is still the live one (ADR 0007 fence)."""
        accepts = getattr(self.sink, "accepts_media", None)
        if not callable(accepts) or not textevent.get("turn_id"):
            return True
        return bool(accepts(textevent, "tts_held_fragment"))

    def _emit_samples(
        self,
        text: str,
        textevent: dict,
        samples: np.ndarray | None,
        started_at: float,
        epoch: int | None = None,
    ) -> None:
        """Emit synthesized PCM as 20 ms frames; nothing of an older epoch or turn is played."""

        def current() -> bool:
            return (
                self.state == State.RUNNING
                and (epoch is None or self._epoch == epoch)
                and self._turn_accepted(textevent)
            )

        if not current():
            return
        if samples is None or not samples.size:
            self.notify_fragment_synthesis_failed(textevent, "tts_empty_audio")
            return
        emitter = self._new_emitter(text, textevent, current)
        logged = False

        def note_first_audio() -> None:
            nonlocal logged
            if not logged and emitter.emitted:
                logged = True
                logger.info("%s first audio:%.4fs", self.LOG_NAME, time.perf_counter() - started_at)

        slice_size = max(self.chunk * 4, 1280)
        for offset in range(0, samples.size, slice_size):
            if not current() or emitter.cancelled:
                return
            emitter.feed_pcm(samples[offset : offset + slice_size])
            note_first_audio()
        if current() and not emitter.cancelled:
            emitter.finish_pcm()
            note_first_audio()
