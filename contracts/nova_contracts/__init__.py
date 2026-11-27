# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The single source of cross-layer contracts (ADR 0028)."""
from nova_contracts.avatar import AvatarRenderer, SpeechFactory, SpeechSource
from nova_contracts.llm import (
    BoardEvent,
    GreetingRequest,
    GreetingResult,
    HandoffDecision,
    HandoffMember,
    HandoffRequest,
    LlmEvent,
    LlmService,
    ReplyDone,
    ReplyModeEvent,
    ReplyRequest,
    RetrievalSourcesEvent,
    SpokenTextDelta,
    WeatherSite,
    WebSourcesEvent,
)
from nova_contracts.stt import SttService, TranscribeResult
from nova_contracts.tts import AudioSink, SynthesizeRequest, TtsService
from nova_contracts.turn import PlayableFragment, TurnEnvelope
from nova_contracts.version import CONTRACT_VERSION

__all__ = [
    "AudioSink", "AvatarRenderer", "BoardEvent", "CONTRACT_VERSION", "GreetingRequest",
    "GreetingResult", "HandoffDecision", "HandoffMember", "HandoffRequest", "LlmEvent",
    "LlmService", "PlayableFragment", "ReplyDone", "ReplyModeEvent", "ReplyRequest",
    "RetrievalSourcesEvent", "SpeechFactory", "SpeechSource", "SpokenTextDelta",
    "SttService", "SynthesizeRequest", "TranscribeResult", "TtsService", "TurnEnvelope",
    "WeatherSite", "WebSourcesEvent",
]
