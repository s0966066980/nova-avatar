# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""One WebRTC microphone session and its server-owned conversation turns.

The class deliberately exposes only audio/control input and an event sink.  VAD
buffers, turn identity, stale-result protection and STT -> LLM -> TTS ordering
remain private so routes and UI cannot accidentally create competing pipelines.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from functools import partial
import json
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event, RLock
from typing import Callable, Optional
from uuid import uuid4

import numpy as np
import soundfile as sf
from av.audio.resampler import AudioResampler

from src.asr.factory import get_asr_engine
from src.greetings.controller import IdleGreetingController
from src.greetings.content import GreetingError
from src.tts.base import sanitize_speech_text
from src.llm.service import (
    remember_greeting,
    acknowledge_session_board_item,
    clear_session_history,
    commit_session_history,
    discard_pending_history,
    llm_response,
    prepare_spoken_history,
)
from src.llm.rules import snapshot_from_config
from src.ragflow.client import RagFlowClient, retrieval_prompt
from src.ragflow.settings import avatar_settings
from src.server.reply_streaming.circuit_breaker import ReplyCircuitBreaker
from src.server.reply_streaming.metrics import TurnMetrics, observe_stages
from src.server.reply_streaming.turn import TurnContext, TurnEnvelope, TurnState
from src.utils.logging import logger
from src.vad.service import create_segmenter


EventSink = Callable[[str], None]
TestResultSink = Callable[[dict], object]
OUTPUT_STALL_FRAMES = 50  # one second at the 20 ms audio commit clock
# The main answer waits at most this long for retrieval (ADR 0022).
RETRIEVAL_BUDGET_SECONDS = 0.4
# Answer content a held turn keeps from clients until routing releases it.
_HELD_EVENT_TYPES = frozenset({
    "rag_retrieval",
    "assistant_response_start",
    "assistant_response_delta",
    "assistant_response_mode",
    "assistant_board",
    "board_begin",
    "board_item",
    "board_end",
})


def speech_input_rejection_reason(
    audio: np.ndarray,
    sample_rate: int,
    speech_ms: int,
    transcription: Optional[dict],
    settings,
) -> Optional[str]:
    """Return a privacy-safe reason when speech input must not reach the LLM."""
    min_speech_ms = max(0, int(getattr(settings, "min_speech_ms", 0) or 0))
    if min_speech_ms and speech_ms and speech_ms < min_speech_ms:
        return "speech_too_short"

    min_audio_rms = max(0.0, float(getattr(settings, "min_audio_rms", 0.0) or 0.0))
    if min_audio_rms:
        samples = np.asarray(audio, dtype=np.float32)
        rms = float(np.sqrt(np.mean(np.square(samples / 32768.0)))) if samples.size else 0.0
        if rms < min_audio_rms:
            return "audio_too_quiet"

    if not transcription:
        return None
    text = str(transcription.get("text", "")).strip()
    if not text:
        return "empty_transcript"

    confidence = transcription.get("confidence", transcription.get("avg_confidence"))
    min_confidence = float(getattr(settings, "min_confidence", 0.0) or 0.0)
    if confidence is not None and min_confidence:
        try:
            if float(confidence) < min_confidence:
                return "transcript_low_confidence"
        except (TypeError, ValueError):
            return "transcript_invalid_confidence"
    return None


