# Derived from Kedreamix/Linly-Talker-Stream.
# Copyright [Linly-talker-stream@kedreamix].
# Licensed under the Apache License, Version 2.0.
#
# Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

import asyncio
import json
import logging
import math
import threading
import time
from typing import Tuple, Dict, Optional, Set, Union
from av.frame import Frame
from av.packet import Packet
from av import AudioFrame
import fractions
import numpy as np

AUDIO_PTIME = 0.020  # 20ms audio packetization
VIDEO_CLOCK_RATE = 90000
VIDEO_PTIME = 0.040 #1 / 25  # 30fps
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK_RATE)
SAMPLE_RATE = 16000
AUDIO_TIME_BASE = fractions.Fraction(1, SAMPLE_RATE)
# Video may skip late frames after this stall. Audio does not use this
# threshold to catch up: any overdue audio frame rebases the wall clock.
MAX_PACING_LAG = 0.100
# Ignore tiny clock noise so every frame does not rebase, but never large
# enough to swallow a full 20 ms audio packet.
AUDIO_PACING_JITTER = 0.002
# Keep one paired video frame of idle runway.  A larger runway makes the first
# spoken PCM packet wait behind silence; zero runway risks an audio underrun
# while the matching video frame is pasted back.
MAX_MEDIA_BUFFER_SECONDS = 0.240
SPEECH_START_RUNWAY_SECONDS = VIDEO_PTIME

