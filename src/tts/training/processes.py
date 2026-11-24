# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Child processes of the training job: spawning, line streaming and cancellation.

Training, export and the Whisper check run as separate processes so that stopping
one releases its GPU or memory at once. ``Process`` is the small interface the job
depends on; ``PopenProcess`` is the real implementation (its own session, so the
whole process group is signalled, including data-loader workers) and tests supply a
fake. ``run_process`` streams output lines to a callback, and on cancel sends
SIGTERM, then SIGKILL once the grace period has passed.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

POLL_SECONDS = 0.2
DEFAULT_GRACE_SECONDS = 10.0
READER_JOIN_SECONDS = 5.0


class Process(Protocol):
    def readline(self) -> str:
        """The next output line (stdout and stderr merged), ``""`` at end of output."""

    def write_line(self, text: str) -> None:
        """Send a line to the process's standard input."""

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int:
        """The exit code; raises ``subprocess.TimeoutExpired`` when it has not exited."""


Spawn = Callable[[Sequence[str], Mapping[str, str], Path], Process]


class PopenProcess:
    def __init__(self, command: Sequence[str], env: Mapping[str, str], cwd: Path) -> None:
        self._popen = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )

    def readline(self) -> str:
        assert self._popen.stdout is not None
        return self._popen.stdout.readline()

    def write_line(self, text: str) -> None:
        assert self._popen.stdin is not None
        self._popen.stdin.write(text + "\n")
        self._popen.stdin.flush()

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)

    def wait(self, timeout: float | None = None) -> int:
        return self._popen.wait(timeout=timeout)

    def _signal(self, number: int) -> None:
        try:
            os.killpg(self._popen.pid, number)
        except (ProcessLookupError, PermissionError):
            pass


def spawn_process(command: Sequence[str], env: Mapping[str, str], cwd: Path) -> Process:
    return PopenProcess(command, env, cwd)


def iter_lines(process: Process) -> Iterator[str]:
    while line := process.readline():
        yield line.rstrip("\r\n")


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    cancelled: bool
    killed: bool


def run_process(
    spawn: Spawn,
    command: Sequence[str],
    env: Mapping[str, str],
    cwd: Path,
    on_line: Callable[[str], None],
    cancel: threading.Event,
    *,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> ProcessResult:
    """Run ``command`` to the end, feeding output lines to ``on_line``.

    On ``cancel`` the process gets SIGTERM; one that is still alive ``grace_seconds``
    later is killed. Blocking: call it from the job's worker thread.
    """
    process = spawn(command, env, cwd)

    def read() -> None:
        for line in iter_lines(process):
            on_line(line)

    reader = threading.Thread(target=read, name="training-process-output", daemon=True)
    reader.start()
    terminated_at: float | None = None
    killed = False
    while True:
        try:
            code = process.wait(timeout=POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            pass
        if not cancel.is_set():
            continue
        if terminated_at is None:
            process.terminate()
            terminated_at = clock()
        elif not killed and clock() - terminated_at >= grace_seconds:
            process.kill()
            killed = True
    reader.join(READER_JOIN_SECONDS)
    return ProcessResult(code, terminated_at is not None, killed)