class RecentKeys:
    """A set that forgets its oldest members beyond ``limit``.

    Per-turn duplicate guards only ever see the latest few turns, so a
    long-running kiosk session must not remember every turn it has served.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._items: OrderedDict = OrderedDict()

    def __contains__(self, item) -> bool:
        return item in self._items

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item) -> None:
        self._items[item] = None
        self._items.move_to_end(item)
        while len(self._items) > self._limit:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


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
        test_result_sink: Optional[TestResultSink] = None,
    ) -> None:
        self.sessionid = sessionid
        self.config = deepcopy(config)
        self.config.conversation_snapshot = True
        self.avatar = avatar
        self.avatar.config = self.config
        self._presenter = presenter if presenter in {"console", "stage"} else "console"
        self._event_sink: Optional[EventSink] = None
        self._test_result_sink = test_result_sink
        self._sequence = 0
        self._role_coordinator = None
        self._role_reset_task = None
        self._presentation = None
        self._turn_origin = "visitor"
        self._greeting_trial_preparation = None
        self._greeting_text = ""
        self._greeting_tts_config = None
        self._greeting_started = False
        self._stage_ready = False
        self._greeting_returning = False
        self.greetings = IdleGreetingController(self, clock=clock)
        self._turn_id: Optional[str] = None
        self._generation = 0
        self._capture_requested = True
        self._gate_open = False
        self._manual_pause = False
        self._closed = False
        from src.server.conversations import defaults, configure_avatar
        self._conversation = defaults(self.config)
        self._role_voices = {}
        self._voice_overrides = set()
        self._composer_has_draft = False
        self._settings_switching = False
        self._pending_history_limit = None
        self._settings_lock = asyncio.Lock()
        self.bind_conversation()
        self._prepare_error = ""
        self._preparing = False
        self._segmenter = None
        self._asr = None
        self._track_task: Optional[asyncio.Task] = None
        self._turn_task: Optional[asyncio.Task] = None
        self._tail_task: Optional[asyncio.Task] = None
        self._finalize_task: Optional[asyncio.Task] = None
        # Fire-and-forget work started by control messages; close() cancels it.
        self._background_tasks: set[asyncio.Task] = set()
        self._output_active = False
        self._metrics_clock = clock
        self._metrics: Optional[TurnMetrics] = None
        self._turn_context: Optional[TurnContext] = None
        self._rules_snapshot = None
        self._assistant_profile_snapshot = None
        self._rag_snapshot = {"enabled": False, "dataset_ids": []}
        self._circuit_breaker = ReplyCircuitBreaker(clock=clock)
        self._pipeline_mode = "legacy"
        self._fragment_lock = RLock()
        self._fragment_texts: dict[int, str] = {}
        self._played_fragment_sequences: set[int] = set()
        self._ended_fragment_sequences: set[int] = set()
        self._played_fragments: list[str] = []
        self._history_finalized_turns = RecentKeys(64)
        self._metrics_emitted_turns = RecentKeys(64)
        self._board_display_receipts = RecentKeys(256)
        self._conversation_dirty = False
        self._idle_reset_task: Optional[asyncio.Task] = None
        from src.server.attachments import AttachmentStore
        self.attachments = AttachmentStore()
        self._attachment_busy = 0
        self._composer_editing = False
        self._client_request_id = None
        self._cancelled_text_requests: set[str] = set()
        # Serializes every interrupt source with turn acceptance, so a tail
        # guard can never clear a turn accepted while it was sleeping.
        self._turn_lock = asyncio.Lock()
        self._llm_finished = False
        # Playback hold: (turn_id, generation) of a main answer generated
        # before routing decided. TTS threads wait at the audio boundary.
        self._playback_hold: Optional[tuple[str, int]] = None
        self._playback_released = Event()
        self._playback_released.set()
        self._playback_blocked_at: Optional[float] = None
        self._held_events: list[tuple[str, Optional[str], dict]] = []
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
                fragment_playback_ended=self.fragment_playback_ended,
                on_tts_onset_preroll_ms=self.observe_tts_onset_preroll_ms,
                on_tts_retry=self.observe_tts_retry,
                on_stage_end=self.mark_stage_end,
                on_llm_chunk=self._on_llm_chunk,
            )

    def bind_conversation(self):
        from src.server.conversations import configure_avatar
        identity = getattr(self.config, 'profile_id', '')
        if identity not in self._voice_overrides:
            self._role_voices[identity] = {
                'voice_zh_tw': getattr(getattr(self.config, 'tts', None), 'ref_file', '') or self._conversation['voice_zh_tw'],
                'voice_en_us': getattr(getattr(self.config, 'tts', None), 'voice_en_us', 'en-US-JennyNeural'),
            }
        self._conversation.update(self._role_voices[identity])
        configure_avatar(self.avatar, self._conversation)
        self.config = self.avatar.config

    async def prepare(self) -> None:
        """Prewarm Silero and STT before the session may announce listening."""
        # Record the owning loop before any turn exists: idle greetings and
        # other worker-thread callbacks must marshal back onto it.
        self._event_loop = asyncio.get_running_loop()
        if not bool(getattr(self.config.vad, "enabled", True)):
            self._preparing = False
            self._close_gate()
            self._emit("state", state="paused")
            return
        self._preparing = True
        self._close_gate()
        self._emit("state", state="preparing")
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._prepare_sync)
            if self._conversation['locale'] == 'en-US':
                from src.server.conversations import warm_voice
                await warm_voice(self.config, self._conversation)
        except Exception as exc:
            self._preparing = False
            self._prepare_error = str(exc)
            self._gate_open = False
            logger.exception("Voice session prewarm failed")
            self._emit("state", state="degraded", error=self._prepare_error)
            return
        self._preparing = False
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
        # Per-call language options keep the shared recognizer immutable.
        if getattr(getattr(self.config, "app", None), "prewarm", True):
            self._asr.prewarm()
        else:
            self._asr.ensure_ready()

    def attach_event_sink(self, sink: EventSink) -> None:
        self._event_sink = sink
        self._emit('conversation_settings', **self._conversation)
        if self._prepare_error:
            self._emit("state", state="degraded", error=self._prepare_error)
        else:
            self._refresh_gate()
        if self._role_coordinator is not None:
            self._role_coordinator.notify(self)
        if self._presentation is not None:
            self._presentation.replay(self)

    @property
    def event_sink_ready(self) -> bool:
        """Whether asynchronous text/voice reply events have a destination."""
        return self._event_sink is not None

    def detach_event_sink(self) -> None:
        self._event_sink = None
        self._stage_ready = False
        self.greetings.reset(stop_playing=True)
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
        if kind == 'conversation_settings':
            self._spawn(self._apply_conversation_control(message.get('settings', {})))
            return
        roles = self._role_coordinator
        if kind in {"role_return", "role_stop"} and roles is not None:
            async def control_role():
                try:
                    if kind == "role_return":
                        await roles.return_to_main(self)
                    elif kind == "role_stop":
                        await self.interrupt()
                except Exception:
                    self._emit("role_error", message="目前無法執行角色操作，請等目前輪次結束後再試。")
            self._spawn(control_role())
            return
        if kind == "stage_ready" and self._presenter == "stage":
            self._stage_ready = (message.get('audible') is True and message.get('interaction') is True
                and (message.get('microphone') is True or bool(getattr(self.config.stage, 'composer_enabled', False))))
            self.greetings.refresh()
            return
        if kind == "capture":
            enabled = bool(message.get("enabled"))
            finalize = (
                not enabled
                and bool(message.get("finalize"))
                and self._segmenter is not None
                and self._gate_open
                and self._finalize_task is None
            )
            self._capture_requested = enabled
            self._manual_pause = bool(message.get("manual_pause", not enabled))
            if finalize:
                # Preserve the current segment until flush runs in the same
                # ordered worker as resampling/VAD.
                self._gate_open = False
                self._emit("state", state="paused")
                self._finalize_task = self._spawn(self._finalize_capture())
                return
            if enabled and self._asr is None and not self._preparing:
                self._preparing = True
                self._spawn(self.prepare())
            if enabled and self._output_active:
                return
            self._refresh_gate()
        elif kind == "interrupt":
            self._spawn(self.interrupt())
        elif kind == "board_displayed":
            if self._presentation is not None and self._presentation.acknowledge_board(self, message):
                return
            self._acknowledge_board(message, presenter=self._presenter)

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _acknowledge_board(self, message, *, presenter):
        turn_id = str(message.get("turn_id") or "")
        board_id = str(message.get("board_id") or "")
        item_index = message.get("item_index")
        if message.get("presenter") != presenter or not turn_id or board_id != turn_id:
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

    def start_track(self, track, *, on_lost: Optional[Callable[[], None]] = None) -> None:
        """Consume microphone audio; ``on_lost`` runs if the track fails.

        aiortc keeps buffering a failed track's RTP in an unbounded queue, so
        the owner must close the peer connection and let the page reconnect.
        """
        if self._track_task:
            self._track_task.cancel()
        self._track_task = asyncio.create_task(self._consume_track(track, on_lost))

    async def _apply_conversation_control(self, values: dict) -> None:
        try:
            await self.apply_conversation(values)
        except (ValueError, RuntimeError, TypeError) as exc:
            self._emit('conversation_settings_error', error=str(exc), **self._conversation)

    async def apply_conversation(self, values: dict) -> None:
        from src.server.conversations import validate, check_language_support, configure_avatar, warm_voice
        from src.llm.service import set_session_history_limit
        async with self._settings_lock:
            candidate = validate(values, self._conversation)
            voice_change = any(candidate[key] != self._conversation[key] for key in ("voice_zh_tw", "voice_en_us"))
            language_change = any(candidate[key] != self._conversation[key]
                                  for key in ('locale', 'voice_zh_tw', 'voice_en_us'))
            if language_change:
                if (getattr(self.config.tts, 'type', '') != 'edgetts'
                        and any(candidate[key] != self._conversation[key]
                                for key in ('voice_zh_tw', 'voice_en_us'))):
                    raise ValueError('voice_controls_require_edge_tts')
                check_language_support(self.config, candidate['locale'])
                capture, paused = self._capture_requested, self._manual_pause
                self._settings_switching = True
                self._emit('conversation_settings_pending')
                self._close_gate()
                try:
                    await self.interrupt()
                    if self._closed:
                        raise RuntimeError('對話已結束')
                    await warm_voice(self.config, candidate)
                    if self._closed:
                        raise RuntimeError('對話已結束')
                    # Old media is fenced before changing the per-avatar config.
                    configure_avatar(self.avatar, candidate)
                except Exception:
                    self._emit('conversation_settings_error', error='voice_unavailable', **self._conversation)
                    raise
                finally:
                    self._settings_switching = False
                    self._capture_requested, self._manual_pause = capture, paused
                    self._refresh_gate()
            limit = candidate['history_max_messages']
            if self._turn_id is not None or self._turn_task is not None or self._output_active:
                self._pending_history_limit = limit
                candidate['history_max_messages'] = self._conversation['history_max_messages']
            else:
                self._pending_history_limit = None
                set_session_history_limit(self.sessionid, limit)
            self._conversation = candidate
            if voice_change:
                self._voice_overrides.add(getattr(self.config, "profile_id", ""))
            self._role_voices[getattr(self.config, 'profile_id', '')] = {key: candidate[key] for key in ('voice_zh_tw', 'voice_en_us')}
            configure_avatar(self.avatar, candidate)
            self._emit('conversation_settings', **self._conversation)

    async def _consume_track(self, track, on_lost=None) -> None:
        while not self._closed:
            try:
                frame = await track.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Only the track itself ending or failing to deliver audio is a loss.
                self._track_lost(exc, on_lost)
                return
            # Keep draining paused uplink audio without scheduling work
            # whose PCM the closed capture gate would immediately discard.
            if not self._gate_open or self._segmenter is None or self._closed:
                continue
            try:
                await self._process_frame(frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                # One bad frame or a failed turn start must not hang up the peer.
                logger.exception("Microphone frame processing failed; continuing")

    async def _process_frame(self, frame) -> None:
        loop = asyncio.get_running_loop()
        generation = self._generation
        pcm_chunks = await loop.run_in_executor(
            self._voice_executor,
            self._resample_frame_sync,
            frame,
        )
        if generation != self._generation:
            return
        for pcm in pcm_chunks:
            await self.feed_pcm(pcm)

    def _track_lost(self, exc: Exception, on_lost) -> None:
        if self._closed:
            return
        logger.warning(f"Microphone track ended: {exc}")
        self._emit("state", state="reconnecting", error="microphone_track_lost")
        self._stage_ready = False
        self.greetings.reset(stop_playing=True)
        self._close_gate()
        if on_lost is not None:
            on_lost()

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
        generation_at_input = self._generation
        preparing_at_input = self.greetings.preparation is not None or (self.is_greeting and not self._greeting_started)
        was_speaking, is_speaking, segments = await loop.run_in_executor(
            self._voice_executor,
            self._segment_pcm_sync,
            pcm,
        )
        if self._closed or self._generation != generation_at_input:
            return
        # Input accepted before first output keeps priority even when VAD's
        # worker finishes just after the first greeting audio frame commits.
        if not self._gate_open and not (preparing_at_input and self.is_greeting):
            return
        if (not was_speaking and is_speaking) or segments:
            self.greetings.reset(stop_playing=preparing_at_input)
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
        endpoint_wait = getattr(segment, "endpoint_wait_ms", None)
        if endpoint_wait is not None:
            self._metrics.record_stage_duration("vad_endpoint", endpoint_wait / 1000.0)
        generation = self._generation
        self._turn_task = asyncio.create_task(
            self._process_turn(
                segment.audio,
                segment.sample_rate,
                self._turn_id,
                generation,
                speech_ms=int(getattr(segment, "speech_ms", 0) or 0),
            )
        )

    async def start_text_turn(self, text: str, *, interrupt: bool = True,
                              _handoff_id: str | None = None,
                              _speak_only: bool = False, attachments=None, request_id=None) -> dict:
        """Start a typed turn through the same reply pipeline as speech."""
        text = str(text or "").strip()
        selected = self.attachments.selection if attachments is None else attachments
        self.attachments.validate_selection(selected)
        if not text and not selected:
            raise ValueError("文字訊息不可為空")
        if self._closed:
            raise RuntimeError("語音工作階段已關閉")
        roles = self._role_coordinator
        continuation = roles.continuations.get(self.sessionid, {}) if roles is not None else {}
        accepted_handoff = (roles is not None and _handoff_id is not None
            and continuation.get("id") == _handoff_id
            and roles.enabled and roles.phase == "ready"
            and roles.current_id == continuation.get('target_profile_id'))
        if roles is not None and not accepted_handoff and not roles.input_allowed(self):
            raise RuntimeError("目前角色正在轉場，請稍候")
        self.greetings.reset()
        if request_id and request_id in self._cancelled_text_requests:
            raise ValueError('cancelled')
        if selected:
            from src.server.attachments import vision_ready
            if not await asyncio.to_thread(vision_ready, self.config):
                raise ValueError('vision_unavailable')
        # A replacement and cancellation may arrive together. Serialize their
        # interrupt/accept steps, and reject stale validation before it can
        # interrupt the replacement's answer.
        async with self._turn_lock:
            if _handoff_id is not None and (not accepted_handoff
                    or roles.continuations.get(self.sessionid) is not continuation):
                raise ValueError('cancelled')
            if request_id and request_id in self._cancelled_text_requests:
                raise ValueError('cancelled')
            if interrupt and (
                self._turn_id is not None
                or self._turn_task is not None
                or self._output_active
            ):
                await self._interrupt_locked()
            if self._turn_id is not None or self._turn_task is not None:
                raise RuntimeError("上一個對話輪次尚未結束")
            if request_id and request_id in self._cancelled_text_requests:
                raise ValueError('cancelled')
            if _handoff_id is None and roles is not None:
                roles.cancel(self.sessionid)
            self.attachments.select(selected, submitted=True)
            self._turn_id = uuid4().hex
            self._start_turn_context(self._turn_id)
            self._client_request_id = request_id
            # Text and microphone turns own the same single-turn session.
            # Close capture before yielding so VAD cannot replace this turn ID
            # while it is waiting for first audio.
            self._close_gate()
            self._metrics.mark_speech_end()
            generation = self._generation
            turn_id = self._turn_id
            if accepted_handoff:
                continuation['target_turn'] = turn_id
            self._turn_task = asyncio.create_task(
                self._process_text_turn(text, turn_id, generation, speak_only=_speak_only)
            )
            return {
                "turn_id": turn_id,
                "reply_mode": self._pipeline_mode,
                "delivery": "events",
            }

    async def start_read_aloud_turn(self, text: str, *, interrupt: bool = True) -> dict:
        """Send fixed text to TTS with the normal capture and media fences."""
        text = str(text or "").strip()
        if not text:
            raise ValueError("朗讀文字不可為空")
        if self._closed:
            raise RuntimeError("語音工作階段已關閉")
        async with self._turn_lock:
            return await self._start_read_aloud_locked(text, interrupt=interrupt)

    async def _start_read_aloud_locked(self, text: str, *, interrupt: bool) -> dict:
        if interrupt and (
            self._turn_id is not None
            or self._turn_task is not None
            or self._output_active
        ):
            await self._interrupt_locked()
        if self._turn_id is not None or self._turn_task is not None:
            raise RuntimeError("上一個對話輪次尚未結束")
        self._turn_id = uuid4().hex
        self._start_turn_context(self._turn_id)
        self._pipeline_mode = "read_aloud"
        self._event_loop = asyncio.get_running_loop()
        self._close_gate()
        self._metrics.mark_speech_end()
        self._llm_finished = True
        envelope = {
            "turn_id": self._turn_id,
            "generation": self._generation,
            "fragment_sequence": 0,
        }
        self._emit("state", state="tts_ready", turn_id=self._turn_id)
        turn_id = self._turn_id
        self.avatar.put_msg_txt(text, envelope)
        self._end_turn_if_nothing_speakable(turn_id)
        return {"turn_id": turn_id, "reply_mode": "read_aloud", "delivery": "events"}

    async def cancel_text_request(self, request_id: str) -> None:
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
            raise ValueError('invalid_request')
        if len(self._cancelled_text_requests) >= 128:
            self._cancelled_text_requests.pop()
        self._cancelled_text_requests.add(request_id)
        async with self._turn_lock:
            if request_id == self._client_request_id:
                await self._interrupt_locked()

    def _segment_pcm_sync(self, pcm: np.ndarray):
        if self._segmenter_reset_pending:
            self._segmenter.reset()
            self._segmenter_reset_pending = False
        was_speaking = self._segmenter.is_speaking
        segments = list(self._segmenter.process(pcm))
        return was_speaking, self._segmenter.is_speaking, segments

    async def _finalize_capture(self) -> None:
        loop = asyncio.get_running_loop()
        generation = self._generation
        try:
            segments = await loop.run_in_executor(
                self._voice_executor,
                lambda: list(self._segmenter.flush()),
            )
            self._segmenter_reset_pending = True
            if self._closed or generation != self._generation:
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
                    speech_ms=int(getattr(segment, "speech_ms", 0) or 0),
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                logger.exception("Voice capture finalize failed")
                self._emit("state", state="error", error=str(exc))
        finally:
            if self._finalize_task is asyncio.current_task():
                self._finalize_task = None
            if not self._closed and self._turn_task is None:
                self._refresh_gate()

    async def _process_turn(
        self,
        audio: np.ndarray,
        sample_rate: int,
        turn_id: str,
        generation: int,
        *,
        speech_ms: int = 0,
    ) -> None:
        loop = asyncio.get_running_loop()
        try:
            rejection = speech_input_rejection_reason(
                audio, sample_rate, speech_ms, None, self.config.asr
            )
            if rejection:
                logger.info("Dropped speech turn before ASR reason=%s", rejection)
                self._release_rejected_speech_turn(turn_id, generation)
                return
            self._emit("state", state="stt", turn_id=turn_id)
            wav = BytesIO()
            sf.write(wav, audio, sample_rate, format="WAV", subtype="PCM_16")
            self.mark_stage_start("asr")
            if getattr(self._asr, 'supports_language_options', False) is True:
                result = await loop.run_in_executor(None, partial(
                    self._asr.transcribe, wav.getvalue(), language='auto'))
            else:
                result = await loop.run_in_executor(None, self._asr.transcribe, wav.getvalue())
            self.mark_stage_end("asr")
            if not self._is_current(turn_id, generation):
                return
            rejection = speech_input_rejection_reason(
                audio, sample_rate, speech_ms, result, self.config.asr
            )
            if rejection:
                logger.info("Dropped speech turn after ASR reason=%s", rejection)
                self._release_rejected_speech_turn(turn_id, generation)
                return
            text = str(result.get("text", "")).strip()
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

    def _release_rejected_speech_turn(self, turn_id: str, generation: int) -> None:
        """Release a discarded speech turn and immediately resume listening."""
        if not self._is_current(turn_id, generation):
            return
        self._turn_id = None
        self._turn_task = None
        self._refresh_gate()

    async def _process_text_turn(
        self, text: str, turn_id: str, generation: int, *, speak_only: bool = False
    ) -> None:
        try:
            if speak_only:
                self._speak_fixed(text, text, turn_id, generation, "echo")
                return
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
        if self._metrics is not None:
            self._metrics.mark_prompt_accepted()
        self.mark_stage_start("pre_answer")
        roles = self._role_coordinator
        if roles is None or not roles.enabled:
            await self._answer_turn(text, turn_id, generation, input_source, None)
            return
        if not roles.continues(self, turn_id):
            await self._route_concurrently(roles, text, turn_id, generation, input_source)
            return
        # A handoff continuation already carries its plan; no routing call.
        self.mark_stage_start("routing")
        role_plan = await roles.before_generate(self, text, turn_id, generation)
        self.mark_stage_end("routing")
        await self._follow_role_plan(text, turn_id, generation, input_source, role_plan)

    async def _route_concurrently(self, roles, text, turn_id, generation, input_source):
        """Route while the main answer is generated; play it only if routing keeps it.

        The answer starts after retrieval (bounded) with the plan routing
        returns when it keeps the current role, and its audio is held at the
        TTS boundary. An equal routed plan releases it; any other plan fences
        it by generation and the turn follows the routed plan (ADR 0022).
        """
        speculative = roles.speculative_plan()
        self._hold_playback(turn_id, generation)
        self.mark_stage_start("routing")
        routing = asyncio.create_task(roles.before_generate(self, text, turn_id, generation))
        inputs = asyncio.create_task(self._answer_inputs(text, turn_id, generation))
        worker: list[asyncio.Future] = []
        answer = asyncio.create_task(self._speculate(
            inputs, turn_id, generation, input_source, speculative, worker))
        try:
            plan = await routing
        except BaseException:
            inputs.cancel()
            answer.cancel()
            raise
        self.mark_stage_end("routing")
        if not self._is_current(turn_id, generation):
            inputs.cancel()
            answer.cancel()
            return
        if plan.get("cancelled"):
            inputs.cancel()
            await self._discard_speculation(turn_id, answer, worker)
            return
        if plan == speculative:
            self._release_playback(turn_id, generation)
            response = await answer
            if response is not None:
                self._finish_answer(response, turn_id, generation, input_source)
            return
        prepared = None
        if "fixed" in plan:
            inputs.cancel()
        else:
            try:
                # Reuse this turn's attachments and retrieval for the new answer.
                prepared = await inputs
            except asyncio.CancelledError:
                answer.cancel()
                raise
            except Exception as exc:
                prepared = exc
        generation = await self._discard_speculation(turn_id, answer, worker)
        try:
            if isinstance(prepared, Exception):
                raise prepared
            await self._follow_role_plan(text, turn_id, generation, input_source, plan, prepared)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The caller's generation was fenced with the discarded answer.
            self._handle_turn_error(exc, turn_id, generation)

    async def _speculate(self, inputs, turn_id, generation, input_source, plan, worker):
        prepared = await inputs
        if prepared is None:
            return None
        return await self._stream_answer(
            prepared, turn_id, generation, input_source, plan, worker=worker)

    async def _discard_speculation(self, turn_id, answer, worker) -> int:
        """Fence an answer routing did not keep; return the turn's new generation."""
        generation = self._fence_held_answer(turn_id)
        answer.cancel()
        await asyncio.gather(answer, return_exceptions=True)
        if worker:
            # The fenced worker stops at its next chunk. Its pending history
            # must be gone before the routed reply opens the same turn's, and
            # a fragment it queued meanwhile must not delay that reply's TTS.
            await asyncio.gather(worker[0], return_exceptions=True)
            self.avatar.flush_talk()
        discard_pending_history(self.avatar, turn_id)
        return generation

    def _fence_held_answer(self, turn_id: str) -> int:
        """Same turn, new generation: everything the held answer queued is stale."""
        self._generation += 1
        self._turn_context = TurnContext(turn_id=turn_id, generation=self._generation)
        self._release_playback(turn_id, None)
        self.avatar.flush_talk()
        if self._media_player is not None:
            self._media_player.discard_stale_media()
        with self._fragment_lock:
            self._fragment_texts.clear()
            self._played_fragment_sequences.clear()
            self._ended_fragment_sequences.clear()
            self._played_fragments.clear()
            self._llm_finished = False
        if self._metrics is not None:
            self._metrics.discard_answer_stages()
        return self._generation

    async def _follow_role_plan(self, text, turn_id, generation, input_source, role_plan,
                                prepared=None):
        if not self._is_current(turn_id, generation) or role_plan.get("cancelled"):
            return
        if "fixed" in role_plan:
            self._speak_fixed(text, role_plan["fixed"], turn_id, generation, input_source)
            return
        weather = role_plan.get("weather")
        if weather is not None:
            self._emit("weather_result", turn_id=turn_id, result=weather)
            if weather["status"] != "available":
                explanation = ("目前提供未來七天的天氣預報，請指定這個範圍內的日期。"
                               if weather["status"] == "out_of_range" else
                               "目前暫時無法取得所問的最新天氣資料，請稍後再試。")
                self._speak_fixed(text, explanation, turn_id, generation, input_source)
                return
            # Facts join this role's own Prompt/RAG/rules below. A successful
            # tool result must not bypass the specialist's answer pipeline.
        await self._answer_turn(text, turn_id, generation, input_source, role_plan, prepared)

    async def _answer_turn(self, text, turn_id, generation, input_source, role_plan,
                           prepared=None):
        if prepared is None:
            prepared = await self._answer_inputs(text, turn_id, generation)
            if prepared is None:
                return
        response = await self._stream_answer(
            prepared, turn_id, generation, input_source, role_plan)
        if response is not None:
            self._finish_answer(response, turn_id, generation, input_source)

    async def _answer_inputs(self, text, turn_id, generation):
        """Attachments and bounded retrieval; ``None`` once the turn is stale."""
        loop = asyncio.get_running_loop()
        resolved = self.attachments.validate_selection(self.attachments.selection)
        if resolved:
            from src.server.attachments import vision_ready
            if not await asyncio.to_thread(vision_ready, self.config):
                raise ValueError('vision_unavailable')
            self._emit('attachment_status', turn_id=turn_id, state='reading', total=sum(len(p) for _, p in resolved))
            def progress(index, total, source):
                loop.call_soon_threadsafe(lambda: self._emit('attachment_status', turn_id=turn_id,
                    state='analyzing', index=index, total=total, source=source)
                    if self._is_current(turn_id, generation) else None)
            text = await asyncio.to_thread(self.attachments.prepare_question, text, resolved,
                self.avatar.config if getattr(self.avatar, 'config', None) else self.config,
                progress, lambda: self._is_current(turn_id, generation))
            if not self._is_current(turn_id, generation):
                return None
        rag_result = None
        rag_selection = self._rag_snapshot
        if rag_selection["enabled"] and rag_selection["dataset_ids"]:
            self._emit("state", state="retrieving", turn_id=turn_id)
            self.mark_stage_start("retrieval")
            try:
                rag_result = await asyncio.wait_for(RagFlowClient().retrieve(
                    text, rag_selection["dataset_ids"],
                    **({"document_ids": rag_selection["document_ids"]}
                       if rag_selection.get("document_scope") == "selected" else {}),
                ), RETRIEVAL_BUDGET_SECONDS)
            except asyncio.TimeoutError:
                rag_result = {"status": "timeout", "sources": []}
                logger.info("RAGFlow retrieval exceeded %.1fs; answering without it",
                            RETRIEVAL_BUDGET_SECONDS)
            except Exception as exc:
                rag_result = {"status": "unavailable", "sources": []}
                logger.warning(f"RAGFlow retrieval unavailable: {type(exc).__name__}")
            self.mark_stage_end("retrieval")
            if not self._is_current(turn_id, generation):
                return None
        return text, rag_result

    async def _stream_answer(self, prepared, turn_id, generation, input_source, role_plan,
                             *, worker=None):
        """Generate the main answer; ``None`` once the turn is stale."""
        loop = asyncio.get_running_loop()
        text, rag_result = prepared
        if not self._is_current(turn_id, generation):
            return None
        if rag_result is not None:
            self._emit(
                "rag_retrieval",
                turn_id=turn_id,
                status=rag_result["status"],
                sources=rag_result["sources"],
            )
        self._emit("state", state="llm", turn_id=turn_id)
        if self._pipeline_mode == "streaming":
            self._emit("assistant_response_start", turn_id=turn_id, mode="streaming", input_source=input_source)
        turn_context = self._turn_context
        if turn_context is None:
            return None
        if turn_context.state == TurnState.CREATED:
            turn_context.transition(TurnState.LLM_STREAMING)

        self.mark_stage_end("pre_answer")
        self.mark_stage_start("llm_first_token")
        self.mark_stage_start("llm_first_speech")
        self.mark_stage_start("llm_total")
        self.mark_stage_start("first_fragment")

        kwargs = {
            "stream_to_avatar": self._pipeline_mode == "streaming",
            "defer_history_commit": True,
            "datainfo": {
                "turn_id": turn_id,
                "generation": generation,
                "on_board": partial(self._on_board_event, generation=generation),
            },
        }
        if rag_result and rag_result["status"] == "matched":
            kwargs["rag_context"] = retrieval_prompt(rag_result["sources"])
        if role_plan:
            context = str(role_plan.get("context") or "")
            if role_plan.get("weather") is not None:
                from src.profiles.weather import weather_prompt
                context += "\n" + weather_prompt(role_plan["weather"])
            if context:
                kwargs["rag_context"] = kwargs.get("rag_context", "") + "\n" + context
        # Keep the immutable snapshot on the session/avatar seam so legacy
        # test doubles and TTS metadata do not receive internal rule text.
        try:
            self.avatar._reply_rules_snapshot = self._rules_snapshot
            self.avatar._assistant_profile_snapshot = self._assistant_profile_snapshot
            self.avatar._reply_mode_callback = (
                lambda mode: self._on_mode_event(turn_id, mode, generation))
            self.avatar._incremental_board = True
        except Exception:
            pass
        if self._pipeline_mode == "streaming" or getattr(self.config, "profile_id", ""):
            kwargs.update(
                {
                    "chunk_guard": lambda sequence: self._accept_llm_chunk(
                        turn_context,
                        sequence,
                    ),
                    "defer_history_commit": True,
                }
            )

        report_stage = self._threadsafe_stage_reporter(loop, turn_id, generation)

        def _call_llm():
            with observe_stages(report_stage):
                return llm_response(text, self.avatar, **kwargs)

        future = loop.run_in_executor(None, _call_llm)
        if worker is not None:
            # A held answer may be discarded while its worker still runs; its
            # owner awaits the worker, so cancellation must not orphan it.
            worker.append(future)
            response = await asyncio.shield(future)
        else:
            response = await future
        self.mark_stage_end("llm_total")
        if not self._is_current(turn_id, generation):
            return None
        return str(response).strip()

    def _finish_answer(self, response, turn_id, generation, input_source) -> None:
        if not self._is_current(turn_id, generation):
            return
        self._llm_finished = True
        self._emit("state", state="tts_ready", turn_id=turn_id)
        if not response:
            self._end_silent_turn(turn_id)
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
        self._end_turn_if_nothing_speakable(turn_id)

    def _hold_playback(self, turn_id: str, generation: int) -> None:
        self._held_events = []
        self._playback_blocked_at = None
        self._playback_hold = (turn_id, generation)
        self._playback_released.clear()

    def _playback_held(self) -> bool:
        """Whether the active turn's answer still waits for routing."""
        hold = self._playback_hold
        return hold is not None and hold == (self._turn_id, self._generation)

    def _release_playback(self, turn_id: str, generation: Optional[int]) -> None:
        """Let a held answer play (``generation``) or drop it (``None``)."""
        hold = self._playback_hold
        blocked_at = self._playback_blocked_at
        held, self._held_events = self._held_events, []
        self._playback_hold = None
        self._playback_blocked_at = None
        self._playback_released.set()
        if generation is None or hold != (turn_id, generation):
            return
        if self._metrics is not None:
            waited = 0.0 if blocked_at is None else self._metrics_clock() - blocked_at
            self._metrics.record_stage_duration("routing_hold", max(0.0, waited))
        for event_type, event_turn, payload in held:
            self._emit(event_type, turn_id=event_turn, **payload)

    def _await_playback_release(self, eventpoint: dict) -> None:
        """Block a TTS thread's held answer audio until routing decides."""
        try:
            key = (str(eventpoint["turn_id"]), int(eventpoint["generation"]))
        except (KeyError, TypeError, ValueError):
            return
        if self._playback_hold != key:
            return
        loop = self._event_loop
        try:
            if asyncio.get_running_loop() is loop:
                return  # never block the session loop itself
        except RuntimeError:
            pass
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(
                    self._note_playback_blocked, key, self._metrics_clock())
            except RuntimeError:
                logger.debug("Dropped playback hold timing: session loop closed")
        while (self._playback_hold == key and self._generation == key[1]
               and not self._closed):
            self._playback_released.wait(0.05)

    def _note_playback_blocked(self, key, blocked_at: float) -> None:
        if self._playback_hold == key and self._playback_blocked_at is None:
            self._playback_blocked_at = blocked_at

    def _end_silent_turn(self, turn_id: str) -> None:
        """Finish a turn that will never produce playback audio."""
        self._commit_history("no_audio", turn_id=turn_id)
        self._emit_turn_metrics("no_audio", turn_id=turn_id)
        self._turn_id = None
        self._turn_task = None
        self._refresh_gate()

    def _end_turn_if_nothing_speakable(self, turn_id: str) -> None:
        """A reply whose text was all stripped (or board-only) has no fragment
        whose playback could ever end the turn, so end it now."""
        if self._turn_id != turn_id or self.is_greeting:
            return
        with self._fragment_lock:
            if self._fragment_texts:
                return
        self._end_silent_turn(turn_id)

    def _speak_fixed(self, question, response, turn_id, generation, input_source):
        """Fixed announcements/failures use the real TTS and played-only history."""
        from src.profiles.language import fixed_text
        response = fixed_text(response, self._conversation["locale"])
        self.mark_stage_end("pre_answer")
        if not self.is_greeting:
            prepare_spoken_history(question, self.avatar, turn_id)
        if self._turn_context is not None and self._turn_context.state == TurnState.CREATED:
            self._turn_context.transition(TurnState.LLM_STREAMING)
        if self._pipeline_mode == "streaming":
            self._emit("assistant_response_start", turn_id=turn_id, mode="streaming", input_source=input_source)
            self._emit("assistant_response_delta", turn_id=turn_id, sequence=0, text_delta=response)
        else:
            self._emit("assistant_response", turn_id=turn_id, text=response, mode="legacy", input_source=input_source)
        self.avatar.put_msg_txt(response, {
            "turn_id": turn_id, "generation": generation, "fragment_sequence": 0})
        self._llm_finished = True
        self._turn_task = None
        self._emit("state", state="tts_ready", turn_id=turn_id)
        if self._pipeline_mode == "streaming":
            self._emit("assistant_response_done", turn_id=turn_id, mode="streaming", terminal_reason="completed")
        self._end_turn_if_nothing_speakable(turn_id)

    def on_output_video_frame(self, eventpoint):
        if self._role_coordinator is not None:
            self._role_coordinator.video_committed(self.sessionid, eventpoint)

    def _handle_turn_error(
        self, exc: Exception, turn_id: str, generation: int
    ) -> None:
        if self._role_coordinator is not None:
            self._role_coordinator.cancel(self.sessionid)
        if not self._is_current(turn_id, generation):
            return
        from src.llm.context_usage import ContextCapacityError
        from src.server.attachments import AttachmentError
        if isinstance(exc, AttachmentError):
            if self._turn_context is not None:
                self._turn_context.fail('attachment_error')
            self._history_finalized_turns.add(turn_id)
            self._emit('state', state='error', error=str(exc), turn_id=turn_id)
            self._emit_turn_metrics('attachment_error', turn_id=turn_id)
            self._turn_id = None
            self._turn_task = None
            self._refresh_gate()
            return
        if isinstance(exc, ContextCapacityError):
            self._history_finalized_turns.add(turn_id)
            self._emit('state', state='error', error='context_capacity', turn_id=turn_id)
            self._turn_id = None
            self._turn_task = None
            self._refresh_gate()
            return
        if self._turn_context is not None:
            self._turn_context.fail("pipeline_error")
        if self._counts_toward_circuit():
            if self._circuit_breaker.record_pipeline_error():
                logger.warning(
                    "reply streaming circuit opened session=%s reason=pipeline_error",
                    self.sessionid,
                )
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
                if self.is_greeting:
                    self._greeting_started = True
                    self.greetings.report("playing")
                self._close_gate()
                self._emit("speaking_start", turn_id=self._turn_id)
                self._emit("state", state="avatar_speaking", turn_id=self._turn_id)
            return
        if self._metrics is not None:
            self._metrics.mark_output_stopped()
        if not self._output_active and self._playback_held():
            # Silence while routing decides is the hold, not a stalled TTS.
            self._silent_output_frames = 0
            self._tts_pending_silent_frames = 0
            return
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
        self.mark_stage_start("tts_pcm_available")
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
        if loop is None or not loop.is_running():
            # Handling inline would touch loop-bound state (the data channel)
            # from the TTS thread; without a loop there is nobody to notify.
            logger.warning(
                "TTS fragment failure dropped without event loop turn=%s reason=%s",
                failed_event.get("turn_id"),
                reason,
            )
            return
        try:
            loop.call_soon_threadsafe(
                self._handle_fragment_synthesis_failure,
                failed_event,
                str(reason),
            )
        except RuntimeError:
            logger.warning("TTS fragment failure dropped: event loop closed")

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

    def fragment_playback_ended(self, eventpoint: dict) -> bool:
        if not self.accepts_media(eventpoint, "fragment_playback_end"):
            return True
        try:
            sequence = int(eventpoint["fragment_sequence"])
        except (KeyError, TypeError, ValueError):
            return True
        with self._fragment_lock:
            return sequence in self._ended_fragment_sequences

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
            if self.is_greeting:
                self.greetings.previous = self._greeting_text
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
            from src.llm.text_normalizer import join_spoken_fragments
            return join_spoken_fragments(self._played_fragments)

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
        if self._role_coordinator is not None:
            self._role_coordinator.cancel(self.sessionid)
        reason = (
            f"{reason_prefix}_after_commit"
            if self.played_assistant_text
            else f"{reason_prefix}_before_commit"
        )
        if self._turn_context is not None and not self._turn_context.terminal:
            self._turn_context.fail(reason)
        if self._counts_toward_circuit():
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
        if self._turn_origin == "greeting":
            self._turn_origin = "visitor"
            self._restore_greeting_voice()
            self.greetings.finished(error="招呼語音播放失敗，已略過本次")
        self._refresh_gate()

    def _counts_toward_circuit(self) -> bool:
        """Only visitor streaming turns judge the streaming pipeline; greetings
        always stream regardless of the breaker, so they never count."""
        return self._pipeline_mode == "streaming" and self._turn_origin != "greeting"

    async def _finish_tail_guard(self) -> None:
        completed_turn = self._turn_id
        was_greeting = self.is_greeting
        self._emit("state", state="tail_guard", turn_id=self._turn_id)
        self._commit_history("completed")
        self._emit_turn_metrics("completed")
        if self._counts_toward_circuit():
            self._circuit_breaker.record_turn_success()
        await asyncio.sleep(0.3)
        self._turn_id = None
        if was_greeting:
            self._restore_greeting_voice()
            self._turn_origin = "visitor"
            self.greetings.finished()
        elif self._role_coordinator is not None:
            await self._role_coordinator.after_playback(self, completed_turn)
        self._refresh_gate()

    async def interrupt(self) -> None:
        """Cancel the old turn, flush all queued speech, then reopen after a tail guard."""
        async with self._turn_lock:
            await self._interrupt_locked()

    async def _interrupt_locked(self) -> None:
        """Interrupt body; the caller must hold ``_turn_lock``."""
        self.greetings.reset()
        interrupted_turn_id = self._turn_id
        if self._role_coordinator is not None:
            self._role_coordinator.cancel(self.sessionid)
        if self._metrics is not None:
            self._metrics.mark_interrupt()
        if self._turn_context is not None:
            self._turn_context.cancel("interrupt")
        self._commit_history("interrupt")
        self._generation += 1
        generation = self._generation
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
        if self._generation != generation:
            # Another fence (failure, greeting, handoff, close) owns the
            # session now; reopening here would clobber its turn.
            if interrupted_turn_id:
                self._emit_turn_metrics("interrupt", turn_id=interrupted_turn_id)
            return
        self._turn_id = None
        self._restore_greeting_voice()
        self._manual_pause = False
        self._capture_requested = True
        self._refresh_gate()
        self._emit_turn_metrics("interrupt", turn_id=interrupted_turn_id)

    async def close(self) -> None:
        if self._role_reset_task is not None:
            self._role_reset_task.cancel()
            await asyncio.gather(self._role_reset_task, return_exceptions=True)
            self._role_reset_task = None
        if self._role_coordinator is not None:
            self._role_coordinator.cancel(self.sessionid)
        self.greetings.close()
        self._cancel_idle_reset()
        self._commit_history("disconnect")
        self._emit_turn_metrics("disconnect")
        self._closed = True
        self.attachments.close()
        if self._turn_context is not None:
            self._turn_context.cancel("disconnect")
        self._generation += 1
        self._close_gate()
        for task in (
            self._track_task,
            self._turn_task,
            self._tail_task,
            self._finalize_task,
            *self._background_tasks,
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
        """Validate one turn-aware media item at a cross-thread boundary.

        At ``avatar_audio_enqueue`` a held answer's TTS thread first waits
        for the routing decision, so its audio is synthesized but not sent.
        """
        if stage == "avatar_audio_enqueue" and isinstance(eventpoint, dict):
            self._await_playback_release(eventpoint)
        if isinstance(eventpoint, dict) and "avatar_epoch" in eventpoint:
            if self._closed or eventpoint["avatar_epoch"] != getattr(self.avatar, "_asset_epoch", 0):
                return False
            if not eventpoint.get("turn_id"):
                return True
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
        metric_payload = {
            "turn_id": target_turn,
            "terminal_reason": terminal_reason,
            "pipeline_mode": self._pipeline_mode,
            "metrics": snapshot,
        }
        if callable(self._test_result_sink):
            try:
                self._test_result_sink(
                    {
                        **metric_payload,
                        "assistant_response": self.played_assistant_text,
                    }
                )
            except Exception:
                logger.exception("Persisting voice test result failed")
        self._emit(
            "turn_metrics",
            **metric_payload,
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

    def _threadsafe_stage_reporter(self, loop, turn_id: str, generation: int):
        """Deliver a worker-thread stage duration to this turn on its loop."""
        def deliver(stage: str, seconds: float) -> None:
            if self._metrics is not None and self._is_current(turn_id, generation):
                self._metrics.record_stage_duration(stage, seconds)

        def report(stage: str, seconds: float) -> None:
            try:
                loop.call_soon_threadsafe(deliver, stage, seconds)
            except RuntimeError:
                logger.debug("Dropped %s timing: session loop closed", stage)

        return report

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
                self._emit_if_current,
                int(generation),
                "assistant_response_delta",
                turn_id=turn_id,
                sequence=sequence,
                text_delta=text,
            )
        )

    def _emit_if_current(self, generation: int, event_type: str, *, turn_id: str,
                         **payload) -> None:
        """Loop-side delivery of worker output; a fence may have run since."""
        if self._is_current(turn_id, generation):
            self._emit(event_type, turn_id=turn_id, **payload)

    def _start_turn_context(self, turn_id: str, *, origin="visitor") -> None:
        self._turn_origin = origin
        if origin == "visitor":
            self.cancel_greeting_trial()
            self._conversation_dirty = True
            self._cancel_idle_reset()
        if (
            self._turn_context is None
            or self._turn_context.turn_id != turn_id
            or self._turn_context.generation != self._generation
        ):
            self._turn_context = TurnContext(
                turn_id=turn_id,
                generation=self._generation,
            )
            self._client_request_id = None
            # Capture once at turn acceptance. A later control-panel save only
            # affects the next conversation, preserving the current scene.
            published = self.config
            if not getattr(self.config, 'conversation_snapshot', False):
                from src.server.state import state
                published = state.config or self.config
            self._rules_snapshot = snapshot_from_config(published)
            self._assistant_profile_snapshot = deepcopy(
                getattr(getattr(published, 'llm', None), 'assistant_profile', None)
            )
            self._rag_snapshot = getattr(self.config, "profile_rag", None) or avatar_settings(
                str(getattr(getattr(self.config, "model", None), "avatar_id", "") or "")
            )
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
        if self.is_greeting:
            if played_text:
                remember_greeting(self.sessionid, played_text, profile_id=getattr(self.config, "profile_id", ""))
            return bool(played_text)
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

    @property
    def is_greeting(self) -> bool:
        return self._turn_origin == "greeting" and self._turn_id is not None

    def greeting_conditions(self):
        roles = self._role_coordinator
        active = (self._presenter == "stage" and not self._closed
                  and self._stage_ready and self._event_sink is not None
                  and self.config.stage.idle_greeting_enabled
                  and not self._manual_pause and not self._prepare_error and not self._preparing
                  and (roles is None or roles.current_id == roles.library["pair"]["main"]))
        idle = (self._is_conversation_idle()
                and (roles is None or roles.all_idle())
                and (roles is None or roles.phase in {"ready", "disabled"}))
        from src.llm.service import _session_llm_instances
        records = any((key == self.sessionid or isinstance(key, tuple) and key[0] == self.sessionid)
                      and (bool(getattr(llm, 'conversation_history', [])) or llm.get_last_board() is not None)
                      for key, llm in list(_session_llm_instances.items()))
        clear = (not self._conversation_dirty and not self._greeting_returning
                 and not records and not self.attachments.snapshot()['files']
                 and not self._composer_has_draft)
        return bool(active), bool(idle), bool(clear)

    def start_greeting(self, text: str, *, playback_config=None) -> str:
        """Queue fenced TTS without manufacturing a visitor history turn."""
        if not sanitize_speech_text(text):
            raise GreetingError("招呼文案沒有可朗讀文字，請補上招呼內容")
        if not self._is_conversation_idle():
            raise RuntimeError("目前有其他對話，請等待播放結束")
        if playback_config is not None and getattr(self.avatar, "tts", None) is not None:
            self._greeting_tts_config = self.avatar.tts.config
            self.avatar.tts.config = playback_config
        self._greeting_text = text
        self._turn_id = uuid4().hex
        self._greeting_started = False
        self._start_turn_context(self._turn_id, origin="greeting")
        # Always use played-only subtitles, independent of visitor reply mode.
        self._pipeline_mode = "streaming"
        try:
            self._speak_fixed("", text, self._turn_id, self._generation, "greeting")
        except Exception:
            self.cancel_greeting(stop_playing=True)
            raise
        return self._turn_id

    def cancel_greeting_trial(self):
        task = self._greeting_trial_preparation
        if task is not None:
            task.cancel()
            self._greeting_trial_preparation = None

    def _restore_greeting_voice(self):
        if self._greeting_tts_config is not None:
            self.avatar.tts.config = self._greeting_tts_config
            self._greeting_tts_config = None

    def cancel_greeting(self, *, stop_playing=False) -> None:
        if not self.is_greeting or self._greeting_started and not stop_playing:
            return
        turn_id = self._turn_id
        self._commit_history("cancelled")
        if self._turn_context is not None:
            self._turn_context.cancel("greeting_cancelled")
        self._generation += 1
        if self._tail_task:
            self._tail_task.cancel()
            self._tail_task = None
        self.avatar.flush_talk()
        if self._media_player is not None:
            self._media_player.discard_stale_media()
        self._turn_id = None
        self._turn_origin = "visitor"
        self._output_active = False
        self._restore_greeting_voice()
        self._emit("turn_cancelled", turn_id=turn_id, reason="greeting_cancelled")
        self._refresh_gate(refresh_greetings=False)

    def _is_conversation_idle(self) -> bool:
        return (
            not self._closed
            and not self._settings_switching
            and self._turn_id is None
            and self._turn_task is None
            and self._finalize_task is None
            and not self._output_active
            and not self._attachment_busy
        )

    def _idle_reset_delay(self) -> float:
        stage = getattr(self.config, "stage", None)
        try:
            return float(getattr(stage, "idle_reset_seconds", 10))
        except (TypeError, ValueError):
            return 10.0

    def _full_reset_delay(self) -> float:
        return self._idle_reset_delay()

    def _cancel_idle_reset(self) -> None:
        task = self._idle_reset_task
        self._idle_reset_task = None
        if task is not None and not task.done():
            task.cancel()

    def _schedule_idle_reset(self) -> None:
        """Count down independently for each idle console or stage conversation.

        The countdown starts when no turn is running and restarts after any
        new interaction or turn ends.
        """
        if self._role_coordinator is not None and not self._role_coordinator.input_allowed(self):
            self._cancel_idle_reset()
            return
        if (
            not self._conversation_dirty
            or not self._is_conversation_idle()
        ):
            return
        delay = self._idle_reset_delay()
        if delay <= 0:
            return
        task = self._idle_reset_task
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._idle_reset_task = loop.create_task(self._reset_after_idle(delay))

    def note_interaction(self) -> None:
        """Restart visitor deadlines; actual input also invalidates greeting preparation."""
        self.greetings.reset(stop_playing=True)
        self._conversation_dirty = True
        self._cancel_idle_reset()
        self._schedule_idle_reset()

    async def _reset_after_idle(self, delay: float) -> None:
        try:
            full_delay = self._full_reset_delay()
            short_delay = min(float(getattr(self.config.stage, "clear_display_seconds", 15)), full_delay)
            await asyncio.sleep(short_delay)
            if self._conversation_dirty and self._is_conversation_idle():
                self._emit('board_clear')
                self._emit('answer_clear')
            await asyncio.sleep(max(0.0, full_delay - short_delay))
        except asyncio.CancelledError:
            return
        self._idle_reset_task = None
        if self._role_coordinator is not None and not self._role_coordinator.input_allowed(self):
            return
        if not self._conversation_dirty or not self._is_conversation_idle():
            return
        self.reset_conversation()

    def reset_conversation(self, *, return_to_main=True) -> None:
        """Forget this source's visitor content, preserving locale and capture preferences."""
        clear_session_history(self.sessionid)
        self.attachments.clear()
        self._composer_editing = False
        self._composer_has_draft = False
        self._board_display_receipts.clear()
        self._conversation_dirty = False
        self.greetings.reset()
        self._emit("board_clear")
        self._emit("answer_clear")
        self._emit("conversation_reset")
        if self._role_coordinator is not None:
            self._role_coordinator.confirmed.pop(self.sessionid, None)
            if return_to_main:
                self._role_coordinator.visitor_reset(self)
        self.greetings.refresh()
        logger.info("Visitor conversation reset session=%s", self.sessionid)

    def _close_gate(self) -> None:
        self._cancel_idle_reset()
        self._gate_open = False
        self._segmenter_reset_pending = True

    def _refresh_gate(self, *, refresh_greetings=True) -> None:
        if (self._pending_history_limit is not None and self._turn_id is None
                and self._turn_task is None and not self._output_active):
            from src.llm.service import set_session_history_limit
            limit = self._pending_history_limit
            self._pending_history_limit = None
            self._conversation['history_max_messages'] = limit
            set_session_history_limit(self.sessionid, limit)
            from src.server.conversations import configure_avatar
            configure_avatar(self.avatar, self._conversation)
        was_open = self._gate_open
        allowed = (
            not self._closed
            and not self._settings_switching
            and (self._role_coordinator is None or self._role_coordinator.input_allowed(self))
            and bool(getattr(self.config.vad, "enabled", True))
            and not self._preparing
            and not self._prepare_error
            and self._event_sink is not None
            and self._capture_requested
            and not self._manual_pause
            and not self._composer_editing
            and not self._greeting_returning
            and not self._output_active
            and self._turn_task is None
            and self._finalize_task is None
            and (self._turn_id is None or self.is_greeting and not self._greeting_started)
        )
        self._gate_open = allowed
        if allowed and not was_open:
            self._segmenter_reset_pending = True
        if allowed and self._metrics is not None:
            self._metrics.mark_listening_resumed()
        self._emit("state", state="listening" if allowed else "paused")
        self._schedule_idle_reset()
        if refresh_greetings:
            self.greetings.refresh()

    def _on_board_event(self, payload: dict, generation: Optional[int] = None) -> None:
        if not isinstance(payload, dict):
            return
        payload_turn = payload.get("turn_id") or self._turn_id
        if generation is None:
            generation = self._generation
        if not payload_turn or not self._is_current(str(payload_turn), generation):
            return
        loop = self._event_loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._dispatch_board_event_if_current,
                                      str(payload_turn), generation, payload)
        else:
            self._dispatch_board_event(payload)

    def _dispatch_board_event_if_current(self, turn_id: str, generation: int,
                                         payload: dict) -> None:
        if self._is_current(turn_id, generation):
            self._dispatch_board_event(payload)

    def _on_mode_event(self, turn_id: str, mode, generation: Optional[int] = None) -> None:
        """Forward parser-confirmed mode from the worker thread safely."""
        if generation is None:
            generation = self._generation
        if not self._is_current(str(turn_id), generation):
            return
        value = getattr(mode, "value", str(mode))
        loop = self._event_loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(
                partial(
                    self._emit_if_current,
                    generation,
                    "assistant_response_mode",
                    turn_id=str(turn_id),
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
        if event_type in _HELD_EVENT_TYPES and self._playback_held():
            # Routing may still discard this answer; clients see it on release.
            self._held_events.append((event_type, turn_id, payload))
            return
        event = {
            "type": event_type,
            "turn_id": turn_id if turn_id is not None else self._turn_id,
            **payload,
        }
        if getattr(self.config, "profile_id", ""):
            event["profile_id"] = self.config.profile_id
        if self._presentation is not None:
            self._presentation.publish(self, event)
        else:
            self._send_event(event)

    def _send_event(self, event):
        if self._event_sink is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        loop = self._event_loop
        if loop is not None and running is not loop and loop.is_running():
            # The data channel is bound to the session loop; never send on it
            # from a TTS/LLM worker thread (or a worker's private loop).
            try:
                loop.call_soon_threadsafe(self._send_event, event)
            except RuntimeError:
                logger.warning("Voice event dropped: event loop closed")
            return
        self._sequence += 1
        try:
            self._event_sink(json.dumps({**event, "seq": self._sequence}, ensure_ascii=False))
        except Exception as exc:
            if running is None or (loop is not None and running is not loop):
                # A failure off the session loop says nothing about the
                # channel itself; keep it open for later loop-side events.
                logger.warning(f"Voice event dropped outside the event loop: {exc}")
                return
            logger.warning(f"Voice event channel failed closed: {exc}")
            self._event_sink = None
            self._close_gate()