#from aiortc.contrib.media import MediaPlayer, MediaRelay
#from aiortc.rtcrtpsender import RTCRtpSender
from aiortc import (
    MediaStreamTrack,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
from logger import logger as mylogger


class _MediaPacingClock:
    """Shared wall-clock origin for one player's audio and video RTP tracks."""

    def __init__(self):
        self._start: Optional[float] = None
        self.rebase_count = 0

    def ensure_started(self, now: float) -> float:
        if self._start is None:
            self._start = now
        return self._start

    @property
    def start(self) -> float:
        if self._start is None:
            raise RuntimeError("media pacing clock has not started")
        return self._start

    def rebase(self, lag: float) -> None:
        self._start = self.start + lag
        self.rebase_count += 1


class PlayerStreamTrack(MediaStreamTrack):
    """
    A video track that returns an animated flag.
    """

    def __init__(
        self,
        player,
        kind,
        pacing_clock=None,
        media_guard=None,
        on_stale_drop=None,
    ):
        super().__init__()  # don't forget this!
        self.kind = kind
        self._player = player
        self._pacing_clock = pacing_clock or _MediaPacingClock()
        self._media_guard = media_guard
        self._on_stale_drop = on_stale_drop
        packet_time = VIDEO_PTIME if kind == "video" else AUDIO_PTIME
        self._packet_time = packet_time
        self._queue = asyncio.Queue(
            maxsize=max(1, round(MAX_MEDIA_BUFFER_SECONDS / packet_time))
        )
        self.timelist = [] #記錄最近包的時間戳
        self.current_frame_count = 0
        self._last_video_item = None
        self._last_video_release_at: Optional[float] = None
        self._last_audio_release_at: Optional[float] = None
        self._audio_late_release = False
        self.catch_up_burst_count = 0
        self.last_audio_lag_seconds = 0.0
        self.min_audio_release_interval_seconds: Optional[float] = None
        if self.kind == 'video':
            self.framecount = 0
            self.lasttime = time.perf_counter()
            self.totaltime = 0
    
    _timestamp: int

    @property
    def _start(self) -> float:
        return self._pacing_clock.start

    @property
    def max_buffer_frames(self) -> int:
        return self._queue.maxsize

    @property
    def max_buffer_duration(self) -> float:
        return self.max_buffer_frames * self._packet_time

    @property
    def buffered_duration(self) -> float:
        return self._queue.qsize() * self._packet_time

    def _event_is_current(self, eventpoint, stage: str) -> bool:
        if not (
            isinstance(eventpoint, dict)
            and eventpoint.get("turn_id")
            and self._media_guard is not None
        ):
            return True
        try:
            return bool(self._media_guard(eventpoint, stage))
        except Exception:
            mylogger.exception("media generation guard failed closed")
            return False

    def _record_stale_drop(self, reason: str = "stale_generation") -> None:
        if self._on_stale_drop is not None:
            self._on_stale_drop(f"webrtc_{self.kind}", reason)

    async def enqueue(self, frame, eventpoint=None) -> bool:
        """Apply media backpressure instead of accumulating stale idle frames."""
        if not self._event_is_current(eventpoint, f"webrtc_{self.kind}_enqueue"):
            self._record_stale_drop()
            return False
        if self.kind == "video" and self._queue.full():
            self._queue.get_nowait()
            self._record_stale_drop("late_video")
            self._queue.put_nowait((frame, eventpoint))
            return True
        await self._queue.put((frame, eventpoint))
        return True

    async def prepare_speech_start(self) -> None:
        if self._player is not None:
            await self._player.prepare_speech_start()

    def discard_stale_media(self) -> int:
        """Synchronously drain queued generations invalidated by cancellation."""
        kept = []
        discarded = 0
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if self._event_is_current(
                item[1],
                f"webrtc_{self.kind}_interrupt_drain",
            ):
                kept.append(item)
            else:
                discarded += 1
                self._record_stale_drop()
        for item in kept:
            self._queue.put_nowait(item)
        if (
            self.kind == "video"
            and self._last_video_item is not None
            and not self._event_is_current(
                self._last_video_item[1],
                "webrtc_video_repeat",
            )
        ):
            self._last_video_item = None
        return discarded

    async def next_timestamp(self) -> Tuple[int, fractions.Fraction]:
        if self.readyState != "live":
            raise Exception

        if self.kind == "video":
            packet_time = VIDEO_PTIME
            clock_rate = VIDEO_CLOCK_RATE
            time_base = VIDEO_TIME_BASE
        else:
            packet_time = AUDIO_PTIME
            clock_rate = SAMPLE_RATE
            time_base = AUDIO_TIME_BASE

        now = time.monotonic()
        late_release = False
        if hasattr(self, "_timestamp"):
            self._timestamp += int(packet_time * clock_rate)
            self.current_frame_count += 1
            deadline = self._start + self.current_frame_count * packet_time
            lag = now - deadline
            if self.kind == "audio":
                self.last_audio_lag_seconds = lag
                if lag > AUDIO_PACING_JITTER:
                    # Overdue audio is released immediately, then the shared
                    # wall-clock origin moves so the next frame is 20 ms later.
                    # RTP PTS stay monotonic; video must not call rebase().
                    self._pacing_clock.rebase(lag)
                    deadline = now
                    late_release = True
                    if lag > MAX_PACING_LAG:
                        mylogger.warning(
                            "[AVSync] audio pacing stalled %.0fms; rebased audio clock",
                            lag * 1000.0,
                        )
            elif lag > MAX_PACING_LAG:
                skipped = max(1, math.ceil(lag / packet_time))
                ticks = int(packet_time * clock_rate)
                self.current_frame_count += skipped
                self._timestamp += skipped * ticks
                deadline = self._start + self.current_frame_count * packet_time
                mylogger.warning(
                    "[AVSync] video pacing stalled %.0fms; skipped %d late frames",
                    lag * 1000.0,
                    skipped,
                )
            if self.kind == "video" and self._last_video_release_at is not None:
                # A short event-loop or inference stall used to leave video up
                # to 100 ms late.  Consecutive recv() calls then escaped with
                # no sleep and appeared as a brief speed-up / shake.  Keep a
                # hard wall-clock floor between displayed video frames even
                # when RTP timestamps need to catch up or skip.
                deadline = max(deadline, self._last_video_release_at + packet_time)
            wait = deadline - now
            if wait > 0:
                await asyncio.sleep(wait)
        else:
            self._pacing_clock.ensure_started(now)
            self._timestamp = 0
            self.timelist.append(self._start)
            mylogger.info("%s start:%f", self.kind, self._start)

        if self.kind == "video":
            self._last_video_release_at = time.monotonic()

        if self.kind == "audio":
            released_at = time.monotonic()
            if self._last_audio_release_at is not None:
                interval = released_at - self._last_audio_release_at
                if (
                    self.min_audio_release_interval_seconds is None
                    or interval < self.min_audio_release_interval_seconds
                ):
                    self.min_audio_release_interval_seconds = interval
                if self._audio_late_release and interval < AUDIO_PACING_JITTER:
                    self.catch_up_burst_count += 1
            self._last_audio_release_at = released_at
            self._audio_late_release = late_release
            notify_pacing = getattr(self._player, "notify_audio_pacing", None)
            if callable(notify_pacing):
                notify_pacing(
                    lag_seconds=self.last_audio_lag_seconds,
                    rebase_count=self._pacing_clock.rebase_count,
                    min_release_interval_seconds=self.min_audio_release_interval_seconds,
                    catch_up_burst_count=self.catch_up_burst_count,
                )

        return self._timestamp, time_base

    async def recv(self) -> Union[Frame, Packet]:        
        self._player._start(self)

        while True:
            try:
                if self.kind == "video" and self._last_video_item is not None:
                    frame,eventpoint = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=self._packet_time,
                    )
                else:
                    frame,eventpoint = await self._queue.get()
            except asyncio.TimeoutError:
                frame,eventpoint = self._last_video_item
            if not self._event_is_current(eventpoint, f"webrtc_{self.kind}_commit"):
                self._record_stale_drop()
                if self.kind == "video" and self._last_video_item == (frame, eventpoint):
                    self._last_video_item = None
                continue
            if frame is None:
                self.stop()
                raise Exception
            pts, time_base = await self.next_timestamp()
            # Pacing is an await boundary: an interrupt can advance the
            # generation after dequeue validation but before playback commit.
            if self._event_is_current(eventpoint, f"webrtc_{self.kind}_commit"):
                break
            self._record_stale_drop()
            if self.kind == "video" and self._last_video_item == (frame, eventpoint):
                self._last_video_item = None
        frame.pts = pts
        frame.time_base = time_base
        if self.kind == "video":
            self._last_video_item = (frame, eventpoint)

        # 每 5 秒回報一次「媒體時間 vs 牆鐘」。任一軌若在 _queue.get() 上餓死，
        # current_frame_count 會停住而牆鐘照走，該軌的 pts 就永久落後真實時間。
        # 把兩軌的 drift 相減，就是實際的音影像不同步量與方向。
        now = time.monotonic()
        if now - getattr(self, "_drift_logged_at", 0.0) >= 5.0:
            self._drift_logged_at = now
            rate = VIDEO_CLOCK_RATE if self.kind == "video" else SAMPLE_RATE
            media_s = pts / rate
            elapsed = now - self._start
            mylogger.info(
                "[AVSync] %-5s media=%8.3fs wall=%8.3fs drift=%+7.0fms qsize=%d",
                self.kind, media_s, elapsed, (elapsed - media_s) * 1000.0,
                self._queue.qsize(),
            )
        if eventpoint and self._player is not None:
            self._player.notify(eventpoint)
        if self._player is not None:
            rate = VIDEO_CLOCK_RATE if self.kind == "video" else SAMPLE_RATE
            self._player.notify_media_timing(self.kind, pts / rate)
        if self.kind == 'audio' and self._player is not None:
            try:
                samples = frame.to_ndarray().astype(np.float32, copy=False)
                active = bool(np.max(np.abs(samples))) if samples.size else False
            except Exception:
                active = False
            notify_audio_frame = getattr(self._player, "notify_audio_frame", None)
            if callable(notify_audio_frame):
                notify_audio_frame(eventpoint, active)
            self._player.notify_audio_activity(active)
        if self.kind == 'video':
            self.totaltime += (time.perf_counter() - self.lasttime)
            self.framecount += 1
            self.lasttime = time.perf_counter()
            if self.framecount==100:
                mylogger.info(f"------actual avg final fps:{self.framecount/self.totaltime:.4f}")
                self.framecount = 0
                self.totaltime=0
        return frame
    
    def stop(self):
        super().stop()
        # Drain & delete remaining frames
        while not self._queue.empty():
            item = self._queue.get_nowait()
            del item
        self._last_video_item = None
        if self._player is not None:
            self._player._stop(self)
            self._player = None

