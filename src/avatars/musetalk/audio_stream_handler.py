# Portions derived from MuseTalk.
# Copyright (c) 2024 Tencent Music Entertainment Group.
# Licensed under the MIT License.
# Modified by HongXian0903 for integration with Nova Avatar, 2026.
# See third_party/licenses/MuseTalk-LICENSE.txt.

"""MuseTalk 音訊流處理器 - 使用 Whisper 提取音訊特徵"""
import time
import numpy as np
from collections import deque
from dataclasses import dataclass
from threading import Lock, RLock
from typing import Any

import queue
from queue import Queue
from src.avatars.audio_stream_handler import BaseAudioStreamHandler
from src.avatars.musetalk.whisper.audio2feature import Audio2Feature

# Matches MuseTalkConfig.max_tts_audio_wait_seconds; the parent avatar's
# configured value takes precedence.
DEFAULT_SPEECH_RUNWAY_WAIT_SECONDS = 0.35


def _turn_key(eventpoint) -> tuple | None:
    if isinstance(eventpoint, dict) and eventpoint.get("turn_id"):
        return eventpoint["turn_id"], eventpoint.get("generation")
    return None


@dataclass(frozen=True)
class MuseInferenceBatch:
    """One atomic MuseTalk feature batch and its paired 20 ms audio frames."""

    features: Any
    audio_frames: tuple[tuple[np.ndarray, int, dict | None], ...]
    batch_size: int | None = None


