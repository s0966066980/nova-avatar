# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Run the real launchers with isolated Docker, systemd and server processes."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher(tmp_path):
    project = tmp_path / "project"
    for directory in (
        "scripts", "config", "web/node_modules", ".venv",
        ".local/ragflow/upstream/.git", "integrations/ragflow",
    ):
        (project / directory).mkdir(parents=True)
    for name in ("start-all.sh", "ragflow.sh"):
        shutil.copy2(ROOT / "scripts" / name, project / "scripts" / name)
    (project / "config/config.yaml").write_text("app:\n  ssl: false\n")
    (project / "config/ragflow.env").write_text("NOVA_RAGFLOW_API_KEY=test-private-key\n")
    (project / "scripts/ragflow_prepare.py").write_text("pass\n")
    (project / "scripts/ragflow_validate.py").write_text("import sys\nsys.stdin.read()\n")

    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "fake-command"
    fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
        import os
        from pathlib import Path
        import subprocess
        import sys

        command, args = Path(sys.argv[0]).name, sys.argv[1:]
        state = Path(os.environ["NOVA_TEST_STATE"])
        with (state / "events").open("a") as events:
            events.write(command + " " + " ".join(args) + "\\n")
        def marked(name):
            return (state / name).exists()
        def mark(name):
            (state / name).touch()
        def fail():
            sys.exit(1)

        if command == "docker":
            if args[0] == "info":
                if not marked("docker-ready") or marked("socket-denied"):
                    fail()
            elif args[0] == "context":
                print("unix:///var/run/docker.sock")
            elif args[0] == "ps":
                if marked("containers"):
                    print("existing-container")
            elif args[0] == "network":
                print("172.17.0.1")
            elif args[0] == "compose":
                if "version" in args:
                    print("v2.40.0")
                elif "config" in args:
                    if "--format" in args:
                        print("{}")
                elif "up" in args:
                    if marked("compose-fails"):
                        fail()
                    mark("containers")
                elif "down" in args:
                    (state / "containers").unlink(missing_ok=True)
        elif command == "systemctl":
            if "is-active" in args:
                if "--user" in args:
                    if not marked("embedding"):
                        fail()
                elif not marked("docker-ready"):
                    fail()
            elif "show" in args:
                print("loaded")
            elif "start" in args and "docker" in args:
                mark("docker-ready")
                if marked("resume-containers"):
                    mark("containers")
            elif "--user" in args and "enable" in args:
                mark("embedding")
            elif "--user" in args and "disable" in args:
                (state / "embedding").unlink(missing_ok=True)
        elif command == "sudo":
            if marked("sudo-denied"):
                fail()
            sys.exit(subprocess.run(args).returncode)
        elif command == "id":
            print("1000")
        elif command == "git":
            print("v0.27.2")
        elif command == "curl":
            url = args[-1]
            if "9380" in url:
                if marked("api-unavailable"):
                    fail()
                print("pong")
            elif "8010" in url:
                if not marked("backend"):
                    fail()
                print('{"ready": true}')
            else:
                print("{}")
        elif command == "uv":
            assert os.environ.get("NOVA_RAGFLOW_API_KEY") == "test-private-key"
            mark("backend")
            os.execl("/bin/sleep", "sleep", "60")
        elif command == "npm":
            assert "NOVA_RAGFLOW_API_KEY" not in os.environ
            mark("frontend")
        elif command == "lsof":
            fail()
    '''))
    fake.chmod(0o755)
    for command in ("docker", "systemctl", "sudo", "id", "git", "curl", "uv", "npm", "node", "lsof"):
        (bin_dir / command).symlink_to(fake)

    def run(script="start-all.sh", *args, **env):
        result = subprocess.run(
            ["bash", str(project / "scripts" / script), *args],
            cwd=project,
            env={
                **{key: value for key, value in os.environ.items()
                   if not key.startswith(("NOVA_", "DOCKER_"))},
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "NOVA_TEST_STATE": str(state),
                "NOVA_RAGFLOW_STARTUP_TIMEOUT": "1",
                **env,
            },
            capture_output=True, text=True, timeout=15,
        )
        events = (state / "events").read_text() if (state / "events").exists() else ""
        return result, events

    return state, run


def test_start_all_starts_docker_and_all_services_then_cleans_up(launcher):
    state, run = launcher
    result, events = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sudo systemctl start docker" in events
    assert events.index("systemctl start docker") < events.index("docker ps")
    assert "--wait" in events
    assert "/api/v1/system/ping" in events
    assert "11435/api/tags" in events
    assert (state / "backend").exists()
    assert (state / "frontend").exists()
    assert not (state / "containers").exists()
    assert not (state / "embedding").exists()
    assert "test-private-key" not in result.stdout + result.stderr


@pytest.mark.parametrize("resume", [False, True])
def test_existing_ragflow_is_preserved_including_docker_auto_restart(launcher, resume):
    state, run = launcher
    (state / ("resume-containers" if resume else "docker-ready")).touch()
    if not resume:
        (state / "containers").touch()
    result, events = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert " down" not in events
    assert (state / "containers").exists()
    if not resume:
        assert "sudo " not in events


def test_docker_authentication_failure_does_not_claim_or_stop_services(launcher):
    state, run = launcher
    (state / "sudo-denied").touch()
    result, events = run()
    assert result.returncode != 0
    assert " up" not in events
    assert " down" not in events
    assert "uv " not in events
    assert "sudo" in result.stdout + result.stderr


def test_remote_docker_failure_does_not_start_local_daemon(launcher):
    _, run = launcher
    result, events = run("ragflow.sh", "ensure-docker", DOCKER_HOST="tcp://remote.invalid:2376")
    assert result.returncode != 0
    assert "systemctl start docker" not in events
    assert "sudo " not in events


def test_active_daemon_with_socket_permission_error_is_not_restarted(launcher):
    state, run = launcher
    (state / "docker-ready").touch()
    (state / "socket-denied").touch()
    result, events = run("ragflow.sh", "ensure-docker")
    assert result.returncode != 0
    assert "systemctl start docker" not in events
    assert "權限" in result.stderr


def test_ragflow_api_must_be_ready_before_backend_starts(launcher):
    state, run = launcher
    (state / "docker-ready").touch()
    (state / "api-unavailable").touch()
    result, events = run()
    assert result.returncode != 0
    assert "uv " not in events
    assert " down" in events
    assert not (state / "containers").exists()


def test_explicitly_disabled_ragflow_does_not_require_docker(launcher):
    state, run = launcher
    result, events = run(NOVA_START_RAGFLOW="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "docker " not in events
    assert (state / "backend").exists()
    assert (state / "frontend").exists()


def test_read_only_status_does_not_start_docker(launcher):
    _, run = launcher
    result, events = run("ragflow.sh", "status")
    assert result.returncode != 0
    assert "sudo " not in events
    assert "systemctl start docker" not in events
