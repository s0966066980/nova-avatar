# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""SIGTERM stops the backend in bounded time, running the shutdown hooks first."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each mode mimics a session thread that only ends when shutdown releases it.
SERVER_SCRIPT = textwrap.dedent(
    """
    import asyncio, sys, threading
    from types import SimpleNamespace
    sys.path.insert(0, sys.argv[5])
    from aiohttp import web
    import src.server.server as server

    mode, port, marker, deadline = sys.argv[1], int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
    server.SHUTDOWN_DEADLINE_SECONDS = deadline
    release = threading.Event()

    def session_thread():
        release.wait()
        with open(marker, "a") as f:
            f.write("thread-exited\\n")

    threading.Thread(target=session_thread, name="session-worker").start()

    async def on_shutdown(app):
        with open(marker, "a") as f:
            f.write("hook-ran\\n")
        if mode == "stuck_hook":
            await asyncio.sleep(3600)
        if mode == "slow_hook":
            await asyncio.sleep(1.5)
        if mode != "stuck_thread":
            release.set()

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    config = SimpleNamespace(app=SimpleNamespace(
        ssl=False, ssl_cert="", ssl_key="", listenhost="127.0.0.1", listenport=port,
    ))
    server.run_server(app, config)
    """
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, process: subprocess.Popen, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"server exited early: {process.communicate()}")
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError("server did not start listening")


class ServerShutdownTests(unittest.TestCase):
    def run_and_terminate(
        self, mode: str, *, deadline: float, sig=signal.SIGTERM, then=None
    ):
        workdir = Path(tempfile.mkdtemp(prefix="nova-shutdown-"))
        script = workdir / "serve.py"
        script.write_text(SERVER_SCRIPT, encoding="utf-8")
        marker = workdir / "marker.txt"
        port = _free_port()
        process = subprocess.Popen(
            [sys.executable, "-I", str(script), mode, str(port), str(marker), str(deadline), str(ROOT)],
            # The backend logger writes to ./logs; keep test runs out of the project's logs.
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        _wait_for_port(port, process)
        started = time.monotonic()
        process.send_signal(sig)
        if then is not None:
            second, delay = then
            time.sleep(delay)
            if process.poll() is None:
                process.send_signal(second)
        process.communicate(timeout=deadline + 30)
        elapsed = time.monotonic() - started
        events = marker.read_text(encoding="utf-8").split() if marker.exists() else []
        return process.returncode, elapsed, events

    def test_sigterm_runs_shutdown_hooks_and_releases_session_threads(self):
        code, elapsed, events = self.run_and_terminate("clean", deadline=20)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(events, ["hook-ran", "thread-exited"])
        self.assertLess(elapsed, 10)

    def test_sigint_takes_the_same_orderly_path(self):
        code, _elapsed, events = self.run_and_terminate("clean", deadline=20, sig=signal.SIGINT)
        self.assertEqual(code, 128 + signal.SIGINT)
        self.assertEqual(events, ["hook-ran", "thread-exited"])

    def test_sigterm_after_ctrl_c_does_not_cut_the_orderly_stop_short(self):
        code, _elapsed, events = self.run_and_terminate(
            "slow_hook", deadline=20, sig=signal.SIGINT, then=(signal.SIGTERM, 0.3)
        )
        self.assertEqual(code, 128 + signal.SIGINT)
        self.assertEqual(events, ["hook-ran", "thread-exited"])

    def test_a_repeated_ctrl_c_does_not_cut_the_orderly_stop_short(self):
        code, _elapsed, events = self.run_and_terminate(
            "slow_hook", deadline=20, sig=signal.SIGINT, then=(signal.SIGINT, 0.3)
        )
        self.assertEqual(code, 128 + signal.SIGINT)
        self.assertEqual(events, ["hook-ran", "thread-exited"])

    def test_a_thread_that_never_stops_cannot_hold_the_process_past_the_deadline(self):
        code, elapsed, events = self.run_and_terminate("stuck_thread", deadline=2)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(events, ["hook-ran"])
        self.assertLess(elapsed, 10)

    def test_a_hanging_shutdown_hook_cannot_hold_the_process_past_the_deadline(self):
        code, elapsed, events = self.run_and_terminate("stuck_hook", deadline=2)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(events, ["hook-ran"])
        self.assertLess(elapsed, 10)


if __name__ == "__main__":
    unittest.main()
