# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's half of the GPU guard: no GPU work starts while a stage is connected.

Stage connections are core state, so the core decides this before it asks the TTS layer,
which only judges free VRAM (``src.tts.training.gpu_guard``). The training pre-flight
(``src.server.tts_training_jobs``) lists ``stage_connection_check`` next to the TTS
layer's ``free_vram_check``; a transcription job asks ``transcription_device``.
"""

from __future__ import annotations

from collections.abc import Callable

from src.tts.training.gpu_guard import DEVICE_CPU, FAIL, PASS, Check, DeviceChoice

CHECK_STAGE = "stage_connections"

# What the console shows when transcription falls back to the CPU because of the stage.
REASON_STAGE = "有舞台連線"


def count_stage_connections() -> int:
    """Every stage session, including one still connecting (its placeholder is ``None``)."""
    from src.server.state import state

    return len(state.avatar_streams)


def stage_connection_check(count: int) -> Check:
    if count:
        return Check(CHECK_STAGE, "舞台連線", FAIL, f"有 {count} 個舞台正在連線，請先關閉再重新檢查", {"count": count})
    return Check(CHECK_STAGE, "舞台連線", PASS, "目前沒有舞台連線", {"count": 0})


def transcription_device(sessions: Callable[[], int], gpu_choice: Callable[[], DeviceChoice]) -> DeviceChoice:
    """CPU with the stage reason while a stage is connected, else the TTS layer's choice.

    The stage is decided first, so a connected stage never runs ``nvidia-smi``.
    """
    if stage_connection_check(sessions()).status == FAIL:
        return DeviceChoice(DEVICE_CPU, REASON_STAGE)
    return gpu_choice()
