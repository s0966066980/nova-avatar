# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's half of the GPU guard: the stage and voice training never share the GPU.

Stage connections and the administrator login are core state, so the core checks them
itself and asks the TTS layer only about everything else, free VRAM included (spec
decision 14). The training pre-flight the console sees is the core's two checks
(``admin_check``, ``stage_connection_check``) in front of the TTS layer's
(``with_core_checks``); a transcription job runs on the CPU while a stage is connected
(``transcription_cpu_reason``). The other way round, ``POST /offer`` asks
``stage_offer_refusal`` so that no new stage connects while a training job runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from nova_contracts.tts import TrainingCheck, TrainingPreflight

if TYPE_CHECKING:
    from nova_contracts.tts import TtsService

CHECK_ADMIN = "admin"
CHECK_STAGE = "stage_connections"

# What the console shows when transcription falls back to the CPU because of the stage.
REASON_STAGE = "有舞台連線"

# The stable reason a stage offer is refused while a voice-training job runs; the stage
# page keys on it to show the pause and keep retrying.
VOICE_TRAINING_ACTIVE = "voice_training_active"
VOICE_TRAINING_MESSAGE = "聲線訓練進行中，數位人暫停服務"


def count_stage_connections() -> int:
    """Every stage session, including one still connecting (its placeholder is ``None``)."""
    from nova_core.server.state import state

    return len(state.avatar_streams)


def admin_check() -> TrainingCheck:
    """Every training route is ADMIN (ADR 0021): reaching it means the login passed."""
    return TrainingCheck(id=CHECK_ADMIN, label="管理者登入", status="pass", reason="以管理者身分操作")


def stage_connection_check(count: int) -> TrainingCheck:
    if count:
        return TrainingCheck(
            id=CHECK_STAGE, label="舞台連線", status="fail",
            reason=f"有 {count} 個舞台正在連線，請先關閉再重新檢查", detail={"count": count},
        )
    return TrainingCheck(id=CHECK_STAGE, label="舞台連線", status="pass", reason="目前沒有舞台連線",
                         detail={"count": 0})


def with_core_checks(layer: TrainingPreflight, stage: TrainingCheck) -> TrainingPreflight:
    """The full pre-flight: the core's checks first, then the TTS layer's."""
    checks = (admin_check(), stage, *layer.checks)
    return TrainingPreflight(can_start=not any(check.status == "fail" for check in checks), checks=checks)


def refusal_message(preflight: TrainingPreflight) -> str:
    """The sentence a refused start answers with, naming every failed check."""
    reasons = "；".join(f"{check.label}：{check.reason}" for check in preflight.checks if check.status == "fail")
    return f"目前不能開始訓練：{reasons}"


def transcription_cpu_reason(count: int) -> str | None:
    """Why a new transcription job must use the CPU, decided before the TTS layer is asked.

    A connected stage means the CPU, so the TTS layer never runs ``nvidia-smi`` for it.
    """
    return REASON_STAGE if count else None


def stage_offer_refusal(role: str, tts: TtsService | None) -> web.Response | None:
    """409 ``voice_training_active`` for a stage offer while a training job runs, else ``None``.

    Console offers are never refused here, and a stage that is already connected is left
    alone: training cannot start while one is (``stage_connection_check``).
    """
    if role != "stage" or tts is None or not tts.training_activity().active:
        return None
    return web.json_response(
        {"code": -1, "reason": VOICE_TRAINING_ACTIVE, "msg": VOICE_TRAINING_MESSAGE}, status=409
    )
