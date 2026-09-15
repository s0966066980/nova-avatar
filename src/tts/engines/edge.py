# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from concurrent.futures import TimeoutError as FuturesTimeoutError
from queue import Empty
from typing import Callable, Optional

import av
import edge_tts
import numpy as np

from src.tts.base import BaseTTS, State
from src.server.reply_streaming.channel import PlayableFragment
from src.server.reply_streaming.retry import RetryBudget
from src.utils.logging import logger


# A warm Edge connection normally returns audio in under 1.5 seconds, but a
# process-cold connection has been observed taking almost 12 seconds. Keep the
# normal path responsive, while giving the one recovery request enough time to
# finish TLS/websocket setup. Once audio starts, never apply the short
# first-byte deadline to continuation packets.
EDGE_INITIAL_STREAM_TIMEOUT_SECONDS = 2.5
EDGE_RETRY_STREAM_TIMEOUT_SECONDS = 15.0
EDGE_CONTINUATION_STREAM_TIMEOUT_SECONDS = 15.0
EDGE_WARMUP_TIMEOUT_SECONDS = 15.0
EDGE_MAX_ATTEMPTS = 2
ACTIVITY_THRESHOLD = 1e-4
ONSET_THRESHOLD = 1e-5
FRAME_SECONDS = 0.01
MAX_PREROLL_SECONDS = 0.16
SILENCE_GUARD_SECONDS = 0.04
TRAILING_PAUSE_SECONDS = 0.12


