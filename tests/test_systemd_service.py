# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Tests for graceful SIGTERM/SIGINT server shutdown and Jetson systemd service."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.server.server import create_app, on_shutdown, run_server
from src.server.state import state


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SERVICE_SCRIPT = ROOT / "scripts" / "jetson-service.sh"
UNIT_TEMPLATE = ROOT / "integrations" / "systemd" / "nova-avatar.service"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class GracefulServerShutdownTests(unittest.TestCase):
    def test_sigterm_runs_runner_cleanup_sessions_and_owned_llama_shutdown(self):
        """SIGTERM after install_shutdown_handlers must run on_shutdown and leave no orphan child."""
        port = _free_port()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ready_file = tmp_path / "ready.txt"
            shutdown_file = tmp_path / "shutdown.txt"
            child_pid_file = tmp_path / "child.pid"

            harness = textwrap.dedent(
                f"""
                import asyncio
                import os
                import subprocess
                import sys
                from pathlib import Path
                from types import SimpleNamespace

                sys.path.insert(0, {str(ROOT)!r})
                import src.llm.llamacpp as llamacpp
                from src.server.server import create_app, run_server
                from src.server.state import state

                # Install llamacpp pre-startup handlers just like src/server/app.py does.
                llamacpp.install_shutdown_handlers()

                # Spawn a detached dummy child to simulate an owned llama-server.
                child = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    start_new_session=True,
                )
                llamacpp._server_proc = child
                Path({str(child_pid_file)!r}).write_text(str(child.pid), encoding="utf-8")

                events = []

                async def fake_session_cleanup():
                    events.append("session_cleanup")
                    state.session_cleanups.pop(101, None)

                class FakePC:
                    async def close(self):
                        events.append("pc_close")

                state.session_cleanups[101] = fake_session_cleanup
                state.pcs.add(FakePC())

                app = create_app()

                async def record_shutdown(_app):
                    events.append("app_on_shutdown")
                    Path({str(shutdown_file)!r}).write_text("\\n".join(events), encoding="utf-8")

                app.on_shutdown.append(record_shutdown)

                config = SimpleNamespace(
                    app=SimpleNamespace(
                        listenhost="127.0.0.1",
                        listenport={port},
                        ssl=False,
                        ssl_cert=None,
                        ssl_key=None,
                    )
                )
                Path({str(ready_file)!r}).write_text("starting", encoding="utf-8")
                run_server(app, config)
                """
            )
            env = dict(os.environ, PYTHONPATH=str(ROOT))
            proc = subprocess.Popen(
                [PYTHON, "-c", harness],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            child_pid = None
            try:
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    if child_pid_file.is_file():
                        child_pid = int(child_pid_file.read_text(encoding="utf-8").strip())
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        if proc.poll() is not None:
                            out, err = proc.communicate()
                            self.fail(f"Server exited early ({proc.returncode}): {out}\n{err}")
                        time.sleep(0.05)
                else:
                    self.fail("Server did not start listening in time")

                proc.send_signal(signal.SIGTERM)
                out, err = proc.communicate(timeout=10.0)
                self.assertEqual(
                    proc.returncode,
                    0,
                    f"Expected clean exit 0 on SIGTERM, got {proc.returncode}\nstdout={out}\nstderr={err}",
                )
                self.assertTrue(
                    shutdown_file.is_file(),
                    "app.on_shutdown was bypassed on SIGTERM",
                )
                events = shutdown_file.read_text(encoding="utf-8").splitlines()
                self.assertIn("session_cleanup", events)
                self.assertIn("pc_close", events)
                self.assertIn("app_on_shutdown", events)

                # Confirm the detached owned child process was terminated (no orphan).
                self.assertIsNotNone(child_pid)
                dead_deadline = time.monotonic() + 3.0
                while time.monotonic() < dead_deadline:
                    try:
                        os.kill(child_pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    self.fail(f"Orphan owned child process {child_pid} still alive after SIGTERM")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
                if child_pid is not None:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_sigint_runs_runner_cleanup_in_process_and_restores_server_ready(self):
        port = _free_port()
        app = create_app()
        cleanup_ran = []

        async def record_cleanup(_app):
            cleanup_ran.append(True)

        app.on_shutdown.append(record_cleanup)
        config = SimpleNamespace(
            app=SimpleNamespace(
                listenhost="127.0.0.1",
                listenport=port,
                ssl=False,
                ssl_cert=None,
                ssl_key=None,
            )
        )
        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)
        prev_ready = state.server_ready

        def _send_sigint():
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.02)
            os.kill(os.getpid(), signal.SIGINT)

        timer = threading.Timer(0.05, _send_sigint)
        timer.start()
        try:
            with patch("src.server.routes.webrtc.close_sessions", new=AsyncMock()), patch(
                "src.tts.engines.edge.shutdown_edge_tts"
            ), patch("src.server.server.shutdown_llama_server") as llama_stop, patch(
                "src.server.server.shutdown_cosyvoice_server"
            ) as cosy_stop, patch("src.server.server.scene_service.close"), patch(
                "src.server.server.routing_clients.close"
            ):
                run_server(app, config)
            self.assertEqual(cleanup_ran, [True])
            self.assertFalse(state.server_ready)
            llama_stop.assert_called_once()
            cosy_stop.assert_called_once()
        finally:
            timer.cancel()
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)
            state.server_ready = prev_ready

    def test_on_shutdown_still_stops_owned_servers_if_session_cleanup_fails(self):
        app = MagicMock()
        with patch(
            "src.server.routes.webrtc.close_sessions",
            new=AsyncMock(side_effect=RuntimeError("webrtc close boom")),
        ), patch("src.tts.engines.edge.shutdown_edge_tts"), patch(
            "src.server.server.shutdown_llama_server"
        ) as llama_stop, patch(
            "src.server.server.shutdown_cosyvoice_server"
        ) as cosy_stop, patch("src.server.server.scene_service.close"), patch(
            "src.server.server.routing_clients.close"
        ):
            asyncio.run(on_shutdown(app))
        llama_stop.assert_called_once()
        cosy_stop.assert_called_once()


