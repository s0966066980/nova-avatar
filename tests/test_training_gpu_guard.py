# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Which device automatic transcription may use: the GPU guard's decision, with fake probes."""

from __future__ import annotations

from src.tts.training.gpu_guard import (
    DeviceChoice,
    choose_transcription_device,
)
from src.tts.training.gpu_probe import VramReading


class Probes:
    """Fake stage-connection count, VRAM probe and CUDA availability that record being asked."""

    def __init__(self, *, stage: int = 0, free_mib: int | None = 24 * 1024, reason: str = "", cuda: bool = True):
        self.stage, self.reading, self.cuda = stage, VramReading(free_mib, reason), cuda
        self.vram_reads = 0
        self.cuda_asked = 0

    def count(self) -> int:
        return self.stage

    def read(self) -> VramReading:
        self.vram_reads += 1
        return self.reading

    def has_cuda(self) -> bool:
        self.cuda_asked += 1
        return self.cuda

    def choose(self, threshold_gb: float = 8.0) -> DeviceChoice:
        return choose_transcription_device(self.count, self.read, threshold_gb, self.has_cuda)


def test_an_idle_stage_with_enough_free_memory_may_use_the_gpu():
    probes = Probes(stage=0, free_mib=10 * 1024)
    assert probes.choose(8.0) == DeviceChoice("cuda", None)


def test_a_connected_stage_means_cpu_with_the_reason_and_no_probe_is_needed():
    probes = Probes(stage=1)
    assert probes.choose() == DeviceChoice("cpu", "有舞台連線")
    assert probes.vram_reads == 0 and probes.cuda_asked == 0


def test_free_memory_below_the_threshold_means_cpu():
    assert Probes(free_mib=7 * 1024).choose(8.0) == DeviceChoice("cpu", "剩餘顯存不足")


def test_free_memory_exactly_at_the_threshold_is_enough():
    assert Probes(free_mib=8 * 1024).choose(8.0) == DeviceChoice("cuda", None)


def test_unknown_free_memory_is_treated_as_too_little():
    probes = Probes(free_mib=None, reason="找不到 nvidia-smi")
    assert probes.choose() == DeviceChoice("cpu", "無法查詢顯存")


def test_the_stage_reason_wins_when_both_conditions_apply():
    assert Probes(stage=2, free_mib=1024).choose() == DeviceChoice("cpu", "有舞台連線")


def test_a_machine_without_cuda_says_so_instead_of_switching_silently():
    assert Probes(cuda=False).choose() == DeviceChoice("cpu", "沒有可用的 CUDA 裝置")


def test_cuda_is_only_asked_after_the_guard_allows_it():
    probes = Probes(free_mib=1024)
    probes.choose(8.0)
    assert probes.cuda_asked == 0

