# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Free-VRAM probe: a fake ``nvidia-smi`` runner, never a real GPU."""

from __future__ import annotations

import subprocess

import pytest

from src.tts.training.gpu_probe import QUERY, VramReading, read_free_vram


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