def player_worker_thread(
    quit_event,
    loop,
    container,
    audio_track,
    video_track
):
    container.render(quit_event,loop,audio_track,video_track)

class HumanPlayer:

    def __init__(
        self, avatar_stream, format=None, options=None, timeout=None, loop=False, decode=True,
        on_audio_activity=None,
        on_audio_frame=None,
        on_media_timing=None,
        on_audio_pacing=None,
        media_guard=None,
        on_stale_drop=None,
    ):
        self.__thread: Optional[threading.Thread] = None
        self.__thread_quit: Optional[threading.Event] = None

        # examine streams
        self.__started: Set[PlayerStreamTrack] = set()
        self.__audio: Optional[PlayerStreamTrack] = None
        self.__video: Optional[PlayerStreamTrack] = None

        pacing_clock = _MediaPacingClock()
        self.__audio = PlayerStreamTrack(
            self,
            kind="audio",
            pacing_clock=pacing_clock,
            media_guard=media_guard,
            on_stale_drop=on_stale_drop,
        )
        self.__video = PlayerStreamTrack(
            self,
            kind="video",
            pacing_clock=pacing_clock,
            media_guard=media_guard,
            on_stale_drop=on_stale_drop,
        )

        self.__container = avatar_stream
        self.__on_audio_activity = on_audio_activity
        self.__on_audio_frame = on_audio_frame
        self.__on_media_timing = on_media_timing
        self.__on_audio_pacing = on_audio_pacing
        self.__media_positions = {}
        self.__media_update_times = {}

    def notify_audio_pacing(
        self,
        *,
        lag_seconds: float,
        rebase_count: int,
        min_release_interval_seconds: Optional[float],
        catch_up_burst_count: int,
    ) -> None:
        if self.__on_audio_pacing is None:
            return
        self.__on_audio_pacing(
            lag_seconds=lag_seconds,
            rebase_count=rebase_count,
            min_release_interval_seconds=min_release_interval_seconds,
            catch_up_burst_count=catch_up_burst_count,
        )

    def notify_audio_activity(self, active: bool):
        if self.__on_audio_activity is not None:
            self.__on_audio_activity(active)

    def notify_audio_frame(self, eventpoint, active: bool) -> None:
        if self.__on_audio_frame is not None:
            self.__on_audio_frame(eventpoint, active)

    def notify_media_timing(self, kind: str, media_seconds: float) -> None:
        """Report scalar queue/A-V timing without exposing frame contents."""
        self.__media_positions[kind] = media_seconds
        self.__media_update_times[kind] = time.monotonic()
        if self.__on_media_timing is None:
            return
        audio_seconds = self.__media_positions.get("audio")
        video_seconds = self.__media_positions.get("video")
        av_offset = None
        updates_are_coincident = (
            audio_seconds is not None
            and video_seconds is not None
            and abs(
                self.__media_update_times["audio"]
                - self.__media_update_times["video"]
            )
            <= 0.05
        )
        if updates_are_coincident:
            av_offset = round(video_seconds - audio_seconds, 6)
        self.__on_media_timing(
            media_debt_seconds=round(self.__audio.buffered_duration, 6),
            av_offset_seconds=av_offset,
        )

    def notify(self,eventpoint):
        if self.__container is not None:
            self.__container.notify(eventpoint)

    async def prepare_speech_start(self) -> None:
        """Trim only paired idle media before releasing the first spoken pair."""
        discarded_pairs = 0
        while (
            self.__audio.buffered_duration > SPEECH_START_RUNWAY_SECONDS
            and self.__video.buffered_duration > SPEECH_START_RUNWAY_SECONDS
            and self.__audio._queue.qsize() >= 2
            and self.__video._queue.qsize() >= 1
        ):
            first_audio = self.__audio._queue._queue[0]
            second_audio = self.__audio._queue._queue[1]
            if first_audio[1] is not None or second_audio[1] is not None:
                break
            self.__audio._queue.get_nowait()
            self.__audio._queue.get_nowait()
            self.__video._queue.get_nowait()
            discarded_pairs += 1
        if discarded_pairs:
            mylogger.info(
                "[AVSync] speech start trimmed %d paired idle frames; audio=%.0fms video=%.0fms",
                discarded_pairs,
                self.__audio.buffered_duration * 1000.0,
                self.__video.buffered_duration * 1000.0,
            )

    def discard_stale_media(self) -> dict[str, int]:
        return {
            "audio": self.__audio.discard_stale_media(),
            "video": self.__video.discard_stale_media(),
        }

    @property
    def audio(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains audio.
        """
        return self.__audio

    @property
    def video(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains video.
        """
        return self.__video

    def _start(self, track: PlayerStreamTrack) -> None:
        self.__started.add(track)
        if self.__thread is None:
            self.__log_debug("Starting worker thread")
            self.__thread_quit = threading.Event()
            self.__thread = threading.Thread(
                name="media-player",
                target=player_worker_thread,
                args=(
                    self.__thread_quit,
                    asyncio.get_event_loop(),
                    self.__container,
                    self.__audio,
                    self.__video                   
                ),
            )
            self.__thread.start()

    def _stop(self, track: PlayerStreamTrack) -> None:
        self.__started.discard(track)

        if not self.__started and self.__thread is not None:
            self.__log_debug("Stopping worker thread")
            self.__thread_quit.set()
            self.__thread.join()
            self.__thread = None

        if not self.__started and self.__container is not None:
            #self.__container.close()
            self.__container = None

    def __log_debug(self, msg: str, *args) -> None:
        mylogger.debug(f"HumanPlayer {msg}", *args)
