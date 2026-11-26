# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's stage-connection check: GPU work never starts while a stage is connected.

The free-VRAM half of the guard belongs to the TTS layer (``test_training_gpu``); the
stage half reads the core's session registry and is decided first.
"""

from __future__ import annotations

from src.server.stage_guard import count_stage_connections, stage_connection_check, transcription_device
from src.tts.training.gpu_guard import DeviceChoice


def test_stage_connections_are_counted_from_the_session_registry(monkeypatch):
    from src.server.state import state

    monkeypatch.setattr(state, "avatar_streams", {1: object(), 2: None})  # 2 is still connecting
    assert count_stage_connections() == 2


def test_stage_connection_check_names_the_count():
    assert stage_connection_check(0).status == "pass"
    blocked = stage_connection_check(3)
    assert (blocked.id, blocked.label) == ("stage_connections", "舞台連線")
    assert (blocked.status, blocked.detail) == ("fail", {"count": 3})
    assert blocked.reason == "有 3 個舞台正在連線，請先關閉再重新檢查"


class GpuChoice:
    """The TTS layer's free-VRAM decision, recording whether it was asked."""

    def __init__(self, choice: DeviceChoice):
        self.choice, self.asked = choice, 0

    def __call__(self) -> DeviceChoice:
        self.asked += 1
        return self.choice


def test_a_connected_stage_means_cpu_and_the_gpu_is_not_probed():
    gpu = GpuChoice(DeviceChoice("cuda"))
    assert transcription_device(lambda: 1, gpu) == DeviceChoice("cpu", "有舞台連線")
    assert gpu.asked == 0


def test_the_stage_reason_wins_over_too_little_vram():
    assert transcription_device(lambda: 2, GpuChoice(DeviceChoice("cpu", "剩餘顯存不足"))) == DeviceChoice(
        "cpu", "有舞台連線"
    )


def test_an_idle_stage_leaves_the_device_to_the_tts_layer():
    assert transcription_device(lambda: 0, GpuChoice(DeviceChoice("cuda"))) == DeviceChoice("cuda")
    assert transcription_device(lambda: 0, GpuChoice(DeviceChoice("cpu", "剩餘顯存不足"))) == DeviceChoice(
        "cpu", "剩餘顯存不足"
    )
