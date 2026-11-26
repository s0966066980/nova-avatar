# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""Shared incremental silence trimmer and turn-aware 20 ms PCM frame emitter."""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable, Optional

import numpy as np

from src.tts.base import State

ACTIVITY_THRESHOLD = 1e-4
ONSET_THRESHOLD = 1e-5
FRAME_SECONDS = 0.01
MAX_PREROLL_SECONDS = 0.16
SILENCE_GUARD_SECONDS = 0.04
TRAILING_PAUSE_SECONDS = 0.12


class DirectFrameSink:
    """Push emitted PCM chunks straight to the core's audio sink."""

    def __init__(self, sink) -> None:
        self.sink = sink
        self.first_pcm = threading.Event()

    def bind(self) -> None:
        return None

    def emit(self, samples: np.ndarray, eventpoint: dict) -> None:
        self.first_pcm.set()
        self.sink.put_audio_frame(samples, eventpoint)

    async def wait_for_space(self) -> None:
        return None

    def release(self) -> None:
        return None

    def cancel(self) -> None:
        return None


class StreamingSilenceTrimmer:
    """Trim leading padding while preserving soft speech onset and natural pauses."""

    def __init__(
        self,
        sample_rate: int,
        threshold: float = ACTIVITY_THRESHOLD,
        leading_pause_seconds: float = SILENCE_GUARD_SECONDS,
        trailing_pause_seconds: float = TRAILING_PAUSE_SECONDS,
        activity_threshold: Optional[float] = None,
        onset_threshold: float = ONSET_THRESHOLD,
        max_preroll_seconds: float = MAX_PREROLL_SECONDS,
        silence_guard_seconds: Optional[float] = None,
    ):
        self.frame_size = max(1, int(sample_rate * FRAME_SECONDS))
        self.activity_threshold = (
            float(threshold) if activity_threshold is None else float(activity_threshold)
        )
        self.onset_threshold = float(onset_threshold)
        guard_seconds = (
            leading_pause_seconds
            if silence_guard_seconds is None
            else silence_guard_seconds
        )
        self.silence_guard_frames = max(0, round(guard_seconds / FRAME_SECONDS))
        self.max_preroll_frames = max(1, round(max_preroll_seconds / FRAME_SECONDS))
        self.trailing_frames = max(0, round(trailing_pause_seconds / FRAME_SECONDS))
        self._remainder = np.empty(0, dtype=np.float32)
        self._preroll: deque[np.ndarray] = deque()
        self._trailing: list[np.ndarray] = []
        self._started = False
        self.retained_preroll_samples = 0

    @property
    def started(self) -> bool:
        return self._started

    @property
    def threshold(self) -> float:
        return self.activity_threshold

    def _frame_rms(self, block: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))

    def _trim_preroll(self) -> None:
        while len(self._preroll) > self.max_preroll_frames:
            self._preroll.popleft()
        leading_padding = 0
        for frame in self._preroll:
            if self._frame_rms(frame) <= self.onset_threshold:
                leading_padding += 1
            else:
                break
        drop = max(0, leading_padding - self.silence_guard_frames)
        for _ in range(drop):
            self._preroll.popleft()

    def _flush_preroll(self) -> list[np.ndarray]:
        output = list(self._preroll)
        self.retained_preroll_samples = sum(frame.size for frame in output)
        self._preroll.clear()
        return output

    def _process_block(self, block: np.ndarray) -> list[np.ndarray]:
        rms = self._frame_rms(block)
        output = []
        if not self._started:
            if rms > self.activity_threshold:
                self._started = True
                output.extend(self._flush_preroll())
                output.append(block)
            else:
                self._preroll.append(block)
                self._trim_preroll()
            return output

        if rms > self.activity_threshold:
            output.extend(self._trailing)
            self._trailing.clear()
            output.append(block)
        else:
            self._trailing.append(block)
        return output

    def feed(self, samples: np.ndarray) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if self._remainder.size:
            samples = np.concatenate((self._remainder, samples))
        complete = (samples.size // self.frame_size) * self.frame_size
        self._remainder = samples[complete:].copy()
        output = []
        for offset in range(0, complete, self.frame_size):
            output.extend(self._process_block(samples[offset : offset + self.frame_size]))
        return (
            np.concatenate(output)
            if output
            else np.empty(0, dtype=np.float32)
        )

    def finish(self) -> np.ndarray:
        output = []
        partial_block = None
        partial_size = 0
        if self._remainder.size:
            partial_size = self._remainder.size
            partial_block = np.pad(
                self._remainder,
                (0, self.frame_size - self._remainder.size),
            )
            output.extend(self._process_block(partial_block))
            self._remainder = np.empty(0, dtype=np.float32)
        if self._started:
            output.extend(self._trailing[: self.trailing_frames])
        self._trailing.clear()
        if partial_block is not None:
            output = [
                item[:partial_size] if item is partial_block else item
                for item in output
            ]
        return (
            np.concatenate(output)
            if output
            else np.empty(0, dtype=np.float32)
        )


class TurnPCMEmitter:
    """Buffer float32 PCM samples and emit fixed-size frames with turn eventpoints."""

    def __init__(
        self,
        owner,
        text: str,
        textevent: dict,
        *,
        start_event_sent: bool = False,
        start_media_sequence: int = 0,
        chunk_guard: Optional[Callable[[int], bool]] = None,
        frame_sink=None,
    ):
        self.owner = owner
        self.text = text
        self.textevent = textevent
        self.frame_sink = frame_sink or DirectFrameSink(owner.sink)
        self.trimmer = StreamingSilenceTrimmer(owner.sample_rate)
        self.samples = np.empty(0, dtype=np.float32)
        self.pending_chunk = None
        self.emitted_chunks = 0
        self.emitted_samples = 0
        self.start_event_sent = start_event_sent
        self.media_sequence = start_media_sequence
        self.chunk_guard = chunk_guard
        self.cancelled = False

    @property
    def emitted(self) -> bool:
        return self.emitted_chunks > 0

    def _emit(self, samples: np.ndarray, *, final: bool = False) -> None:
        if self.owner.state != State.RUNNING:
            return
        if self.chunk_guard is not None and not self.chunk_guard(self.media_sequence):
            self.cancelled = True
            return
        turn_aware = {
            "turn_id",
            "generation",
            "fragment_sequence",
        }.issubset(self.textevent)
        eventpoint = dict(self.textevent) if turn_aware else {}
        if turn_aware:
            eventpoint["media_sequence"] = self.media_sequence
            eventpoint["fragment_start"] = not self.start_event_sent
            eventpoint["fragment_end"] = final
        if not self.start_event_sent:
            eventpoint.update({"status": "start"})
            if not turn_aware:
                eventpoint.update({"text": self.text, **self.textevent})
            self.start_event_sent = True
        elif final:
            eventpoint.update({"status": "end"})
            if not turn_aware:
                eventpoint.update({"text": self.text, **self.textevent})
        first_fragment = self.textevent.get("fragment_sequence", 0) == 0
        mark_stage = getattr(self.owner.sink, "mark_stage_end", None)
        if (
            self.emitted_chunks == 0
            and first_fragment
            and callable(mark_stage)
            and self.textevent.get("turn_id")
        ):
            mark_stage("tts_pcm_available")
        self.frame_sink.emit(samples, eventpoint)
        if self.emitted_chunks == 0:
            if first_fragment and callable(mark_stage) and self.textevent.get("turn_id"):
                mark_stage("tts_first_pcm")
        self.emitted_chunks += 1
        self.emitted_samples += samples.size
        self.media_sequence += 1

    def _queue_samples(self, samples: np.ndarray) -> None:
        if not samples.size:
            return
        self.samples = np.concatenate((self.samples, samples))
        while self.samples.size >= self.owner.chunk:
            chunk = self.samples[: self.owner.chunk].copy()
            self.samples = self.samples[self.owner.chunk :]
            if self.pending_chunk is not None:
                self._emit(self.pending_chunk)
            self.pending_chunk = chunk

    def feed_pcm(self, samples: np.ndarray) -> None:
        self._queue_samples(self.trimmer.feed(samples))

    def finish_pcm(self) -> None:
        self._queue_samples(self.trimmer.finish())
        if self.samples.size:
            padded = np.pad(
                self.samples,
                (0, self.owner.chunk - self.samples.size),
            )
            if self.pending_chunk is not None:
                self._emit(self.pending_chunk)
            self.pending_chunk = padded.astype(np.float32, copy=False)
            self.samples = np.empty(0, dtype=np.float32)
        if self.pending_chunk is not None:
            self._emit(self.pending_chunk, final=True)
            self.pending_chunk = None
