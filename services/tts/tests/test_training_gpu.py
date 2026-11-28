# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Free-VRAM probe: a fake ``nvidia-smi`` runner, never a real GPU."""

from __future__ import annotations

import subprocess

import pytest

from nova_tts.training.gpu_guard import (
    DeviceChoice,
    choose_transcription_device,
)
from nova_tts.training.gpu_probe import QUERY, VramReading, read_free_vram

pytestmark = pytest.mark.speech


def runner(stdout: str = "", returncode: int = 0, raises: Exception | None = None):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    run.calls = calls
    return run


def test_reads_the_first_gpu_free_memory():
    run = runner("9830\n24000\n")
    reading = read_free_vram(run)
    assert reading == VramReading(9830)
    assert reading.free_gb == pytest.approx(9830 / 1024)
    assert run.calls[0][0] == QUERY
    assert run.calls[0][1]["timeout"] > 0


@pytest.mark.parametrize(
    ("run", "reason"),
    [
        (runner(raises=FileNotFoundError()), "nvidia-smi"),
        (runner(raises=subprocess.TimeoutExpired("nvidia-smi", 10)), "沒有回應"),
        (runner(raises=PermissionError("denied")), "denied"),
        (runner("", returncode=9), "執行失敗"),
        (runner(""), "無法讀取"),
        (runner("[N/A]\n"), "無法讀取"),
    ],
)
def test_an_unreadable_gpu_is_unknown_with_a_reason(run, reason):
    reading = read_free_vram(run)
    assert reading.free_mib is None and reading.free_gb is None
    assert reason in reading.reason


# --- the TTS layer's free-VRAM guard (the stage half is the core's: test_stage_guard) ---


def test_free_vram_check_treats_unknown_as_insufficient():
    from nova_tts.training.gpu_guard import free_vram_check

    assert free_vram_check(VramReading(8192), 8.0).status == "pass"
    assert free_vram_check(VramReading(8191), 8.0).status == "fail"
    unknown = free_vram_check(VramReading(None, "找不到 nvidia-smi"), 8.0)
    assert unknown.status == "fail" and "找不到 nvidia-smi" in unknown.reason


class Probes:
    """Fake VRAM probe and CUDA availability that record being asked."""

    def __init__(self, *, free_mib: int | None = 24 * 1024, reason: str = "", cuda: bool = True):
        self.reading, self.cuda = VramReading(free_mib, reason), cuda
        self.vram_reads = 0
        self.cuda_asked = 0

    def read(self) -> VramReading:
        self.vram_reads += 1
        return self.reading

    def has_cuda(self) -> bool:
        self.cuda_asked += 1
        return self.cuda

    def choose(self, threshold_gb: float = 8.0) -> DeviceChoice:
        return choose_transcription_device(self.read, threshold_gb, self.has_cuda)


def test_enough_free_memory_may_use_the_gpu():
    probes = Probes(free_mib=10 * 1024)
    assert probes.choose(8.0) == DeviceChoice("cuda", None)
    assert probes.vram_reads == 1


def test_free_memory_below_the_threshold_means_cpu():
    assert Probes(free_mib=7 * 1024).choose(8.0) == DeviceChoice("cpu", "剩餘顯存不足")


def test_free_memory_exactly_at_the_threshold_is_enough():
    assert Probes(free_mib=8 * 1024).choose(8.0) == DeviceChoice("cuda", None)


def test_unknown_free_memory_is_treated_as_too_little():
    probes = Probes(free_mib=None, reason="找不到 nvidia-smi")
    assert probes.choose() == DeviceChoice("cpu", "無法查詢顯存")


def test_a_machine_without_cuda_says_so_instead_of_switching_silently():
    assert Probes(cuda=False).choose() == DeviceChoice("cpu", "沒有可用的 CUDA 裝置")


def test_cuda_is_only_asked_after_the_guard_allows_it():
    probes = Probes(free_mib=1024)
    probes.choose(8.0)
    assert probes.cuda_asked == 0
