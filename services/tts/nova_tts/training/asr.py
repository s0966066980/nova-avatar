# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The training job's recognition of what a corpus line actually says, on the CPU.

``transcript_check.verify_with_asr`` takes a ``transcribe(path) -> str`` callable and
loads nothing itself. ``SubprocessTranscriber`` is that callable for the training job:
it runs ``whisper_worker`` in a child of the application's own interpreter with
``CUDA_VISIBLE_DEVICES=`` so that the model never occupies the GPU the training run
needs, and the model is released when the child exits. One child serves every line.

Time estimate (CPU, int8, measured once on the development host while it was busy): the
child is ready in 1 to 4 seconds; ``small`` takes about 1.1 s for a 2 to 3 second sentence
(roughly 0.4 to 0.5 times real time), ``tiny`` about 0.3 s but it mis-hears more. The
quick-test preset (about 220 sentences) therefore needs about 4 to 5 minutes with
``small`` and the standard preset (about 830 sentences) about 15 to 17 minutes; ticket 10
re-measures this on the venue host. The job never skips this check silently.

The child never blocks the caller for good: the start-up and every request have a
timeout, and an optional ``cancel`` event is watched while waiting. On a timeout or a
cancel the child is killed at once (its whole process group), so a stuck recognition
neither holds the CPU nor outlives a cancelled job; the transcriber is unusable after that.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType

from src.tts.training.processes import Process, Spawn, spawn_process
from src.utils.paths import get_project_root

# Model sizes whose faster-whisper weights may already be in the Hugging Face cache.
WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")
DEFAULT_MODEL = "small"
STARTUP_NOTE_LINES = 5
CLOSE_WAIT_SECONDS = 5.0
# One utterance is a few seconds of speech (about 1 s on the CPU with ``small``); a child that
# takes this long is stuck. Loading ``large-v3`` on the CPU takes tens of seconds, hence the
# longer start-up limit.
UTTERANCE_TIMEOUT_SECONDS = 120.0
STARTUP_TIMEOUT_SECONDS = 300.0
POLL_SECONDS = 0.1


class TranscriberError(RuntimeError):
    """The recognition child failed to start or stopped answering."""


class TranscriberCancelled(TranscriberError):
    """The job was cancelled while the child was working; the child has been killed."""


class SubprocessTranscriber:
    """Context manager and callable: ``with SubprocessTranscriber("small") as transcribe``."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        spawn: Spawn = spawn_process,
        python: str = sys.executable,
        root: Path | None = None,
        environ: Mapping[str, str] | None = None,
        utterance_timeout: float = UTTERANCE_TIMEOUT_SECONDS,
        startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
        cancel: threading.Event | None = None,
    ) -> None:
        if model not in WHISPER_MODELS:
            raise ValueError(f"unknown Whisper model {model!r}")
        self._root = get_project_root() if root is None else root
        self._command = [python, "-m", "src.tts.training.whisper_worker", "--model", model]
        self._env = {**(os.environ if environ is None else environ), "CUDA_VISIBLE_DEVICES": ""}
        self._spawn = spawn
        self._utterance_timeout = utterance_timeout
        self._startup_timeout = startup_timeout
        self._cancel = cancel
        self._process: Process | None = None
        self._dead = False
        self._lines: queue.Queue[str] = queue.Queue()
        self._recent: deque[str] = deque(maxlen=STARTUP_NOTE_LINES)

    def __enter__(self) -> SubprocessTranscriber:
        process = self._process = self._spawn(self._command, self._env, self._root)
        threading.Thread(target=self._pump, args=(process,), name="whisper-worker-output", daemon=True).start()
        try:
            self._read_reply("ready", self._startup_timeout)
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def __call__(self, path: Path) -> str:
        if self._process is None:
            raise TranscriberError("辨識程序尚未啟動")
        if self._dead:
            raise TranscriberError("辨識程序已停止")
        self._check_cancel()
        try:
            self._process.write_line(json.dumps({"path": str(path)}))
        except OSError as exc:
            raise TranscriberError(f"辨識程序沒有回應：{exc}") from exc
        reply = self._read_reply("text", self._utterance_timeout)
        return str(reply["text"])

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=CLOSE_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _pump(self, process: Process) -> None:
        """Move the child's output lines to a queue, so that waiting for one can time out."""
        while line := process.readline():
            self._lines.put(line)
        self._lines.put("")

    def _check_cancel(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            self._kill()
            raise TranscriberCancelled("已取消，辨識程序已停止")

    def _kill(self) -> None:
        self._dead = True
        if self._process is not None:
            self._process.kill()

    def _next_line(self, deadline: float, timeout: float) -> str:
        while True:
            self._check_cancel()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill()
                raise TranscriberError(f"辨識逾時（超過 {timeout:g} 秒沒有回應），辨識程序已停止")
            try:
                return self._lines.get(timeout=min(POLL_SECONDS, remaining))
            except queue.Empty:
                continue

    def _read_reply(self, key: str, timeout: float) -> dict:
        """The next JSON reply holding ``key``; other lines are library noise and are kept for errors."""
        assert self._process is not None
        deadline = time.monotonic() + timeout
        while True:
            line = self._next_line(deadline, timeout)
            if not line:
                notes = " / ".join(self._recent)
                raise TranscriberError(f"辨識程序意外結束{('：' + notes) if notes else ''}")
            line = line.strip()
            try:
                reply = json.loads(line)
            except json.JSONDecodeError:
                reply = None
            if not isinstance(reply, dict):
                self._recent.append(line[:200])
                continue
            if "error" in reply:
                raise TranscriberError(f"辨識失敗：{reply['error']}")
            if key in reply:
                return reply
            self._recent.append(line[:200])