class MuseAudioStreamHandler(BaseAudioStreamHandler):
    """Whisper 音訊特徵提取器
    
    用於 MuseTalk Avatar 模型，提取 Whisper 音訊特徵。
    """
    def __init__(self, config, parent, audio_processor: Audio2Feature):
        super().__init__(config, parent)
        self.audio_processor = audio_processor
        self.queue = Queue(maxsize=max(1, round(self.fps * 2.0)))
        # MuseTalk inference runs in threads in this process.  A thread queue
        # avoids multiprocessing pipe/pickle overhead for numpy feature data.
        self.feat_queue = Queue(maxsize=2)
        self.output_queue = Queue()
        self._paired_audio_frames = deque()
        self._paired_audio_lock = Lock()
        self._context_lock = RLock()
        self._context_epoch = 0
        # A short first batch gets the first mouth/audio frame onto WebRTC
        # without waiting for the steady-state model batch to fill.
        self.startup_batch_size = max(1, min(self.batch_size, 4))
        self._startup_batch_emitted = False
        self._speech_batch_emitted = False
        # Reply turn of the last emitted speech batch; a new turn's first
        # batch is startup-sized and gets its own lookahead runway.
        self._speech_turn = None
        self._runway_wait_started_at = None

    @property
    def startup_batch_emitted(self) -> bool:
        return self._startup_batch_emitted

    def first_speech_batch_pending(self) -> bool:
        """Whether queued reply PCM starts a turn with no speech batch yet."""
        with self.queue.mutex:
            head = self.queue.queue[0][1] if self.queue.queue else None
        turn = _turn_key(head)
        return turn is not None and (
            turn != self._speech_turn or not self._speech_batch_emitted
        )

    def _runway_wait_expired(self) -> bool:
        now = time.perf_counter()
        if self._runway_wait_started_at is None:
            self._runway_wait_started_at = now
        limit = getattr(self.parent, "max_tts_audio_wait_seconds",
                        DEFAULT_SPEECH_RUNWAY_WAIT_SECONDS)
        return now - self._runway_wait_started_at >= limit

    def warm_up(self):
        """Prime silent context without consuming any incoming reply PCM."""
        with self._context_lock:
            self._prime_context()

    def _prime_context(self):
        offset = self.av_offset_frames()
        self.frames = [
            np.zeros(self.chunk, dtype=np.float32)
            for _ in range(self.stride_left_size + self.stride_right_size)
        ]
        paired_count = max(0, -offset) + self.stride_right_size - max(0, offset)
        paired = [
            (np.zeros(self.chunk, dtype=np.float32), 1, None)
            for _ in range(paired_count)
        ]
        with self._paired_audio_lock:
            self._paired_audio_frames.clear()
            self._paired_audio_frames.extend(paired)

    def flush_talk(self):
        with self._context_lock:
            self._context_epoch += 1
            super().flush_talk()
            self._prime_context()
            self._startup_batch_emitted = False
            self._speech_batch_emitted = False
            self._speech_turn = None
            self._runway_wait_started_at = None

    def _refresh_idle_lookahead(self, effective_batch_size):
        """Replace idle lookahead with ready PCM before the first speech batch.

        Retaining ten idle context frames leaves only six spoken PCM frames
        in a steady-state batch. That 120 ms runway cannot cover the next
        model call. Re-prime only untagged idle context, preserving the left
        history and every spoken frame's feature alignment and order.
        """
        right = self.stride_right_size
        if right <= 0 or self.av_offset_frames() != 0:
            return True
        with self._paired_audio_lock:
            idle_context = (
                len(self._paired_audio_frames) == right
                and all(kind == 1 and event is None
                        for _frame, kind, event in self._paired_audio_frames)
            )
        if not idle_context or len(self.frames) < right:
            return True
        with self.queue.mutex:
            if not self.queue.queue:
                return True
            queued = len(self.queue.queue)
            first_frame, first_event = self.queue.queue[0]
            starts_speech = (
                isinstance(first_event, dict)
                and (first_event.get("status") == "start" or first_event.get("fragment_start"))
            ) or (first_frame.size > 0 and float(np.max(np.abs(first_frame))) > 1e-4)
            complete_short_fragment = any(
                isinstance(event, dict)
                and (event.get("fragment_end") or event.get("status") == "end")
                for _frame, event in self.queue.queue
            )
        if not starts_speech:
            return True
        if queued < right + effective_batch_size * 2:
            tts = getattr(self.parent, "tts", None)
            pending = getattr(tts, "has_pending_work", None)
            # A streaming first packet may be smaller than the lookahead.
            # Keep it untouched until a full runway is ready. Short completed
            # utterances and later speech batches must still drain promptly,
            # and a stalled stream must not freeze idle video.
            return (self._speech_batch_emitted or complete_short_fragment
                    or not callable(pending) or not pending()
                    or self._runway_wait_expired())
        self._runway_wait_started_at = None
        with self._paired_audio_lock:
            self._paired_audio_frames.clear()
        self.frames = self.frames[:-right]
        for audio_frame, kind, event in self.get_audio_frames(right):
            self.frames.append(audio_frame)
            with self._paired_audio_lock:
                self._paired_audio_frames.append((audio_frame, kind, event))
        return True

    def _collect_batch(self):
        """Snapshot PCM and context together; feature extraction may be slow."""
        first_speech = self.first_speech_batch_pending()
        if first_speech:
            self._speech_batch_emitted = False
        # The first speech batch of each turn does not wait for a full batch.
        effective_batch_size = (
            self.batch_size
            if self._startup_batch_emitted and not first_speech
            else self.startup_batch_size
        )
        if not self._refresh_idle_lookahead(effective_batch_size):
            return False
        for audio_frame, type, eventpoint in self.get_audio_frames(effective_batch_size * 2):
            self.frames.append(audio_frame)
            item = (audio_frame, type, eventpoint)
            with self._paired_audio_lock:
                self._paired_audio_frames.append(item)
        
        if len(self.frames) <= self.stride_left_size + self.stride_right_size:
            return
        
        with self._paired_audio_lock:
            if len(self._paired_audio_frames) < effective_batch_size * 2:
                return
            paired_audio_frames = tuple(
                self._paired_audio_frames.popleft()
                for _ in range(effective_batch_size * 2)
            )

        # Static/custom audio does not drive a mouth pose.  Preserve the
        # paired timeline but bypass Whisper feature extraction entirely.
        all_idle = all(
            frame_type != 0
            or frame.size == 0
            or float(np.max(np.abs(frame))) <= 1e-4
            for frame, frame_type, _event in paired_audio_frames
        )
        inputs = None if all_idle else np.concatenate(self.frames)
        context_size = self.stride_left_size + self.stride_right_size
        self.frames = self.frames[-context_size:] if context_size else []
        return self._context_epoch, effective_batch_size, paired_audio_frames, inputs

    def run_step(self):
        """Extract features without restoring context invalidated by a flush."""
        with self._context_lock:
            collected = self._collect_batch()
        if collected is False or collected is None:
            return collected
        epoch, effective_batch_size, paired_audio_frames, inputs = collected
        if inputs is None:
            whisper_chunks = ()
        else:
            whisper_feature = self.audio_processor.audio2feat(inputs)
            whisper_chunks = self.audio_processor.feature2chunks(
                feature_array=whisper_feature,
                fps=self.fps / 2,
                batch_size=effective_batch_size,
                start=self.stride_left_size / 2
            )
        #print(f"whisper_chunks len:{len(whisper_chunks)},self.audio_feats len:{len(self.audio_feats)},self.output_queue len:{self.output_queue.qsize()}")
        #self.audio_feats = self.audio_feats[-(self.stride_left_size + self.stride_right_size):]
        batch = MuseInferenceBatch(
            features=whisper_chunks,
            audio_frames=paired_audio_frames,
            batch_size=effective_batch_size,
        )
        quit_event = getattr(self, "quit_event", None)
        while quit_event is None or not quit_event.is_set():
            with self._context_lock:
                if epoch != self._context_epoch:
                    return False
                try:
                    self.feat_queue.put_nowait(batch)
                    self._startup_batch_emitted = True
                    if any(kind == 0 for _frame, kind, _event in paired_audio_frames):
                        self._speech_batch_emitted = True
                        self._runway_wait_started_at = None
                        turns = [_turn_key(event) for _frame, _kind, event in paired_audio_frames]
                        self._speech_turn = next(
                            (turn for turn in reversed(turns) if turn is not None), None)
                    break
                except queue.Full:
                    pass
            # Release the context lock while applying backpressure so an
            # interrupt can drain the queue and invalidate this pending batch.
            time.sleep(0.01)
        else:
            return
        mark_stage = getattr(self.parent, "mark_stage_end", None)
        if callable(mark_stage) and any(
            isinstance(eventpoint, dict) and eventpoint.get("turn_id")
            for _frame, _frame_type, eventpoint in paired_audio_frames
        ):
            mark_stage("musetalk_first_batch")
