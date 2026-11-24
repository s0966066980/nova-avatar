# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The stage-connection and free-VRAM checks that keep GPU work from hurting the stage.

One implementation, shared by everything that wants the GPU while a stage may be running:
the training job's pre-flight (``src.server.tts_training_jobs``) uses these two functions,
and the automatic transcription of uploaded recordings (ticket 12) is to call the same
ones instead of copying them. A ``Check`` says ``pass`` or ``fail`` with a reason the
console shows; ``detail`` carries the numbers.

Unknown free memory is a failure: the caller must then treat the GPU as unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.tts.training.gpu_probe import VramReading

CHECK_STAGE = "stage_connections"
CHECK_VRAM = "free_vram"
PASS, FAIL, WARN = "pass", "fail", "warn"
DEFAULT_MIN_FREE_VRAM_GB = 8.0


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    status: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "status": self.status, "reason": self.reason, "detail": self.detail}


def count_stage_connections() -> int:
    """Every stage session, including one still connecting (its placeholder is ``None``)."""
    from src.server.state import state

    return len(state.avatar_streams)


def stage_connection_check(count: int) -> Check:
    if count:
        return Check(CHECK_STAGE, "舞台連線", FAIL, f"有 {count} 個舞台正在連線，請先關閉再重新檢查", {"count": count})
    return Check(CHECK_STAGE, "舞台連線", PASS, "目前沒有舞台連線", {"count": 0})


def free_vram_check(reading: VramReading, threshold_gb: float) -> Check:
    detail: dict[str, Any] = {"free_gb": None, "threshold_gb": threshold_gb}
    if reading.free_gb is None:
        return Check(
            CHECK_VRAM, "剩餘顯存", FAIL,
            f"讀不到剩餘顯存（{reading.reason}），為避免訓練把舞台的 GPU 用光，先不開始", detail,
        )
    detail["free_gb"] = round(reading.free_gb, 2)
    if reading.free_gb < threshold_gb:
        return Check(CHECK_VRAM, "剩餘顯存", FAIL, f"剩餘 {reading.free_gb:.1f} GB，低於門檻 {threshold_gb:g} GB", detail)
    return Check(CHECK_VRAM, "剩餘顯存", PASS, f"剩餘 {reading.free_gb:.1f} GB，高於門檻 {threshold_gb:g} GB", detail)
