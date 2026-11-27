# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The free-VRAM check that keeps GPU work from hurting the stage.

The TTS layer's half of the GPU guard. Whether a stage is connected is core state, so the
core checks that first (``src.server.stage_guard``) and asks this module only about free
memory: the training job's pre-flight uses ``free_vram_check``, and the automatic
transcription of uploaded recordings asks ``choose_transcription_device``, which calls the
same check instead of copying it. A ``Check`` says ``pass`` or ``fail`` with a reason the
console shows; ``detail`` carries the numbers.

Unknown free memory is a failure: the caller must then treat the GPU as unavailable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.tts.training.gpu_probe import VramReading, read_free_vram

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
# its longer sentences from the check above.
REASON_LOW_VRAM = "剩餘顯存不足"
REASON_VRAM_UNKNOWN = "無法查詢顯存"
REASON_NO_CUDA = "沒有可用的 CUDA 裝置"


@dataclass(frozen=True)
class DeviceChoice:
    """The device a GPU job runs on and, for the CPU, why it is not the GPU."""

    device: str
    fallback_reason: str | None = None


def choose_transcription_device(
    read_vram: Callable[[], VramReading] = read_free_vram,
    threshold_gb: float = DEFAULT_MIN_FREE_VRAM_GB,
    cuda_available: Callable[[], bool] = lambda: True,
) -> DeviceChoice:
    """CPU (int8) with a reason when the VRAM budget forbids the GPU, else CUDA.

    Blocking (``nvidia-smi``): call it from a worker thread, after the core has ruled out a
    connected stage. Unknown free memory counts as too little. The GPU is never a refusal,
    only a fallback, and the caller decides once per job.
    """
    vram = free_vram_check(read_vram(), threshold_gb)
    if vram.status == FAIL:
        unknown = vram.detail["free_gb"] is None
        return DeviceChoice(DEVICE_CPU, REASON_VRAM_UNKNOWN if unknown else REASON_LOW_VRAM)
    if not cuda_available():
        return DeviceChoice(DEVICE_CPU, REASON_NO_CUDA)
    return DeviceChoice(DEVICE_CUDA)