class SystemdUnitAndCliRenderTests(unittest.TestCase):
    def test_unit_template_and_cli_help_exist(self):
        self.assertTrue(UNIT_TEMPLATE.is_file(), f"Missing {UNIT_TEMPLATE}")
        self.assertTrue(SERVICE_SCRIPT.is_file(), f"Missing {SERVICE_SCRIPT}")

        res = subprocess.run(
            ["bash", str(SERVICE_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        for subcommand in (
            "install",
            "uninstall",
            "start",
            "stop",
            "restart",
            "status",
            "logs",
            "check",
            "health",
            "render-unit",
        ):
            self.assertIn(subcommand, res.stdout)

    def test_render_unit_contains_jetson_preflight_env_and_shutdown_settings(self):
        res = subprocess.run(
            ["bash", str(SERVICE_SCRIPT), "render-unit"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "NOVA_START_RAGFLOW": "0"},
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        unit = res.stdout
        self.assertIn("[Unit]", unit)
        self.assertIn("[Service]", unit)
        self.assertIn("[Install]", unit)
        self.assertIn(f"WorkingDirectory={ROOT}", unit)
        self.assertIn("ExecStartPre=", unit)
        self.assertIn("scripts/check-cuda.py", unit)
        self.assertIn("ExecStart=", unit)
        self.assertIn("src/server/app.py --config config/config_jetson.yaml", unit)
        for env_line in (
            "Environment=OMP_NUM_THREADS=1",
            "Environment=OPENBLAS_NUM_THREADS=1",
            "Environment=MKL_NUM_THREADS=1",
            "Environment=OPENCV_FOR_THREADS_NUM=1",
            "Environment=NOVA_START_RAGFLOW=0",
        ):
            self.assertIn(env_line, unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("TimeoutStopSec=30", unit)
        self.assertIn("KillMode=mixed", unit)
        self.assertIn("StandardOutput=journal", unit)
        self.assertIn("StandardError=journal", unit)
        self.assertIn("WantedBy=default.target", unit)


class SystemdLifecycleAndPreflightTests(unittest.TestCase):
    def _make_fake_bin(
        self,
        tmp_path: Path,
        *,
        linger: str = "yes",
        ollama_active: bool = False,
        ollama_rss_kb: int = 1782579,
        service_active: str = "inactive",
    ) -> tuple[Path, Path]:
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        call_log = tmp_path / "calls.log"

        systemctl = fake_bin / "systemctl"
        systemctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                echo "systemctl $*" >> {str(call_log)!r}
                if [ "$1" = "is-active" ]; then
                    if [ "${{2:-}}" = "--quiet" ] && [ "${{3:-}}" = "ollama" ]; then
                        exit {0 if ollama_active else 3}
                    fi
                fi
                if [ "$1" = "--user" ] && [ "${{2:-}}" = "is-active" ]; then
                    echo {service_active!r}
                    [ {service_active!r} = "active" ] && exit 0 || exit 3
                fi
                exit 0
                """
            ),
            encoding="utf-8",
        )
        systemctl.chmod(0o755)

        loginctl = fake_bin / "loginctl"
        loginctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                echo "loginctl $*" >> {str(call_log)!r}
                echo {linger!r}
                """
            ),
            encoding="utf-8",
        )
        loginctl.chmod(0o755)

        journalctl = fake_bin / "journalctl"
        journalctl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                echo "journalctl $*" >> {str(call_log)!r}
                echo "sample journal line"
                """
            ),
            encoding="utf-8",
        )
        journalctl.chmod(0o755)

        ps_stub = fake_bin / "ps"
        if ollama_active:
            ps_body = f'echo "4321 {ollama_rss_kb} ollama /usr/local/bin/ollama serve"\n'
        else:
            ps_body = 'echo "100 1024 bash -bash"\n'
        ps_stub.write_text(f"#!/usr/bin/env bash\n{ps_body}", encoding="utf-8")
        ps_stub.chmod(0o755)

        return fake_bin, call_log

    def test_install_and_uninstall_use_isolated_systemd_dir_without_touching_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin, call_log = self._make_fake_bin(tmp_path, linger="no")
            systemd_dir = tmp_path / "systemd-user"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "NOVA_SYSTEMD_USER_DIR": str(systemd_dir),
                "NOVA_START_RAGFLOW": "0",
                "UV_PROJECT_ENVIRONMENT": "/home/oliver/nova-avatar/.venv",
            }

            install_res = subprocess.run(
                ["bash", str(SERVICE_SCRIPT), "install"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(install_res.returncode, 0, install_res.stderr)
            unit_file = systemd_dir / "nova-avatar.service"
            self.assertTrue(unit_file.is_file())
            self.assertIn("ExecStartPre=", unit_file.read_text(encoding="utf-8"))
            self.assertIn("enable-linger", install_res.stdout)

            calls = call_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("systemctl --user daemon-reload", calls)
            self.assertIn("systemctl --user enable nova-avatar.service", calls)

            uninstall_res = subprocess.run(
                ["bash", str(SERVICE_SCRIPT), "uninstall"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(uninstall_res.returncode, 0, uninstall_res.stderr)
            self.assertFalse(unit_file.exists())
            calls_after = call_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("systemctl --user disable --now nova-avatar.service", calls_after)

    def test_start_stop_restart_status_logs_dispatch_to_user_systemd(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin, call_log = self._make_fake_bin(tmp_path, service_active="active")
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "NOVA_SYSTEMD_USER_DIR": str(tmp_path / "systemd-user"),
                "NOVA_START_RAGFLOW": "0",
                "UV_PROJECT_ENVIRONMENT": "/home/oliver/nova-avatar/.venv",
            }
            for cmd in ("start", "stop", "restart", "status"):
                res = subprocess.run(
                    ["bash", str(SERVICE_SCRIPT), cmd],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(res.returncode, 0, f"{cmd} failed: {res.stderr}")

            logs_res = subprocess.run(
                ["bash", str(SERVICE_SCRIPT), "logs", "--no-pager", "-n", "20"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(logs_res.returncode, 0, logs_res.stderr)
            self.assertIn("sample journal line", logs_res.stdout)

            calls = call_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("systemctl --user start nova-avatar.service", calls)
            self.assertIn("systemctl --user stop nova-avatar.service", calls)
            self.assertIn("systemctl --user restart nova-avatar.service", calls)
            self.assertIn("systemctl --user status nova-avatar.service --no-pager", calls)
            self.assertIn("journalctl --user -u nova-avatar.service --no-pager -n 20", calls)

    def test_check_detects_external_ollama_and_advises_without_auto_killing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin, call_log = self._make_fake_bin(
                tmp_path, linger="no", ollama_active=True, ollama_rss_kb=1782579
            )
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "NOVA_START_RAGFLOW": "0",
                "UV_PROJECT_ENVIRONMENT": "/home/oliver/nova-avatar/.venv",
            }
            res = subprocess.run(
                ["bash", str(SERVICE_SCRIPT), "check"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("ollama", res.stdout)
            self.assertIn("1.70 GB", res.stdout)
            self.assertIn("sudo systemctl stop ollama", res.stdout)
            self.assertIn("enable-linger", res.stdout)

            calls = call_log.read_text(encoding="utf-8")
            self.assertNotIn("stop ollama", calls)
            self.assertNotIn("disable", calls)

    def test_health_subcommand_checks_ready_flag_over_http(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        ready_flag = {"ready": True}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/health":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = (
                    '{"code": 0, "ready": true}'
                    if ready_flag["ready"]
                    else '{"code": 0, "ready": false}'
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cfg = Path(tmp) / "health_test.yaml"
                cfg.write_text(f"app:\n  listenport: {port}\n  ssl: false\n", encoding="utf-8")
                env = {**os.environ, "NOVA_CONFIG_FILE": str(cfg)}

                ok_res = subprocess.run(
                    ["bash", str(SERVICE_SCRIPT), "health"],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(ok_res.returncode, 0, ok_res.stderr)
                self.assertIn('"ready": true', ok_res.stdout)

                ready_flag["ready"] = False
                fail_res = subprocess.run(
                    ["bash", str(SERVICE_SCRIPT), "health"],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                self.assertNotEqual(fail_res.returncode, 0)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
