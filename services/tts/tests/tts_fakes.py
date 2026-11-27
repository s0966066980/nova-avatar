# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""TTS services for core tests."""
from __future__ import annotations

from nova_contracts.tts import TtsEngineSettings


def in_process_tts():
    """The real in-process TTS service; tests patch the layer's internals under it.

    For core tests whose behaviour (voice checks, BreezyVoice start, previews)
    now happens behind ``TtsService``.
    """
    from nova_tts.adapter import InProcessTtsService

    return InProcessTtsService(TtsEngineSettings())
