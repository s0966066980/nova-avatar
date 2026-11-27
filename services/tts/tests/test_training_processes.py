# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""run_process: line streaming and cancellation, with fake children."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from nova_tts.training import processes
from nova_tts.training.processes import PopenProcess, run_process
from training_fakes import FakeProcess

CLOCK = time.monotonic


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(processes, "POLL_SECONDS", 0.01)


def run(process: FakeProcess, cancel: threading.Event | None = None, **kwargs):
    lines: list[str] = []
    result = run_process(lambda *_: process, ["train"], {}, Path("."), lines.append, cancel or threading.Event(), **kwargs)
    return result, lines


def test_output_lines_reach_the_callback_and_the_exit_code_is_returned():
    result, lines = run(FakeProcess(["step=1/2", "step=2/2"], returncode=3))
    assert lines == ["step=1/2", "step=2/2"]
    assert (result.returncode, result.cancelled, result.killed) == (3, False, False)


def test_cancel_sends_sigterm_and_no_kill_when_the_child_exits():
    cancel = threading.Event()
    process = FakeProcess(["started"], returncode=None)
    threading.Timer(0.05, cancel.set).start()
    result, lines = run(process, cancel, grace_seconds=5.0)
    assert process.signals == ["TERM"]
    assert (result.returncode, result.cancelled, result.killed) == (-15, True, False)
    assert lines == ["started"]


def test_a_child_that_ignores_sigterm_is_killed_after_the_grace_period():
    cancel = threading.Event()
    process = FakeProcess([], returncode=None, ignore_term=True)
    cancel.set()
    now = [0.0]

    def clock():
        now[0] += 3.0  # every look at the clock is three seconds later
        return now[0]

    result, _ = run(process, cancel, grace_seconds=5.0, clock=clock)
    assert process.signals[0] == "TERM" and "KILL" in process.signals
    assert process.signals.count("KILL") == 1
    assert result.cancelled and result.killed and result.returncode == -9


def test_the_real_process_wrapper_streams_output_and_is_stopped_by_sigterm(tmp_path):
    started = PopenProcess([sys.executable, "-u", "-c", "import time;print('hi');time.sleep(60)"], {}, tmp_path)
    assert started.readline() == "hi\n"
    started.terminate()
    assert started.wait(timeout=10) == -15
    assert started.readline() == ""
