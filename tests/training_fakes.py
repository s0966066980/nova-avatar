# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Fake child processes for the training tests: no real subprocess, model or GPU."""

from __future__ import annotations

import queue
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


class FakeProcess:
    """A scripted child process.

    ``lines`` is what it prints; ``returncode`` is its exit code once the lines are
    out (``None`` keeps it running until it is signalled). ``ignore_term`` makes it
    survive SIGTERM so that the kill escalation can be observed. ``on_line`` receives
    each line written to its standard input and may return reply lines. ``pid`` is what a
    tracked spawn records in the job state.
    """

    def __init__(
        self,
        lines: Sequence[str] = (),
        returncode: int | None = 0,
        *,
        ignore_term: bool = False,
        on_line: Callable[[str], Sequence[str]] | None = None,
        release: threading.Event | None = None,
        pid: int | None = None,
    ) -> None:
        self.pid = pid
        self.signals: list[str] = []
        self.written: list[str] = []
        self._ignore_term = ignore_term
        self._on_line = on_line
        self._out: queue.Queue[str | None] = queue.Queue()
        self._exited = threading.Event()
        self._code = returncode
        self.returncode: int | None = None
        for line in lines:
            self._out.put(line + "\n")
        if returncode is not None and release is None:
            self._finish(returncode)
        elif returncode is not None and release is not None:
            threading.Thread(target=self._finish_when, args=(release, returncode), daemon=True).start()

    def _finish_when(self, release: threading.Event, code: int) -> None:
        release.wait(30)
        self._finish(code)

    def _finish(self, code: int) -> None:
        if self._exited.is_set():
            return
        self.returncode = code
        self._exited.set()
        self._out.put(None)

    def readline(self) -> str:
        item = self._out.get()
        if item is None:
            self._out.put(None)
            return ""
        return item

    def write_line(self, text: str) -> None:
        self.written.append(text)
        if self._on_line is not None:
            for reply in self._on_line(text):
                self._out.put(reply + "\n")

    def terminate(self) -> None:
        self.signals.append("TERM")
        if not self._ignore_term:
            self._finish(-15)

    def kill(self) -> None:
        self.signals.append("KILL")
        self._finish(-9)

    def wait(self, timeout: float | None = None) -> int:
        if not self._exited.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout or 0)
        assert self.returncode is not None
        return self.returncode


class FakeSpawner:
    """A ``Spawn`` that records every command and returns the process a handler builds.

    ``handler(command, env, cwd)`` returns the ``FakeProcess``; it may also create
    files (a training script writes checkpoints), as the real child would.
    """

    def __init__(self, handler: Callable[[Sequence[str], Mapping[str, str], Path], FakeProcess]) -> None:
        self.handler = handler
        self.commands: list[list[str]] = []
        self.envs: list[Mapping[str, str]] = []
        self.cwds: list[Path] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, command: Sequence[str], env: Mapping[str, str], cwd: Path) -> FakeProcess:
        self.commands.append(list(command))
        self.envs.append(dict(env))
        self.cwds.append(cwd)
        process = self.handler(command, env, cwd)
        self.processes.append(process)
        return process


def argument(command: Sequence[str], flag: str) -> str:
    """The value that follows ``flag`` in ``command``."""
    return command[list(command).index(flag) + 1]


def tone_wav(seconds: float = 1.5, rate: int = 16000, amplitude: float = 0.3) -> bytes:
    """A WAV of silence, a 220 Hz tone and silence: it passes the audio quality check."""
    import io

    import numpy as np
    import soundfile as sf

    t = np.arange(int(rate * seconds)) / rate
    body = amplitude * np.sin(2 * np.pi * 220 * t)
    mono = np.concatenate([np.zeros(int(rate * 0.3)), body, np.zeros(int(rate * 0.3))]).astype("float32")
    buffer = io.BytesIO()
    sf.write(buffer, mono, rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
