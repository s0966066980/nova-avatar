# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""One WebRTC microphone session and its server-owned conversation turns.

The class deliberately exposes only audio/control input and an event sink.  VAD
buffers, turn identity, stale-result protection and STT -> LLM -> TTS ordering
remain private so routes and UI cannot accidentally create competing pipelines.
"""
from __future__ import annotations

import asyncio
from functools import partial
import json
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import RLock
from typing import Callable, Optional
from uuid import uuid4

import numpy as np
import soundfile as sf
from av.audio.resampler import AudioResampler

from src.asr.factory import get_asr_engine
from src.llm.service import (
    acknowledge_session_board_item,
    commit_session_history,
    llm_response,
)
from src.llm.rules import snapshot_from_config
from src.server.reply_streaming.circuit_breaker import ReplyCircuitBreaker
from src.server.reply_streaming.metrics import TurnMetrics
from src.server.reply_streaming.turn import TurnContext, TurnEnvelope, TurnState
from src.utils.logging import logger
from src.vad.service import create_segmenter


EventSink = Callable[[str], None]
OUTPUT_STALL_FRAMES = 50  # one second at the 20 ms audio commit clock


class VoiceTurnSession:
    """Own the complete lifetime of hands-free turns for one peer connection."""

    def __init__(
        self,
        sessionid: int,
        config,
        avatar,
        *,
        clock: Callable[[], float] = time.monotonic,
        presenter: str = "console",
    ) -> None:
        self.sessionid = sessionid
        self.config = config
        self.avatar = avatar
        self._presenter = presenter if presenter in {"console", "stage"} else "console"
        self._event_sink: Optional[EventSink] = None
        self._sequence = 0
        self._turn_id: Optional[str] = None
        self._generation = 0
        self._capture_requested = True
        self._gate_open = False
        self._manual_pause = False
        self._closed = False
        self._prepare_error = ""
        self._segmenter = None
        self._asr = None
        self._track_task: Optional[asyncio.Task] = None
        self._turn_task: Optional[asyncio.Task] = None
        self._tail_task: Optional[asyncio.Task] = None
        self._finalize_task: Optional[asyncio.Task] = None
        self._output_active = False
        self._metrics_clock = clock
        self._metrics: Optional[TurnMetrics] = None
        self._turn_context: Optional[TurnContext] = None
        self._rules_snapshot = None
        self._circuit_breaker = ReplyCircuitBreaker(clock=clock)
        self._pipeline_mode = "legacy"
        self._fragment_lock = RLock()
        self._fragment_texts: dict[int, str] = {}
        self._played_fragment_sequences: set[int] = set()
        self._ended_fragment_sequences: set[int] = set()
        self._played_fragments: list[str] = []
        self._history_finalized_turns: set[str] = set()
        self._metrics_emitted_turns: set[str] = set()
        self._board_display_receipts: set[tuple[str, str, int, str]] = set()
        self._llm_finished = False
        self._media_player = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._silent_output_frames = 0
        self._tts_pending_silent_frames = 0
        timeout_sec = float(
            getattr(
                getattr(self.config, "reply_streaming", None),
                "inter_fragment_timeout_seconds",
                5.0,
            )
            or 5.0
        )
        self._inter_fragment_stall_frames = max(
            OUTPUT_STALL_FRAMES, int(timeout_sec / 0.02)
        )
        self._segmenter_reset_pending = True
        self._resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        # Silero/PyTorch must never run on aiohttp/aiortc's media event loop.
        # One worker preserves the segmenter's stateful frame ordering.
        self._voice_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"voice-input-{sessionid}",
        )
        configure_media_fence = getattr(self.avatar, "configure_media_fence", None)
        if callable(configure_media_fence):
            configure_media_fence(
                media_guard=self.accepts_media,
                on_stale_drop=self.record_stale_drop,
                on_fragment_queued=self.register_fragment,
                on_fragment_failed=self.on_fragment_synthesis_failed,
                fragment_playback_committed=self.fragment_playback_committed,
                on_tts_onset_preroll_ms=self.observe_tts_onset_preroll_ms,
                on_tts_retry=self.observe_tts_retry,
                on_stage_end=self.mark_stage_end,
                on_llm_chunk=self._on_llm_chunk,
            )

    async def prepare(self) -> None:
        """Prewarm Silero and STT before the session may announce listening."""
        self._emit("state", state="preparing")
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._prepare_sync)
        except Exception as exc:
            self._prepare_error = str(exc)
            self._gate_open = False
            logger.exception("Voice session prewarm failed")
            self._emit("state", state="degraded", error=self._prepare_error)
            return
        self._refresh_gate()

    def _prepare_sync(self) -> None:
        self.config.asr.mode = "server"
        self.config.vad.type = "silero"
        self._segmenter = create_segmenter(self.config.vad, self.config)
        self._segmenter.vad.ensure_ready()
        self._asr = get_asr_engine(
            self.config.asr.type,
            model_size=self.config.asr.model_size,
            config=self.config,
        )
        self._asr.set_language(self.config.asr.language)
        self._asr.ensure_ready()

    def attach_event_sink(self, sink: EventSink) -> None:
        self._event_sink = sink
        if self._prepare_error:
            self._emit("state", state="degraded", error=self._prepare_error)
        else:
            self._refresh_gate()

    @property
    def event_sink_ready(self) -> bool:
        """Whether asynchronous text/voice reply events have a destination."""
        return self._event_sink is not None

    def detach_event_sink(self) -> None:
        self._event_sink = None
        self._close_gate()

    def attach_media_player(self, player) -> None:
        self._media_player = player
        configure_audio_output = getattr(self.avatar, "configure_audio_output", None)
        reply_streaming = getattr(self.config, "reply_streaming", None)
        if (
            callable(configure_audio_output)
            and bool(getattr(reply_streaming, "enabled", False))
            and bool(getattr(reply_streaming, "decoupled_audio_clock", False))
        ):
            try:
                configure_audio_output(player.audio, asyncio.get_running_loop())
            except RuntimeError:
                logger.debug("audio output fan-out deferred: no running event loop")

    def handle_control(self, raw_message: str) -> None:
        try:
            message = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            return
        kind = message.get("type")
        if kind == "capture":
            enabled = bool(message.get("enabled"))
            finalize = (
                not enabled
                and bool(message.get("finalize"))
                and self._segmenter is not None
                and self._gate_open
            )
            self._capture_requested = enabled
            self._manual_pause = not enabled
            if finalize:
                # Preserve the current segment until flush runs in the same
                # ordered worker as resampling/VAD.
                self._gate_open = False
                self._emit("state", state="paused")
                self._finalize_task = asyncio.create_task(
                    self._finalize_capture()
                )
                return
            if enabled and self._output_active:
                return
            self._refresh_gate()
        elif kind == "interrupt":
            asyncio.create_task(self.interrupt())
        elif kind == "board_displayed":
            turn_id = str(message.get("turn_id") or "")
            board_id = str(message.get("board_id") or "")
            presenter = str(message.get("presenter") or "")
            item_index = message.get("item_index")
            if presenter != self._presenter or not turn_id or board_id != turn_id:
                return
            if isinstance(item_index, bool):
                return
            try:
                item_index = int(item_index)
            except (TypeError, ValueError):
                return
            receipt_key = (turn_id, board_id, item_index, presenter)
            if receipt_key in self._board_display_receipts:
                return
            if acknowledge_session_board_item(
                self.sessionid,
                turn_id=turn_id,
                board_id=board_id,
                item_index=item_index,
                presenter=presenter,
            ):
                self._board_display_receipts.add(receipt_key)

    def start_track(self, track) -> None:
        if self._track_task:
            self._track_task.cancel()
        self._track_task = asyncio.create_task(self._consume_track(track))

    async def _consume_track(self, track) -> None:
        try:
            while not self._closed:
                frame = await track.recv()
                loop = asyncio.get_running_loop()
                pcm_chunks = await loop.run_in_executor(
                    self._voice_executor,
                    self._resample_frame_sync,
                    frame,
                )
                for pcm in pcm_chunks:
                    await self.feed_pcm(pcm)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                logger.warning(f"Microphone track ended: {exc}")
                self._emit("state", state="reconnecting", error="microphone_track_lost")
                self._close_gate()

    def _resample_frame_sync(self, frame) -> list[np.ndarray]:
        return [
            converted.to_ndarray().reshape(-1).astype(np.int16, copy=False)
            for converted in self._resampler.resample(frame)
        ]

    async def feed_pcm(self, pcm: np.ndarray) -> None:
        """Feed mono 16 kHz int16 PCM; intentionally a small testable seam."""
        if not self._gate_open or self._closed or self._segmenter is None:
            return
        loop = asyncio.get_running_loop()
        was_speaking, is_speaking, segments = await loop.run_in_executor(
            self._voice_executor,
            self._segment_pcm_sync,
            pcm,
        )
        if self._closed:
            return
        if not was_speaking and is_speaking:
            self._turn_id = uuid4().hex
            self._start_turn_context(self._turn_id)
            self._emit("state", state="speech_detected")
        if not segments:
            return
        # max_speech_ms and normal endpointing both finalize exactly one turn.
        self._close_gate()
        segment = segments[0]
        if self._turn_id is None:
            self._turn_id = uuid4().hex
        self._start_turn_context(self._turn_id)
        self._metrics.mark_speech_end()
        generation = self._generation
        self._turn_task = asyncio.create_task(
            self._process_turn(segment.audio, segment.sample_rate, self._turn_id, generation)
        )

    async def start_text_turn(self, text: str, *, interrupt: bool = True) -> dict:
        """Start a typed turn through the same reply pipeline as speech."""
        text = str(text or "").strip()
        if not text:
            raise ValueError("文字訊息不可為空")
        if self._closed:
            raise RuntimeError("語音工作階段已關閉")
        if interrupt and (
            self._turn_id is not None
            or self._turn_task is not None
            or self._output_active
        ):
            await self.interrupt()
        if self._turn_id is not None or self._turn_task is not None:
            raise RuntimeError("上一個對話輪次尚未結束")
        self._turn_id = uuid4().hex
        self._start_turn_context(self._turn_id)
        generation = self._generation
        turn_id = self._turn_id
        self._turn_task = asyncio.create_task(
            self._process_text_turn(text, turn_id, generation)
        )
        return {
            "turn_id": turn_id,
            "reply_mode": self._pipeline_mode,
            "delivery": "events",
        }

    def _segment_pcm_sync(self, pcm: np.ndarray):
        if self._segmenter_reset_pending:
            self._segmenter.reset()
            self._segmenter_reset_pending = False
        was_speaking = self._segmenter.is_speaking
        segments = list(self._segmenter.process(pcm))
        return was_speaking, self._segmenter.is_speaking, segments

    async def _finalize_capture(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            segments = await loop.run_in_executor(
                self._voice_executor,
                lambda: list(self._segmenter.flush()),
            )
            self._segmenter_reset_pending = True
            if self._closed:
                return
            if not segments:
                return
            self._close_gate()
            if self._turn_id is None:
                self._turn_id = uuid4().hex
            self._start_turn_context(self._turn_id)
            self._metrics.mark_speech_end()
            generation = self._generation
            segment = segments[0]
            self._turn_task = asyncio.create_task(
                self._process_turn(
                    segment.audio,
                    segment.sample_rate,
                    self._turn_id,
                    generation,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                logger.exception("Voice capture finalize failed")
                self._emit("state", state="error", error=str(exc))
        finally:
            self._finalize_task = None
            if not self._closed and self._turn_task is None:
                self._refresh_gate()

    async def _process_turn(
        self, audio: np.ndarray, sample_rate: int, turn_id: str, generation: int
    ) -> None:
        loop = asyncio.get_running_loop()
        try:
            self._emit("state", state="stt", turn_id=turn_id)
            wav = BytesIO()
            sf.write(wav, audio, sample_rate, format="WAV", subtype="PCM_16")
            self.mark_stage_start("asr")
            result = await loop.run_in_executor(None, self._asr.transcribe, wav.getvalue())
            self.mark_stage_end("asr")
            if not self._is_current(turn_id, generation):
                return
            text = str(result.get("text", "")).strip()
            if not text:
                self._turn_id = None
                self._refresh_gate()
                return
            self._emit("user_transcript", text=text, turn_id=turn_id)
            await self._generate_turn(
                text,
                turn_id,
                generation,
                input_source="speech",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._handle_turn_error(exc, turn_id, generation)

    async def _process_text_turn(
        self, text: str, turn_id: str, generation: int
    ) -> None:
        try:
            await self._generate_turn(
                text,
                turn_id,
                generation,
                input_source="text",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._handle_turn_error(exc, turn_id, generation)

    async def _generate_turn(
        self,
        text: str,
        turn_id: str,
        generation: int,
        *,
        input_source: str,
    ) -> None:
        loop = asyncio.get_running_loop()
        self._event_loop = loop
        if not self._is_current(turn_id, generation):
            return
        self._emit("board_clear", turn_id=turn_id)
        self._emit("state", state="llm", turn_id=turn_id)
        if self._pipeline_mode == "streaming":
            self._emit("assistant_response_start", turn_id=turn_id, mode="streaming", input_source=input_source)
        turn_context = self._turn_context
        if turn_context is None:
            return
        if turn_context.state == TurnState.CREATED:
            turn_context.transition(TurnState.LLM_STREAMING)

        self.mark_stage_start("llm_first_token")
        self.mark_stage_start("llm_total")
        self.mark_stage_start("first_fragment")

        kwargs = {
            "stream_to_avatar": self._pipeline_mode == "streaming",
            "datainfo": {
                "turn_id": turn_id,
                "generation": generation,
                "on_board": self._on_board_event,
            },
        }
        # Keep the immutable snapshot on the session/avatar seam so legacy
        # test doubles and TTS metadata do not receive internal rule text.
        try:
            self.avatar._reply_rules_snapshot = self._rules_snapshot
            self.avatar._reply_mode_callback = lambda mode: self._on_mode_event(turn_id, mode)
            self.avatar._incremental_board = True
        except Exception:
            pass
        if self._pipeline_mode == "streaming":
            kwargs.update(
                {
                    "chunk_guard": lambda sequence: self._accept_llm_chunk(
                        turn_context,
                        sequence,
                    ),
                    "defer_history_commit": True,
                }
            )

        def _call_llm():
            return llm_response(text, self.avatar, **kwargs)

        response = await loop.run_in_executor(None, _call_llm)
        self.mark_stage_end("llm_total")
        if not self._is_current(turn_id, generation):
            return
        response = str(response).strip()
        self._llm_finished = True
        self._emit("state", state="tts_ready", turn_id=turn_id)
        if not response:
            if self._pipeline_mode == "streaming":
                self._commit_history("no_audio", turn_id=turn_id)
            self._emit_turn_metrics("no_audio", turn_id=turn_id)
            self._turn_id = None
            self._turn_task = None
            self._refresh_gate()
            return
        if self._pipeline_mode == "legacy":
            eventpoint = {
                "turn_id": turn_id,
                "generation": generation,
                "fragment_sequence": 0,
            }
            self.avatar.put_msg_txt(response, eventpoint)
            self._emit(
                "assistant_response",
                text=response,
                turn_id=turn_id,
                mode="legacy",
                input_source=input_source,
            )
        else:
            self._emit(
                "assistant_response_done",
                turn_id=turn_id,
                mode="streaming",
                terminal_reason="completed",
            )
        self._turn_task = None

    def _handle_turn_error(
        self, exc: Exception, turn_id: str, generation: int
    ) -> None:
        if not self._is_current(turn_id, generation):
            return
        if self._turn_context is not None:
            self._turn_context.fail("pipeline_error")
        if self._pipeline_mode == "streaming":
            if self._circuit_breaker.record_pipeline_error():
                logger.warning(
                    "reply streaming circuit opened session=%s reason=pipeline_error",
                    self.sessionid,
                )
        if self._pipeline_mode == "streaming":
            self._commit_history("pipeline_error", turn_id=turn_id)
        self._emit_turn_metrics("pipeline_error", turn_id=turn_id)
        logger.error("Voice turn failed reason=pipeline_error type=%s", type(exc).__name__)
        self._emit("state", state="error", error="pipeline_error", turn_id=turn_id)
        self._turn_id = None
        self._turn_task = None
        self._refresh_gate()

    def on_output_audio(self, active: bool) -> None:
        """Called from the outbound WebRTC audio track for frame-accurate gating."""
        if self._closed:
            return
        if active:
            self._silent_output_frames = 0
            self._tts_pending_silent_frames = 0
            if self._metrics is not None:
                had_first_audio = self._metrics.snapshot().get("first_audio_seconds") is not None
                self._metrics.mark_first_audio()
                self._metrics.mark_stage_end("avatar_to_webrtc_commit")
                self._metrics.mark_stage_end("webrtc_audio_commit")
                if not had_first_audio:
                    logger.info(
                        "first active audio committed turn=%s stages=%s",
                        self._turn_id,
                        self._metrics.snapshot().get("stage_seconds", {}),
                    )
            if not self._output_active:
                self._output_active = True
                self._close_gate()
                self._emit("speaking_start", turn_id=self._turn_id)
                self._emit("state", state="avatar_speaking", turn_id=self._turn_id)
            return
        if self._metrics is not None:
            self._metrics.mark_output_stopped()
        if not self._output_active:
            if self._has_unended_fragments():
                if self._tts_has_pending_work():
                    self._tts_pending_silent_frames += 1
                    max_tts_stall = max(
                        OUTPUT_STALL_FRAMES * 4,
                        self._inter_fragment_stall_frames * 2,
                    )
                    if self._tts_pending_silent_frames >= max_tts_stall:
                        logger.warning(
                            "Initial output stalled awaiting TTS pending work (silent=%d/%d)",
                            self._tts_pending_silent_frames,
                            max_tts_stall,
                        )
                        self._fail_playback_turn()
                    else:
                        self._silent_output_frames = 0
                    return
                self._silent_output_frames += 1
                if self._silent_output_frames >= OUTPUT_STALL_FRAMES:
                    self._fail_playback_turn()
            return
        is_still_rendering = getattr(self.avatar, "is_speaking", None)
        direct_audio_enabled = bool(
            getattr(self.avatar, "direct_audio_enabled", False)
        )
        if not direct_audio_enabled and callable(is_still_rendering) and is_still_rendering():
            self._silent_output_frames = 0
            return
        self._silent_output_frames += 1
        if self._silent_output_frames < 3:
            return
        if not self._all_registered_fragments_ended():
            if self._tts_has_pending_work():
                self._tts_pending_silent_frames += 1
                max_tts_stall = max(
                    OUTPUT_STALL_FRAMES * 4,
                    self._inter_fragment_stall_frames * 2,
                )
                if self._tts_pending_silent_frames >= max_tts_stall:
                    logger.warning(
                        "Output stalled awaiting TTS pending work (silent=%d/%d llm_finished=%s)",
                        self._tts_pending_silent_frames,
                        max_tts_stall,
                        self._llm_finished,
                    )
                    self._fail_playback_turn()
                else:
                    self._silent_output_frames = 0
                return
            stall_limit = (
                self._inter_fragment_stall_frames
                if not self._llm_finished
                else OUTPUT_STALL_FRAMES
            )
            if self._silent_output_frames >= stall_limit:
                self._fail_playback_turn()
            return
        self._output_active = False
        self._silent_output_frames = 0
        self._tts_pending_silent_frames = 0
        self._emit("speaking_end", turn_id=self._turn_id)
        if self._tail_task:
            self._tail_task.cancel()
        self._tail_task = asyncio.create_task(self._finish_tail_guard())

    def register_fragment(self, text: str, eventpoint: dict) -> bool:
        """Register private fragment text before TTS; never expose it early."""
        if not self.accepts_media(eventpoint, "fragment_register"):
            self.record_stale_drop("fragment_register", "stale_generation")
            return False
        try:
            sequence = int(eventpoint["fragment_sequence"])
        except (KeyError, TypeError, ValueError):
            return False
        with self._fragment_lock:
            self._fragment_texts.setdefault(sequence, str(text))
        self.mark_stage_end("first_fragment")
        self.mark_stage_start("tts_first_encoded")
        self.mark_stage_start("tts_first_pcm")
        self.mark_stage_start("musetalk_first_batch")
        self.mark_stage_start("musetalk_inference_first_result")
        self.mark_stage_start("avatar_pasteback_done")
        self.mark_stage_start("webrtc_audio_enqueue")
        self.mark_stage_start("webrtc_video_enqueue")
        self.mark_stage_start("avatar_to_webrtc_commit")
        self.mark_stage_start("webrtc_audio_commit")
        return True

    def on_fragment_synthesis_failed(
        self,
        eventpoint: dict,
        reason: str,
    ) -> None:
        """Marshal a TTS-worker failure onto the session event loop."""
        failed_event = dict(eventpoint or {})
        if not self.accepts_media(failed_event, "fragment_synthesis_failure"):
            self.record_stale_drop(
                "fragment_synthesis_failure",
                "stale_generation",
            )
            return
        loop = self._event_loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(
                self._handle_fragment_synthesis_failure,
                failed_event,
                str(reason),
            )
            return
        self._handle_fragment_synthesis_failure(failed_event, str(reason))

    def _handle_fragment_synthesis_failure(
        self,
        eventpoint: dict,
        reason: str,
    ) -> None:
        if not self.accepts_media(eventpoint, "fragment_synthesis_failure"):
            self.record_stale_drop(
                "fragment_synthesis_failure",
                "stale_generation",
            )
            return
        try:
            sequence = int(eventpoint["fragment_sequence"])
        except (KeyError, TypeError, ValueError):
            return
        with self._fragment_lock:
            if sequence not in self._fragment_texts:
                return
            if sequence in self._ended_fragment_sequences:
                return
        logger.warning(
            "TTS fragment failed turn=%s generation=%s fragment=%s reason=%s",
            eventpoint.get("turn_id"),
            eventpoint.get("generation"),
            sequence,
            reason,
        )
        self._fail_playback_turn(reason_prefix="tts_error")

    def fragment_playback_committed(self, eventpoint: dict) -> bool:
        """True after a non-silent WebRTC frame for this fragment has been sent."""
        try:
            sequence = int(eventpoint["fragment_sequence"])
        except (KeyError, TypeError, ValueError):
            return False
        with self._fragment_lock:
            return sequence in self._played_fragment_sequences

    def on_output_audio_frame(self, eventpoint: dict, active: bool) -> None:
        """Commit subtitle/text only after a current non-silent audio frame."""
        if not isinstance(eventpoint, dict) or not self.accepts_media(
            eventpoint,
            "playback_text_commit",
        ):
            return
        try:
            sequence = int(eventpoint["fragment_sequence"])
        except (KeyError, TypeError, ValueError):
            return

        committed_text = None
        ended = False
        with self._fragment_lock:
            if active and sequence not in self._played_fragment_sequences:
                text = self._fragment_texts.get(sequence)
                if text is not None:
                    self._played_fragment_sequences.add(sequence)
                    self._played_fragments.append(text)
                    committed_text = text
            if (
                eventpoint.get("fragment_end")
                and sequence in self._played_fragment_sequences
                and sequence not in self._ended_fragment_sequences
            ):
                self._ended_fragment_sequences.add(sequence)
                ended = True

        if committed_text is not None:
            self._emit(
                "assistant_fragment",
                text=committed_text,
                turn_id=str(eventpoint["turn_id"]),
                fragment_sequence=sequence,
            )
        if ended:
            self._emit(
                "assistant_fragment_end",
                turn_id=str(eventpoint["turn_id"]),
                fragment_sequence=sequence,
            )

    @property
    def played_assistant_text(self) -> str:
        with self._fragment_lock:
            return "".join(self._played_fragments)

    def _all_registered_fragments_ended(self) -> bool:
        with self._fragment_lock:
            registered = set(self._fragment_texts)
            if not registered:
                return True
            return self._llm_finished and registered.issubset(
                self._ended_fragment_sequences
            )

    def _has_unended_fragments(self) -> bool:
        with self._fragment_lock:
            return (
                self._llm_finished
                and bool(self._fragment_texts)
                and not set(self._fragment_texts).issubset(
                    self._ended_fragment_sequences
                )
            )

    def _tts_has_pending_work(self) -> bool:
        tts = getattr(self.avatar, "tts", None)
        has_pending_work = getattr(tts, "has_pending_work", None)
        return bool(has_pending_work()) if callable(has_pending_work) else False

    def _fail_playback_turn(self, *, reason_prefix: str = "playback_error") -> None:
        turn_id = self._turn_id
        if not turn_id:
            return
        reason = (
            f"{reason_prefix}_after_commit"
            if self.played_assistant_text
            else f"{reason_prefix}_before_commit"
        )
        if self._turn_context is not None and not self._turn_context.terminal:
            self._turn_context.fail(reason)
        if self._pipeline_mode == "streaming":
            if self._circuit_breaker.record_pipeline_error():
                logger.warning(
                    "reply streaming circuit opened session=%s reason=%s",
                    self.sessionid,
                    reason,
                )
        self._commit_history(reason, turn_id=turn_id)
        self._emit_turn_metrics(reason, turn_id=turn_id)
        self._generation += 1
        self.avatar.flush_talk()
        if self._media_player is not None:
            self._media_player.discard_stale_media()
        self._output_active = False
        self._silent_output_frames = 0
        self._tts_pending_silent_frames = 0
        self._emit("turn_cancelled", turn_id=turn_id, reason=reason)
        self._emit("state", state="error", error=reason, turn_id=turn_id)
        self._turn_id = None
        self._turn_task = None
        self._refresh_gate()

    async def _finish_tail_guard(self) -> None:
        self._emit("state", state="tail_guard", turn_id=self._turn_id)
        if self._pipeline_mode == "streaming":
            self._commit_history("completed")
        self._emit_turn_metrics("completed")
        if self._pipeline_mode == "streaming":
            self._circuit_breaker.record_turn_success()
        await asyncio.sleep(0.3)
        self._turn_id = None
        self._refresh_gate()

    async def interrupt(self) -> None:
        """Cancel the old turn, flush all queued speech, then reopen after a tail guard."""
        interrupted_turn_id = self._turn_id
        if self._metrics is not None:
            self._metrics.mark_interrupt()
        if self._turn_context is not None:
            self._turn_context.cancel("interrupt")
        self._commit_history("interrupt")
        self._generation += 1
        self._close_gate()
        if self._turn_task:
            self._turn_task.cancel()
            self._turn_task = None
        if self._tail_task:
            self._tail_task.cancel()
        self.avatar.flush_talk()
        if self._media_player is not None:
            self._media_player.discard_stale_media()
        self._output_active = False
        if self._metrics is not None:
            self._metrics.mark_output_stopped()
        self._emit("turn_cancelled", turn_id=self._turn_id)
        self._emit("state", state="tail_guard", turn_id=self._turn_id)
        await asyncio.sleep(0.3)
        self._turn_id = None
        self._manual_pause = False
        self._capture_requested = True
        self._refresh_gate()
        self._emit_turn_metrics("interrupt", turn_id=interrupted_turn_id)

    async def close(self) -> None:
        self._commit_history("disconnect")
        self._emit_turn_metrics("disconnect")
        self._closed = True
        if self._turn_context is not None:
            self._turn_context.cancel("disconnect")
        self._generation += 1
        self._close_gate()
        for task in (
            self._track_task,
            self._turn_task,
            self._tail_task,
            self._finalize_task,
        ):
            if task:
                task.cancel()
        self.avatar.flush_talk()
        if self._media_player is not None:
            self._media_player.discard_stale_media()
        self._event_sink = None
        self._voice_executor.shutdown(wait=False, cancel_futures=True)

    def _is_current(self, turn_id: str, generation: int) -> bool:
        turn_context = self._turn_context
        return (
            not self._closed
            and self._turn_id == turn_id
            and self._generation == generation
            and turn_context is not None
            and turn_context.turn_id == turn_id
            and turn_context.generation == generation
            and not turn_context.terminal
        )

    def _accept_llm_chunk(self, turn_context: TurnContext, sequence: int) -> bool:
        if self._turn_context is not turn_context:
            return False
        accepted = turn_context.accepts(
            turn_context.envelope(stage="llm_token", sequence=sequence)
        )
        if accepted:
            self.mark_stage_end("llm_first_token")
        return accepted

    def accepts_media(self, eventpoint: dict, stage: str) -> bool:
        """Validate one turn-aware media item at a cross-thread boundary."""
        turn_context = self._turn_context
        if turn_context is None or not isinstance(eventpoint, dict):
            return False
        try:
            turn_id = str(eventpoint["turn_id"])
            generation = int(eventpoint["generation"])
            if (
                self._closed
                or self._turn_id != turn_id
                or self._generation != generation
            ):
                return False
            envelope = TurnEnvelope(
                turn_id=turn_id,
                generation=generation,
                stage=stage,
                sequence=int(
                    eventpoint.get(
                        "media_sequence",
                        eventpoint.get("fragment_sequence", 0),
                    )
                ),
            )
        except (KeyError, TypeError, ValueError):
            return False
        return self._turn_context is turn_context and turn_context.accepts(envelope)

    def record_stale_drop(self, stage: str, reason: str) -> None:
        if self._metrics is not None:
            self._metrics.record_stale_drop(stage, reason)

    def metrics_snapshot(self) -> Optional[dict]:
        """Return the latest turn's content-free baseline measurements."""
        if self._metrics is None:
            return None
        return self._metrics.snapshot()

    def _emit_turn_metrics(
        self,
        terminal_reason: str,
        *,
        turn_id: Optional[str] = None,
    ) -> None:
        target_turn = turn_id or self._turn_id
        if (
            not target_turn
            or target_turn in self._metrics_emitted_turns
            or self._metrics is None
        ):
            return
        snapshot = self._metrics.snapshot()
        if snapshot.get("turn_id") != target_turn:
            return
        self._metrics_emitted_turns.add(target_turn)
        self._emit(
            "turn_metrics",
            turn_id=target_turn,
            terminal_reason=terminal_reason,
            pipeline_mode=self._pipeline_mode,
            metrics=snapshot,
        )

    def observe_media_timing(
        self,
        *,
        media_debt_seconds: Optional[float] = None,
        av_offset_seconds: Optional[float] = None,
    ) -> None:
        """Record outbound queue and A/V timing without accepting media content."""
        if self._metrics is None:
            return
        if media_debt_seconds is not None:
            self._metrics.observe_media_debt(media_debt_seconds)
        if av_offset_seconds is not None:
            self._metrics.observe_av_offset(av_offset_seconds)

    def observe_audio_pacing(
        self,
        *,
        lag_seconds: float = 0.0,
        rebase_count: int = 0,
        min_release_interval_seconds: Optional[float] = None,
        catch_up_burst_count: int = 0,
    ) -> None:
        if self._metrics is None:
            return
        self._metrics.observe_audio_pacing(
            lag_seconds=lag_seconds,
            rebase_count=rebase_count,
            min_release_interval_seconds=min_release_interval_seconds,
            catch_up_burst_count=catch_up_burst_count,
        )

    def observe_tts_onset_preroll_ms(self, milliseconds: float) -> None:
        if self._metrics is None:
            return
        self._metrics.observe_tts_onset_preroll_ms(milliseconds)

    def observe_tts_retry(self, *, after_commit: bool) -> None:
        if self._metrics is None:
            return
        self._metrics.observe_tts_retry(after_commit=after_commit)

    def mark_stage_start(self, stage: str) -> None:
        if self._metrics is not None:
            self._metrics.mark_stage_start(stage)

    def mark_stage_end(self, stage: str) -> None:
        if self._metrics is not None:
            self._metrics.mark_stage_end(stage)

    def _on_llm_chunk(self, text: str, eventpoint: dict) -> None:
        """Forward generated text to the event loop without blocking LLM work."""
        if not text or self._closed or self._pipeline_mode != "streaming":
            return
        turn_id = str(eventpoint.get("turn_id") or self._turn_id or "")
        generation = eventpoint.get("generation")
        if not turn_id or generation is None or not self._is_current(turn_id, int(generation)):
            return
        self._silent_output_frames = 0
        sequence = int(eventpoint.get("llm_sequence", 0))
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(
            partial(
                self._emit,
                "assistant_response_delta",
                turn_id=turn_id,
                sequence=sequence,
                text_delta=text,
            )
        )

    def _start_turn_context(self, turn_id: str) -> None:
        if (
            self._turn_context is None
            or self._turn_context.turn_id != turn_id
            or self._turn_context.generation != self._generation
        ):
            self._turn_context = TurnContext(
                turn_id=turn_id,
                generation=self._generation,
            )
            # Capture once at turn acceptance. A later control-panel save only
            # affects the next turn, even while this one is still generating.
            self._rules_snapshot = snapshot_from_config(self.config)
            enabled = bool(
                getattr(getattr(self.config, "reply_streaming", None), "enabled", False)
            )
            self._pipeline_mode = (
                self._circuit_breaker.mode_for_next_turn() if enabled else "legacy"
            )
            if enabled and self._pipeline_mode == "legacy":
                logger.info(
                    "reply streaming circuit fallback session=%s mode=legacy",
                    self.sessionid,
                )
            with self._fragment_lock:
                self._fragment_texts.clear()
                self._played_fragment_sequences.clear()
                self._ended_fragment_sequences.clear()
                self._played_fragments.clear()
                self._llm_finished = False
        if self._metrics is None or self._metrics.snapshot()["turn_id"] != turn_id:
            self._metrics = TurnMetrics(turn_id, clock=self._metrics_clock)

    def _commit_history(
        self,
        terminal_reason: str,
        *,
        turn_id: Optional[str] = None,
    ) -> bool:
        target_turn = turn_id or self._turn_id
        if not target_turn or target_turn in self._history_finalized_turns:
            return False
        self._history_finalized_turns.add(target_turn)
        played_text = self.played_assistant_text
        self._emit(
            "turn_committed",
            turn_id=target_turn,
            played_text=played_text,
            reason=str(terminal_reason),
        )
        return commit_session_history(
            self.sessionid,
            target_turn,
            assistant_text=played_text,
            terminal_reason=terminal_reason,
        )

    def record_streaming_health_probe(self, healthy: bool) -> bool:
        """Allow an external content-free probe to close the breaker."""
        recovered = self._circuit_breaker.record_health_probe(healthy)
        logger.info(
            "reply streaming health probe session=%s result=%s",
            self.sessionid,
            "healthy" if healthy else "unhealthy",
        )
        return recovered

    def _close_gate(self) -> None:
        self._gate_open = False
        self._segmenter_reset_pending = True

    def _refresh_gate(self) -> None:
        was_open = self._gate_open
        allowed = (
            not self._closed
            and not self._prepare_error
            and self._event_sink is not None
            and self._capture_requested
            and not self._manual_pause
            and not self._output_active
            and self._turn_task is None
            and self._finalize_task is None
            and self._turn_id is None
        )
        self._gate_open = allowed
        if allowed and not was_open:
            self._segmenter_reset_pending = True
        if allowed and self._metrics is not None:
            self._metrics.mark_listening_resumed()
        self._emit("state", state="listening" if allowed else "paused")

    def _on_board_event(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        payload_turn = payload.get("turn_id") or self._turn_id
        if not payload_turn or not self._is_current(str(payload_turn), self._generation):
            return
        loop = self._event_loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._dispatch_board_event, payload)
        else:
            self._dispatch_board_event(payload)

    def _on_mode_event(self, turn_id: str, mode) -> None:
        """Forward parser-confirmed mode from the worker thread safely."""
        if not self._is_current(str(turn_id), self._generation):
            return
        value = getattr(mode, "value", str(mode))
        loop = self._event_loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(
                partial(
                    self._emit,
                    "assistant_response_mode",
                    turn_id=turn_id,
                    mode=value,
                )
            )
        else:
            self._emit("assistant_response_mode", turn_id=turn_id, mode=value)

    def _dispatch_board_event(self, payload: dict) -> None:
        turn_id = payload.get("turn_id") or self._turn_id
        board_id = str(payload.get("board_id") or turn_id or "")
        if "items" in payload:
            items = payload.get("items") or []
            board_obj = {
                "title": str(payload.get("title") or ""),
                "summary": payload.get("summary"),
                "items": items,
            }
            self._emit(
                "assistant_board",
                turn_id=turn_id,
                board_id=board_id,
                board=board_obj,
            )
            if payload.get("incremental"):
                self._emit("board_end", turn_id=turn_id, board_id=board_id)
                return
            self._emit(
                "board_begin",
                turn_id=turn_id,
                board_id=board_id,
                title=board_obj["title"],
            )
            for idx, item in enumerate(items):
                self._emit(
                    "board_item",
                    turn_id=turn_id,
                    board_id=board_id,
                    index=idx,
                    title=str(item.get("title") or ""),
                    body=str(item.get("content") or item.get("body") or ""),
                )
            self._emit("board_end", turn_id=turn_id, board_id=board_id)
            return

        kind = str(payload.get("kind") or "")
        if kind == "begin":
            self._emit(
                "board_begin",
                turn_id=turn_id,
                board_id=board_id,
                title=str(payload.get("title") or ""),
            )
            return
        if kind == "item":
            self._emit(
                "board_item",
                turn_id=turn_id,
                board_id=board_id,
                index=int(payload.get("index") or 0),
                title=str(payload.get("title") or ""),
                body=str(payload.get("body") or ""),
            )
            return
        if kind == "end":
            self._emit("board_end", turn_id=turn_id, board_id=board_id)

    def _emit(self, event_type: str, *, turn_id: Optional[str] = None, **payload) -> None:
        if self._event_sink is None:
            return
        self._sequence += 1
        event = {
            "type": event_type,
            "seq": self._sequence,
            "turn_id": turn_id if turn_id is not None else self._turn_id,
            **payload,
        }
        try:
            self._event_sink(json.dumps(event, ensure_ascii=False))
        except Exception as exc:
            logger.warning(f"Voice event channel failed closed: {exc}")
            self._event_sink = None
            self._close_gate()
