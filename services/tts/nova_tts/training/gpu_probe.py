# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Free GPU memory as ``nvidia-smi`` reports it, for the training pre-flight check.

The probe never loads CUDA in the application: it runs ``nvidia-smi`` (blocking, so
call it from a worker thread) and reads the first GPU's free memory in MiB. Anything
unexpected (no ``nvidia-smi``, a timeout, a failure, unparsable output) is an
*unknown* reading with a reason; the pre-flight check treats unknown as refusal,
because starting a training run that may run out of memory would take the stage's
GPU down with it.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

QUERY = ("nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits")
TIMEOUT_SECONDS = 10.0

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class VramReading:
    """``free_mib`` is ``None`` when the memory could not be read; ``reason`` says why."""

    free_mib: int | None
    reason: str = ""

    @property
    def free_gb(self) -> float | None:
        return None if self.free_mib is None else self.free_mib / 1024


def read_free_vram(run: Runner = subprocess.run) -> VramReading:
    try:
        result = run(QUERY, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        return VramReading(None, "找不到 nvidia-smi")
    except subprocess.TimeoutExpired:
        return VramReading(None, "nvidia-smi 沒有回應")
    except OSError as exc:
        return VramReading(None, f"無法執行 nvidia-smi：{exc}")
    if result.returncode != 0:
        return VramReading(None, "nvidia-smi 執行失敗")
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    try:
        # Training uses the first GPU.
        return VramReading(int(float(lines[0])))
    except (IndexError, ValueError):
        return VramReading(None, "無法讀取 nvidia-smi 的輸出")