class _EdgeAsyncWorker:
    """One background asyncio loop per EdgeTTS instance; not a persistent Edge socket."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run,
            name="edge-tts-loop",
            daemon=True,
        )
        self._started = threading.Event()
        self.thread.start()
        if not self._started.wait(timeout=2):
            raise RuntimeError("Edge TTS worker loop failed to start")

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._started.set()
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        self.loop.close()

    def submit(self, coro):
        task_box: dict[str, asyncio.Task] = {}
        started = threading.Event()

        async def runner():
            task_box["task"] = asyncio.current_task()
            started.set()
            return await coro

        future = asyncio.run_coroutine_threadsafe(runner(), self.loop)
        started.wait(timeout=1)
        future.aio_task = task_box.get("task")
        return future

    def cancel(self, future) -> None:
        task = getattr(future, "aio_task", None)
        if task is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(task.cancel)

    def run(self, coro):
        return self.submit(coro).result()

    def close(self) -> None:
        loop = self.loop
        if loop.is_closed():
            return
        loop.call_soon_threadsafe(loop.stop)
        self.thread.join(timeout=2)


class _DirectFrameSink:
    def __init__(self, parent) -> None:
        self.parent = parent
        self.first_pcm = threading.Event()

    def bind(self) -> None:
        return None

    def emit(self, samples: np.ndarray, eventpoint: dict) -> None:
        self.parent.put_audio_frame(samples, eventpoint)
        self.first_pcm.set()

    async def wait_for_space(self) -> None:
        return None

    def release(self) -> None:
        return None

    def cancel(self) -> None:
        return None


class _GatedFrameSink:
    """Buffer a synthesized fragment until every preceding fragment is emitted."""

    def __init__(self, parent) -> None:
        self.parent = parent
        self.first_pcm = threading.Event()
        self._buffer: deque[tuple[np.ndarray, dict]] = deque()
        self._lock = threading.Lock()
        self._released = False
        self._cancelled = False
        self._space: Optional[asyncio.Event] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._space = asyncio.Event()
        self._space.set()

    def _wake(self) -> None:
        space = self._space
        if space is None:
            return
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(space.set)
                return
            except RuntimeError:
                pass
        space.set()

    def emit(self, samples: np.ndarray, eventpoint: dict) -> None:
        live = False
        with self._lock:
            if self._cancelled:
                return
            if self._released:
                live = True
            else:
                self._buffer.append(
                    (np.asarray(samples, dtype=np.float32).copy(), dict(eventpoint))
                )
        if live:
            self.parent.put_audio_frame(samples, eventpoint)
            self.first_pcm.set()

    async def wait_for_space(self) -> None:
        # A gated sink owns a complete in-memory fragment.  Do not throttle
        # the Edge stream here: later fragments must finish synthesis while
        # earlier audio is still playing.
        return None

    def release(self) -> None:
        with self._lock:
            self._released = True
            frames = list(self._buffer)
            self._buffer.clear()
        for samples, eventpoint in frames:
            self.parent.put_audio_frame(samples, eventpoint)
            self.first_pcm.set()
        self._wake()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._buffer.clear()
        self._wake()



async def _prewarm_edge_tts(voicename: str) -> bool:
    """Open Edge's cold connection and stop as soon as one audio packet arrives."""
    stream = edge_tts.Communicate("語音連線準備完成。", voicename).stream()
    iterator = stream.__aiter__()
    try:
        while True:
            item = await iterator.__anext__()
            if item.get("type") == "audio" and item.get("data"):
                return True
    except StopAsyncIteration:
        return False
    finally:
        aclose = getattr(iterator, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:
                pass


def prewarm_edge_tts(
    voicename: str,
    *,
    timeout_seconds: float = EDGE_WARMUP_TIMEOUT_SECONDS,
) -> bool:
    """Warm Edge networking before the first user turn; failure is non-fatal."""
    started_at = time.perf_counter()
    try:
        ready = asyncio.run(
            asyncio.wait_for(
                _prewarm_edge_tts(voicename),
                timeout=max(0.1, float(timeout_seconds)),
            )
        )
    except Exception as exc:
        logger.warning(
            "Edge TTS prewarm failed after %.3fs type=%s",
            time.perf_counter() - started_at,
            type(exc).__name__,
        )
        return False
    elapsed = time.perf_counter() - started_at
    if ready:
        logger.info("Edge TTS prewarm ready in %.3fs", elapsed)
        return True
    logger.warning("Edge TTS prewarm returned no audio after %.3fs", elapsed)
    return False


def trim_edge_silence(
    stream: np.ndarray,
    sample_rate: int,
    threshold: float = ACTIVITY_THRESHOLD,
    leading_pause_seconds: float = SILENCE_GUARD_SECONDS,
    trailing_pause_seconds: float = TRAILING_PAUSE_SECONDS,
    *,
    activity_threshold: Optional[float] = None,
    onset_threshold: float = ONSET_THRESHOLD,
    max_preroll_seconds: float = MAX_PREROLL_SECONDS,
    silence_guard_seconds: Optional[float] = None,
) -> np.ndarray:
    """移除 Edge TTS 供應商 padding，同時保留低能量語音起音與自然停頓。"""
    if stream.size == 0:
        return stream

    trimmer = _StreamingSilenceTrimmer(
        sample_rate,
        threshold=threshold,
        leading_pause_seconds=leading_pause_seconds,
        trailing_pause_seconds=trailing_pause_seconds,
        activity_threshold=activity_threshold,
        onset_threshold=onset_threshold,
        max_preroll_seconds=max_preroll_seconds,
        silence_guard_seconds=silence_guard_seconds,
    )
    trimmed = np.concatenate((trimmer.feed(stream), trimmer.finish()))
    if trimmed.size == 0 and not trimmer.started:
        return stream
    return trimmed


class _StreamingSilenceTrimmer:
    """Incremental equivalent of trim_edge_silence with a buffered tail."""

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
        self._trailing = []
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


class _EdgePCMEmitter:
    """Decode MP3 incrementally and release complete 20ms PCM frames."""

    def __init__(
        self,
        owner: "EdgeTTS",
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
        self.frame_sink = frame_sink or _DirectFrameSink(owner.parent)
        self.decoder = av.CodecContext.create("mp3", "r")
        self.resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=owner.sample_rate,
        )
        self.trimmer = _StreamingSilenceTrimmer(owner.sample_rate)
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
        self.frame_sink.emit(samples, eventpoint)
        if self.emitted_chunks == 0:
            mark_stage = getattr(self.owner.parent, "mark_stage_end", None)
            if callable(mark_stage) and self.textevent.get("turn_id"):
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

    def _feed_audio_frame(self, frame) -> None:
        for converted in self.resampler.resample(frame):
            pcm = converted.to_ndarray().reshape(-1).astype(np.float32)
            pcm /= 32768.0
            self._queue_samples(self.trimmer.feed(pcm))

    def _decode_packet(self, packet) -> None:
        try:
            frames = self.decoder.decode(packet)
        except av.error.InvalidDataError:
            # Some MP3 streams begin with an ID3/Xing metadata packet which
            # carries no audio.  Later packets remain independently decodable.
            return
        for frame in frames:
            self._feed_audio_frame(frame)

    def feed_mp3(self, data: bytes) -> None:
        for packet in self.decoder.parse(data):
            self._decode_packet(packet)

    def finish(self) -> None:
        for packet in self.decoder.parse(b""):
            self._decode_packet(packet)
        for frame in self.decoder.decode(None):
            self._feed_audio_frame(frame)
        for converted in self.resampler.resample(None):
            pcm = converted.to_ndarray().reshape(-1).astype(np.float32)
            pcm /= 32768.0
            self._queue_samples(self.trimmer.feed(pcm))
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


class EdgeTTS(BaseTTS):
    def __init__(self, config, parent):
        super().__init__(config, parent)
        self.retry_after_pcm_count = 0
        self.retry_after_playback_commit_count = 0
        self.last_onset_preroll_ms = 0.0
        self._worker: Optional[_EdgeAsyncWorker] = None
        self._prefetch_jobs: deque[dict] = deque()
        self._worker_lock = threading.Lock()

    @property
    def worker_loop(self):
        worker = self._worker
        return None if worker is None else worker.loop

    @property
    def _persistent_enabled(self) -> bool:
        tts = getattr(self.config, "tts", None)
        prefetch = bool(getattr(tts, "edge_prefetch", True))
        persistent = bool(getattr(tts, "edge_persistent_worker", True))
        return persistent or prefetch

    @property
    def _prefetch_enabled(self) -> bool:
        return bool(getattr(getattr(self.config, "tts", None), "edge_prefetch", True))

    def _ensure_worker(self) -> _EdgeAsyncWorker:
        with self._worker_lock:
            if self._worker is None:
                self._worker = _EdgeAsyncWorker()
            return self._worker

    def close_worker(self) -> None:
        with self._worker_lock:
            worker = self._worker
            self._worker = None
        if worker is not None:
            worker.close()

    def _run_coro(self, coro):
        if not self._persistent_enabled:
            return asyncio.run(coro)
        return self._ensure_worker().run(coro)

    def flush_talk(self) -> None:
        super().flush_talk()
        for job in list(self._prefetch_jobs):
            job["sink"].cancel()

    def has_pending_work(self) -> bool:
        return super().has_pending_work() or bool(self._prefetch_jobs)

    def render(self, quit_event) -> None:
        if self._persistent_enabled:
            self._ensure_worker()
        super().render(quit_event)

    def process_tts(self, quit_event) -> None:
        try:
            if self._prefetch_enabled:
                self._process_tts_with_prefetch(quit_event)
            else:
                super().process_tts(quit_event)
        finally:
            self.close_worker()

    def _launch_stream(self, msg: tuple[str, dict], *, gated: bool) -> dict:
        text, textevent = msg
        sink = _GatedFrameSink(self.parent) if gated else _DirectFrameSink(self.parent)
        started_at = time.perf_counter()
        future = self._ensure_worker().submit(
            self._stream_with_retry(
                self.config.tts.ref_file,
                text,
                textevent,
                started_at,
                fragment_committed=self._fragment_committed_predicate(textevent),
                discard_uncommitted=self._discard_uncommitted_predicate(textevent),
                frame_sink=sink,
            )
        )
        return {"msg": msg, "sink": sink, "future": future}

    def _finish_job(self, job: dict) -> bool:
        future = job["future"]
        try:
            future.result(timeout=0.05)
        except FuturesTimeoutError:
            return False
        except Exception:
            text, textevent = job["msg"]
            logger.exception("Edge TTS streaming failed")
            self.notify_fragment_synthesis_failed(
                textevent,
                "tts_exhausted_before_audio",
            )
        return True

    def _playback_ended(self, job: dict) -> bool:
        eventpoint = job["msg"][1]
        if not eventpoint.get("turn_id"):
            return True
        ended = getattr(self.parent, "fragment_playback_ended", None)
        return bool(ended(eventpoint)) if callable(ended) else True

    def _cancel_job(self, job: Optional[dict]) -> None:
        if job is None:
            return
        job["sink"].cancel()
        worker = self._worker
        if worker is not None:
            worker.cancel(job["future"])
        try:
            job["future"].result(timeout=1)
        except Exception:
            pass

    def _cancel_prefetch_jobs(self) -> None:
        while self._prefetch_jobs:
            self._cancel_job(self._prefetch_jobs.popleft())

    def _launch_queued_prefetches(self) -> None:
        """Synthesize every already-known later fragment while playback drains.

        Each sink retains its PCM until its turn is released, so completing
        later requests early cannot reorder or overlap audible speech.
        """
        while self.state == State.RUNNING:
            try:
                msg = self.msgqueue.get_nowait()
            except Empty:
                return
            self._prefetch_jobs.append(self._launch_stream(msg, gated=True))

    def _process_tts_with_prefetch(self, quit_event) -> None:
        current = None
        while not quit_event.is_set():
            if current is None:
                if self._prefetch_jobs:
                    current = self._prefetch_jobs.popleft()
                    if self.state != State.RUNNING:
                        self._cancel_job(current)
                        current = None
                        self._synthesis_active.clear()
                        continue
                    current["sink"].release()
                else:
                    try:
                        msg = self.msgqueue.get(block=True, timeout=1)
                    except Empty:
                        continue
                    self.state = State.RUNNING
                    self._synthesis_active.set()
                    current = self._launch_stream(msg, gated=False)

            if self.state == State.RUNNING and current["sink"].first_pcm.is_set():
                self._launch_queued_prefetches()

            if self.state != State.RUNNING:
                self._cancel_job(current)
                self._cancel_prefetch_jobs()
                current = None
                self._synthesis_active.clear()
                continue

            if not self._finish_job(current):
                continue
            if not self._playback_ended(current):
                self._launch_queued_prefetches()
                time.sleep(0.01)
                continue
            current = None
            if not self._prefetch_jobs and self.msgqueue.empty():
                self._synthesis_active.clear()
        self._cancel_job(current)
        self._cancel_prefetch_jobs()
        logger.info("ttsreal thread stop")

    def txt_to_audio(self, msg: tuple[str, dict]):
        voicename = self.config.tts.ref_file  # 比如 "zh-CN-YunxiaNeural"
        text, textevent = msg
        started_at = time.perf_counter()
        try:
            self._run_coro(
                self._stream_with_retry(
                    voicename,
                    text,
                    textevent,
                    started_at,
                    fragment_committed=self._fragment_committed_predicate(textevent),
                    discard_uncommitted=self._discard_uncommitted_predicate(textevent),
                )
            )
        except Exception:
            logger.exception("Edge TTS streaming failed")
            self.notify_fragment_synthesis_failed(
                textevent,
                "tts_exhausted_before_audio",
            )
        finally:
            logger.info(
                "-------edge tts total stream time:%.4fs",
                time.perf_counter() - started_at,
            )

    def synthesize_fragment(
        self,
        fragment: PlayableFragment,
        *,
        chunk_guard: Callable[[int], bool],
        retry_budget: Optional[RetryBudget] = None,
        fragment_committed: Optional[Callable[[], bool]] = None,
        discard_uncommitted: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Synchronously synthesize one fenced fragment into 20ms PCM frames."""
        envelope = fragment.envelope
        textevent = {
            "turn_id": envelope.turn_id,
            "generation": envelope.generation,
            "fragment_sequence": envelope.sequence,
        }
        started_at = time.perf_counter()
        try:
            self._run_coro(
                self._stream_with_retry(
                    self.config.tts.ref_file,
                    fragment.text,
                    textevent,
                    started_at,
                    chunk_guard=chunk_guard,
                    retry_budget=retry_budget,
                    fragment_committed=fragment_committed,
                    discard_uncommitted=discard_uncommitted,
                )
            )
        except Exception:
            logger.exception("Edge TTS fragment streaming failed")
            self.notify_fragment_synthesis_failed(
                textevent,
                "tts_exhausted_before_audio",
            )

    def _fragment_committed_predicate(
        self, textevent: dict
    ) -> Optional[Callable[[], bool]]:
        checker = getattr(self.parent, "fragment_playback_committed", None)
        if not callable(checker):
            return None
        return lambda: bool(checker(textevent))

    def _discard_uncommitted_predicate(
        self, textevent: dict
    ) -> Optional[Callable[[], bool]]:
        discard = getattr(self.parent, "discard_uncommitted_fragment", None)
        if not callable(discard):
            return None
        return lambda: bool(discard(textevent))

    def _record_onset_preroll(self, emitter: _EdgePCMEmitter) -> None:
        samples = int(getattr(emitter.trimmer, "retained_preroll_samples", 0) or 0)
        self.last_onset_preroll_ms = round(
            samples / float(self.sample_rate) * 1000.0,
            3,
        )
        observe = getattr(self.parent, "observe_tts_onset_preroll_ms", None)
        if callable(observe) and self.last_onset_preroll_ms:
            observe(self.last_onset_preroll_ms)

    def _fail_closed_after_pcm(
        self,
        emitter: _EdgePCMEmitter,
        *,
        committed: bool,
        exc: Exception,
    ) -> None:
        if committed:
            self.retry_after_playback_commit_count += 1
        else:
            self.retry_after_pcm_count += 1
        try:
            emitter.finish()
        except Exception:
            logger.debug("Could not flush interrupted Edge stream", exc_info=True)
        self._record_onset_preroll(emitter)
        logger.warning(
            "Edge TTS stream stopped after PCM without sample splice reason=%s type=%s",
            "playback_commit" if committed else "uncommitted_pcm",
            type(exc).__name__,
        )
        observe = getattr(self.parent, "observe_tts_retry", None)
        if callable(observe):
            observe(after_commit=committed)

    async def _stream_with_retry(
        self,
        voicename: str,
        text: str,
        textevent: dict,
        started_at: float,
        *,
        chunk_guard: Optional[Callable[[int], bool]] = None,
        retry_budget: Optional[RetryBudget] = None,
        fragment_committed: Optional[Callable[[], bool]] = None,
        discard_uncommitted: Optional[Callable[[], bool]] = None,
        frame_sink=None,
    ) -> None:
        last_error = None
        start_event_sent = False
        first_audio_logged = False
        first_encoded_logged = False
        retry_timeout_seconds = EDGE_RETRY_STREAM_TIMEOUT_SECONDS
        if frame_sink is None:
            frame_sink = _DirectFrameSink(self.parent)
        frame_sink.bind()
        for attempt in range(1, EDGE_MAX_ATTEMPTS + 1):
            received_audio = False
            emitter = _EdgePCMEmitter(
                self,
                text,
                textevent,
                start_event_sent=start_event_sent,
                chunk_guard=chunk_guard,
                frame_sink=frame_sink,
            )

            def log_first_audio() -> None:
                nonlocal first_audio_logged
                if emitter.emitted and not first_audio_logged:
                    first_audio_logged = True
                    logger.info(
                        "-------edge tts first audio:%.4fs (attempt %d)",
                        time.perf_counter() - started_at,
                        attempt,
                    )

            stream = edge_tts.Communicate(text, voicename).stream()
            iterator = stream.__aiter__()
            try:
                while self.state == State.RUNNING:
                    try:
                        item = await asyncio.wait_for(
                            iterator.__anext__(),
                            timeout=(
                                EDGE_CONTINUATION_STREAM_TIMEOUT_SECONDS
                                if received_audio
                                else (
                                    EDGE_INITIAL_STREAM_TIMEOUT_SECONDS
                                    if attempt == 1
                                    else retry_timeout_seconds
                                )
                            ),
                        )
                    except StopAsyncIteration:
                        break
                    if item.get("type") == "audio":
                        received_audio = True
                        if not first_encoded_logged:
                            first_encoded_logged = True
                            mark_stage = getattr(self.parent, "mark_stage_end", None)
                            if callable(mark_stage) and textevent.get("turn_id"):
                                mark_stage("tts_first_encoded")
                        emitter.feed_mp3(item["data"])
                        log_first_audio()
                        await frame_sink.wait_for_space()
                        if emitter.cancelled:
                            return
                emitter.finish()
                log_first_audio()
                if emitter.cancelled:
                    return
                self._record_onset_preroll(emitter)
                if emitter.emitted_samples or self.state != State.RUNNING:
                    return
                raise RuntimeError("Edge TTS returned no decodable audio")
            except Exception as exc:
                last_error = exc
                if self.state != State.RUNNING:
                    return
                can_retry = attempt < EDGE_MAX_ATTEMPTS
                if can_retry and retry_budget is not None:
                    permit = retry_budget.claim_retry()
                    can_retry = permit is not None
                    if permit is not None:
                        retry_timeout_seconds = permit.max_wait_seconds
                if emitter.emitted_samples:
                    log_first_audio()
                    committed = bool(
                        fragment_committed is not None and fragment_committed()
                    )
                    if committed:
                        self._fail_closed_after_pcm(
                            emitter, committed=True, exc=exc
                        )
                        return
                    if (
                        can_retry
                        and discard_uncommitted is not None
                        and discard_uncommitted()
                    ):
                        self.retry_after_pcm_count += 1
                        start_event_sent = False
                        logger.warning(
                            "Edge TTS discarded uncommitted PCM; "
                            "retrying fragment from start attempt %d/%d",
                            attempt + 1,
                            EDGE_MAX_ATTEMPTS,
                        )
                        continue
                    self._fail_closed_after_pcm(
                        emitter, committed=False, exc=exc
                    )
                    return
                logger.warning(
                    "Edge TTS attempt %d/%d failed before first audio: %s",
                    attempt,
                    EDGE_MAX_ATTEMPTS,
                    exc,
                )
                if not can_retry:
                    break
            finally:
                aclose = getattr(iterator, "aclose", None)
                if callable(aclose):
                    try:
                        await aclose()
                    except Exception:
                        pass
        raise RuntimeError("Edge TTS exhausted retries") from last_error
