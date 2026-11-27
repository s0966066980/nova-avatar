# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Stage names and a context-local timer shared by every processing layer.

The processing layers measure their own stages with ``timed_stage``; the core
decides who observes them (``observe_stages``) and keeps the per-turn record.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, Optional

Clock = Callable[[], float]
StageObserver = Callable[[str, float], None]

# Stage durations are measured where the work runs; durations, not clocks,
# cross threads. ``pre_answer`` runs from the transcript to the main answer
# (or fixed reply) that is played and contains ``retrieval``. ``routing`` runs
# concurrently with it; ``routing_hold`` is how long synthesized answer audio
# waited for the routing decision, inside ``avatar_to_webrtc_commit``.
# ``model_info`` is the llama-server preflight inside ``llm_first_token``.
#
# Before the speech end (not part of ``first_audio_seconds``):
# ``vad_endpoint`` is the silence wait on the audio timeline (the configured
# ``min_silence_ms`` rounded up to whole VAD frames, not a wall-clock reading);
# ``vad_speech_tail`` is how long the VAD still judged speech after the voice
# fell below -40 dBFS; ``vad_processing`` runs from the arrival of the uplink
# frame that completed the endpoint to the endpoint decision.
# After the first audio: ``webrtc_audible_onset`` runs from the first nonzero
# reply frame sent to the first one whose peak exceeds ``AUDIBLE_PEAK``.
STAGE_NAMES = (
    "vad_endpoint",
    "vad_speech_tail",
    "vad_processing",
    "asr",
    "pre_answer",
    "routing",
    "retrieval",
    "web_search_plan",
    "web_search",
    "web_synthesis",
    "routing_hold",
    "model_info",
    "llm_first_token",
    "llm_first_speech",
    "llm_total",
    "first_fragment",
    "tts_first_encoded",
    "tts_pcm_available",
    "tts_first_pcm",
    "musetalk_first_batch",
    "musetalk_inference_first_result",
    "avatar_pasteback_done",
    "webrtc_audio_enqueue",
    "webrtc_video_enqueue",
    "avatar_to_webrtc_commit",
    "webrtc_audio_commit",
    "webrtc_audible_onset",
)

_stage_observer: ContextVar[Optional[StageObserver]] = ContextVar(
    "turn_stage_observer", default=None,
)


@contextmanager
def observe_stages(observer: StageObserver) -> Iterator[None]:
    """Route ``timed_stage`` durations in this context to ``observer``."""
    token = _stage_observer.set(observer)
    try:
        yield
    finally:
        _stage_observer.reset(token)


@contextmanager
def timed_stage(stage: str, *, clock: Clock = time.monotonic) -> Iterator[None]:
    """Time a block for the current turn, if one is observing this context."""
    validate_stage(stage)
    observer = _stage_observer.get()
    started = clock()
    try:
        yield
    finally:
        if observer is not None:
            observer(stage, max(0.0, clock() - started))


def validate_stage(stage: str) -> None:
    """Reject a stage name outside the fixed, privacy-safe set."""
    if stage not in STAGE_NAMES:
        raise ValueError(f"unsupported latency stage: {stage}")
