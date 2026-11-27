# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The stage-connection and free-VRAM checks that keep GPU work from hurting the stage.

One implementation, shared by everything that wants the GPU while a stage may be running:
the training job's pre-flight (``nova_core.server.tts_training_jobs``) uses these two functions,
and the automatic transcription of uploaded recordings asks ``choose_transcription_device``,
which calls the same two instead of copying them. The core counts the stage connections and
passes that count (or a counter) in; this layer only reads the free VRAM. A ``Check`` says ``pass`` or ``fail`` with a reason the
console shows; ``detail`` carries the numbers.

Unknown free memory is a failure: the caller must then treat the GPU as unavailable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nova_tts.training.gpu_probe import VramReading, read_free_vram

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


DEVICE_CUDA, DEVICE_CPU = "cuda", "cpu"

# What the console shows when transcription runs on the CPU; the training pre-flight keeps
# its longer sentences from the checks above.
REASON_STAGE = "有舞台連線"
REASON_LOW_VRAM = "剩餘顯存不足"
REASON_VRAM_UNKNOWN = "無法查詢顯存"
REASON_NO_CUDA = "沒有可用的 CUDA 裝置"


@dataclass(frozen=True)
class DeviceChoice:
    """The device a GPU job runs on and, for the CPU, why it is not the GPU."""

    device: str
    fallback_reason: str | None = None


def choose_transcription_device(
    stage_connections: Callable[[], int],
    read_vram: Callable[[], VramReading] = read_free_vram,
    threshold_gb: float = DEFAULT_MIN_FREE_VRAM_GB,
    cuda_available: Callable[[], bool] = lambda: True,
) -> DeviceChoice:
    """CPU (int8) with a reason when the stage or the VRAM budget forbids the GPU, else CUDA.

    Blocking (``nvidia-smi``): call it from a worker thread. A connected stage is decided
    before the VRAM is read; unknown free memory counts as too little. The GPU is never a
    refusal, only a fallback, and the caller decides once per job.
    """
    if stage_connection_check(stage_connections()).status == FAIL:
        return DeviceChoice(DEVICE_CPU, REASON_STAGE)
    vram = free_vram_check(read_vram(), threshold_gb)
    if vram.status == FAIL:
        unknown = vram.detail["free_gb"] is None
        return DeviceChoice(DEVICE_CPU, REASON_VRAM_UNKNOWN if unknown else REASON_LOW_VRAM)
    if not cuda_available():
        return DeviceChoice(DEVICE_CPU, REASON_NO_CUDA)
    return DeviceChoice(DEVICE_CUDA)
