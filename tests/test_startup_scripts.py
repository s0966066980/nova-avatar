# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Run the real launchers with isolated Docker, systemd and server processes."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]

# Stand-in for a server: reports SIGTERM, then exits unless told to ignore it.
FAKE_SERVER = f"#!{sys.executable}\n" + textwrap.dedent('''\
    import os
    from pathlib import Path
    import signal
    import time

    def on_term(*_):
        if os.environ.get("NOVA_TEST_TERM_MARKER"):
            Path(os.environ["NOVA_TEST_TERM_MARKER"]).touch()
        if os.environ.get("NOVA_TEST_IGNORE_TERM") != "1":
            raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_term)
    if os.environ.get("NOVA_TEST_READY"):
        Path(os.environ["NOVA_TEST_READY"]).touch()
    while True:
        time.sleep(0.1)
''')


def _write_fake_server(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_SERVER)
    path.chmod(0o755)
    return path


def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


@pytest.fixture
def launcher(tmp_path):
    project = tmp_path / "project"
    for directory in (
        "scripts", "config", "web/node_modules", ".venv",
        ".local/ragflow/upstream/.git", "integrations/ragflow",
    ):
        (project / directory).mkdir(parents=True)
    for name in ("start-all.sh", "start-backend.sh", "start-frontend.sh", "ragflow.sh",
                 "process-control.sh"):
        shutil.copy2(ROOT / "scripts" / name, project / "scripts" / name)
    _write_fake_server(project / "src/server/app.py")
    _write_fake_server(project / "web/node_modules/.bin/vite")
    _write_fake_server(project / "scripts/cosyvoice_fastapi_server.py")
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
            if "--version" in args:
                print("Python 3.10.19")
                sys.exit(0)
            assert os.environ.get("NOVA_RAGFLOW_API_KEY") == "test-private-key"
            if marked("spawn-children"):
                # A worker in the backend's group, and CosyVoice in its own
                # session like src/tts/cosyvoice_runtime.py starts it.
                worker = subprocess.Popen(["sleep", "60"])
                (state / "worker-pid").write_text(str(worker.pid))
                cosyvoice = subprocess.Popen(
                    [sys.executable, os.path.join(os.getcwd(), "scripts/cosyvoice_fastapi_server.py")],
                    start_new_session=True,
                )
                (state / "cosyvoice-pid").write_text(str(cosyvoice.pid))
            (state / "backend-pid").write_text(str(os.getpid()))
            mark("backend")
            # A short-lived backend: the launcher stays until its backend exits.
            seconds = (state / "backend-seconds").read_text() if marked("backend-seconds") else "3"
            os.execl("/bin/sleep", "sleep", seconds)
        elif command == "npm":
            assert "NOVA_RAGFLOW_API_KEY" not in os.environ
            (state / "npm-config").write_text(os.environ.get("CONFIG_FILE", ""))
            mark("frontend")
        elif command == "lsof":
            port = next(arg.rsplit(":", 1)[1] for arg in args if ":" in arg)
            listener = state / f"listen-{port}"
            if not listener.exists():
                fail()
            pid = listener.read_text().strip()
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
            except OSError:
                fail()
            if stat.rsplit(")", 1)[1].split()[0] == "Z":
                fail()
            print(pid)
        elif command == "ss":
            # Never report this machine's real listeners to the launchers.
            pass
    '''))
    fake.chmod(0o755)
    for command in ("docker", "systemctl", "sudo", "id", "git", "curl", "uv", "npm", "node", "lsof", "ss"):
        (bin_dir / command).symlink_to(fake)

    def launcher_env(env):
        return {
            **{key: value for key, value in os.environ.items()
               if not key.startswith(("NOVA_", "DOCKER_"))},
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "NOVA_TEST_STATE": str(state),
            "NOVA_RAGFLOW_STARTUP_TIMEOUT": "1",
            **env,
        }

    def events():
        return (state / "events").read_text() if (state / "events").exists() else ""

    def run(script="start-all.sh", *args, cwd=project, **env):
        result = subprocess.run(
            ["bash", str(project / "scripts" / script), *args],
            cwd=cwd, env=launcher_env(env),
            capture_output=True, text=True, timeout=30,
        )
        return result, events()

    def start(script="start-all.sh", *args, **env):
        return subprocess.Popen(
            ["bash", str(project / "scripts" / script), *args],
            cwd=project, env=launcher_env(env),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )

    run.project = project
    run.start = start
    return state, run


@pytest.fixture
def spawn(tmp_path):
    """Start a stand-in server outside the test's process group; kill leftovers."""
    processes = []

    def start(args, cwd, **env):
        ready = tmp_path / f"ready-{len(processes)}"
        process = subprocess.Popen(
            args, cwd=cwd, env={**os.environ, "NOVA_TEST_READY": str(ready), **env},
            start_new_session=True,
        )
        # Reap promptly so an exited stand-in never lingers as a zombie.
        threading.Thread(target=process.wait, daemon=True).start()
        processes.append(process)
        assert _wait_for(ready.exists), "stand-in server did not start"
        return process

    yield start
    for process in processes:
        if process.poll() is None:
            process.kill()


@pytest.fixture
def reap_pids(launcher):
    """Kill processes a fake backend spawned if a launcher failed to stop them."""
    state, _ = launcher
    yield
    for name in ("worker-pid", "cosyvoice-pid", "backend-pid"):
        path = state / name
        if path.exists():
            try:
                os.kill(int(path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def _backend_config(events: str) -> str:
    line = next(line for line in events.splitlines() if line.startswith("uv run python src/server/app.py"))
    return line.split("--config ", 1)[1]


def test_start_all_builds_the_frontend_and_serves_it_from_the_backend(launcher):
    state, run = launcher
    result, events = run(NOVA_START_RAGFLOW="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert " run build" in events
    assert " run dev" not in events
    assert events.index(" run build") < events.index("uv run python src/server/app.py")
    output = result.stdout
    assert "控制台 Local: \x1b[0mhttp://localhost:8010" in output
    assert "數字人舞台 Local: \x1b[0mhttp://localhost:8010/stage.html" in output
    assert ":3000" not in output
    # The stage is loopback-only (docs/adr/0021): a LAN address would answer 403.
    assert "舞台 Network" not in output


def test_start_all_passes_an_absolute_config_resolved_from_the_callers_directory(launcher):
    state, run = launcher
    result, events = run("start-all.sh", "../config/config.yaml",
                         cwd=run.project / "scripts", NOVA_START_RAGFLOW="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _backend_config(events) == str(run.project / "config/config.yaml")
    assert (state / "npm-config").read_text() == str(run.project / "config/config.yaml")


def test_start_backend_resolves_the_config_before_changing_directory(launcher):
    state, run = launcher
    result, events = run("start-backend.sh", "../config/config.yaml", cwd=run.project / "scripts")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _backend_config(events) == str(run.project / "config/config.yaml")


def test_start_frontend_builds_by_default_and_points_at_the_backend(launcher):
    state, run = launcher
    result, events = run("start-frontend.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert " run build" in events
    assert " run dev" not in events
    assert "http://localhost:8010" in result.stdout
    assert ":3000" not in result.stdout


def test_start_frontend_dev_server_is_loopback_only_and_reads_the_given_config(launcher):
    state, run = launcher
    result, events = run("start-frontend.sh", "--dev", "config/config.yaml")
    assert result.returncode == 0, result.stdout + result.stderr
    assert " run dev" in events
    assert " run build" not in events
    assert (state / "npm-config").read_text() == str(run.project / "config/config.yaml")
    assert "http://127.0.0.1:3000" in result.stdout


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


def test_docker_authentication_failure_skips_ragflow_but_starts_the_avatar(launcher):
    state, run = launcher
    (state / "sudo-denied").touch()
    result, events = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert " up" not in events
    assert " down" not in events
    assert (state / "backend").exists()
    assert "sudo" in result.stdout + result.stderr
    assert "RAGFlow 管理頁 Local" not in result.stdout


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


@pytest.mark.parametrize("failure", ["api-unavailable", "compose-fails"])
def test_ragflow_startup_failure_is_stopped_and_the_avatar_still_starts(launcher, failure):
    state, run = launcher
    (state / "docker-ready").touch()
    (state / failure).touch()
    result, events = run()
    assert result.returncode == 0, result.stdout + result.stderr
    # The partly started RAGFlow is taken down before the backend starts.
    assert " down" in events
    assert events.index(" down") < events.index("uv run python src/server/app.py")
    assert not (state / "containers").exists()
    assert (state / "backend").exists()
    assert "RAGFlow 管理頁 Local" not in result.stdout


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


# Each launcher clears its own port: (script, args, port, stand-in path in a checkout, cwd).
PORT_OWNERS = [
    ("start-all.sh", ("config/config.yaml",), 8010, "src/server/app.py", "."),
    ("start-backend.sh", (), 8010, "src/server/app.py", "."),
    ("start-frontend.sh", ("--dev",), 3000, "web/node_modules/.bin/vite", "web"),
]


def _stand_in_args(checkout: Path, relative: str) -> list[str]:
    # The backend runs as `python src/server/app.py` from the project root;
    # Vite runs as `node <web>/node_modules/.bin/vite`.
    if relative == "src/server/app.py":
        return [sys.executable, relative, "--config", "config/config.yaml"]
    return [sys.executable, str(checkout / relative)]


def _started(events: str, port: int) -> bool:
    return (" run dev" if port == 3000 else "uv run python src/server/app.py") in events


@pytest.mark.parametrize("script,args,port,relative,cwd", PORT_OWNERS)
def test_launchers_refuse_to_stop_a_listener_from_another_program(
    launcher, spawn, tmp_path, script, args, port, relative, cwd,
):
    state, run = launcher
    # Same command line, but another checkout: not this Nova instance.
    other = tmp_path / "other-checkout"
    _write_fake_server(other / relative)
    term = tmp_path / "term"
    foreign = spawn(_stand_in_args(other, relative), cwd=other / cwd,
                    NOVA_TEST_TERM_MARKER=str(term))
    (state / f"listen-{port}").write_text(str(foreign.pid))
    result, events = run(script, *args, NOVA_START_RAGFLOW="0")
    assert result.returncode != 0
    assert not _started(events, port)
    assert _alive(foreign.pid)
    assert not term.exists()
    assert str(foreign.pid) in result.stdout + result.stderr


@pytest.mark.parametrize("script,args,port,relative,cwd", PORT_OWNERS)
def test_launchers_stop_a_stale_nova_listener_gracefully(
    launcher, spawn, tmp_path, script, args, port, relative, cwd,
):
    state, run = launcher
    project = run.project
    term = tmp_path / "term"
    stale = spawn(_stand_in_args(project, relative), cwd=project / cwd,
                  NOVA_TEST_TERM_MARKER=str(term))
    (state / f"listen-{port}").write_text(str(stale.pid))
    result, events = run(script, *args, NOVA_START_RAGFLOW="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert term.exists(), "stale server should get SIGTERM first"
    assert _wait_for(lambda: not _alive(stale.pid), timeout=2)
    assert _started(events, port)


def test_stale_backend_ignoring_sigterm_is_killed_after_the_shared_grace(launcher, spawn, tmp_path):
    state, run = launcher
    project = run.project
    term = tmp_path / "term"
    stale = spawn(_stand_in_args(project, "src/server/app.py"), cwd=project,
                  NOVA_TEST_TERM_MARKER=str(term), NOVA_TEST_IGNORE_TERM="1")
    (state / "listen-8010").write_text(str(stale.pid))
    started = time.monotonic()
    result, events = run("start-backend.sh", NOVA_STOP_GRACE_SECONDS="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert term.exists()
    assert _wait_for(lambda: not _alive(stale.pid), timeout=2)
    assert _started(events, 8010)
    assert time.monotonic() - started < 15


def test_start_all_stops_stale_cosyvoice_of_this_checkout_only(launcher, spawn, tmp_path):
    _, run = launcher
    project = run.project
    ours = spawn([sys.executable, str(project / "scripts/cosyvoice_fastapi_server.py")], cwd=project)
    other = tmp_path / "other-checkout"
    _write_fake_server(other / "scripts/cosyvoice_fastapi_server.py")
    theirs = spawn([sys.executable, str(other / "scripts/cosyvoice_fastapi_server.py")], cwd=other)
    result, _ = run(NOVA_START_RAGFLOW="0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _wait_for(lambda: not _alive(ours.pid), timeout=2)
    assert _alive(theirs.pid)


def test_start_all_reaps_the_backend_group_and_cosyvoice_when_the_backend_exits(launcher, reap_pids):
    state, run = launcher
    (state / "spawn-children").touch()
    result, _ = run(NOVA_START_RAGFLOW="0")
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("worker-pid", "cosyvoice-pid"):
        pid = int((state / name).read_text())
        assert _wait_for(lambda: not _alive(pid), timeout=2), name


def test_start_all_stops_the_whole_backend_group_and_cosyvoice_when_stopped(launcher, reap_pids):
    state, run = launcher
    (state / "spawn-children").touch()
    (state / "backend-seconds").write_text("60")
    launcher_process = run.start(NOVA_START_RAGFLOW="0")
    try:
        assert _wait_for(lambda: (state / "cosyvoice-pid").exists(), timeout=15)
        time.sleep(0.5)
        # The backend leads its own process group, so the launcher's cleanup
        # reaches every process in it rather than only the leader.
        backend = int((state / "backend-pid").read_text())
        assert os.getpgid(backend) == backend
        assert os.getpgid(launcher_process.pid) != backend
        launcher_process.send_signal(signal.SIGTERM)
        output, _ = launcher_process.communicate(timeout=30)
    finally:
        if launcher_process.poll() is None:
            launcher_process.kill()
    assert launcher_process.returncode == 143, output
    for name in ("backend-pid", "worker-pid", "cosyvoice-pid"):
        pid = int((state / name).read_text())
        assert _wait_for(lambda: not _alive(pid), timeout=2), name


def _post_musetalk(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / ".venv").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "scripts/post_musetalk_install.sh", project / "scripts")
    other = tmp_path / "other-venv/lib/python3.10/site-packages/mmdet/__init__.py"
    other.parent.mkdir(parents=True)
    other.write_text("mmcv_maximum_version = '2.1.0'\n")
    result = subprocess.run(
        ["bash", str(project / "scripts/post_musetalk_install.sh")],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
        env={**os.environ, "VIRTUAL_ENV": str(tmp_path / "other-venv")},
    )
    return other, result


def test_post_musetalk_install_patches_the_project_venv_not_the_active_one(tmp_path):
    init = tmp_path / "project/.venv/lib/python3.10/site-packages/mmdet/__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text("mmcv_maximum_version = '2.1.0'\n")
    other, result = _post_musetalk(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert init.read_text() == "mmcv_maximum_version = '2.2.1'\n"
    assert other.read_text() == "mmcv_maximum_version = '2.1.0'\n"


def test_post_musetalk_install_fails_when_mmdet_is_missing(tmp_path):
    other, result = _post_musetalk(tmp_path)
    assert result.returncode != 0
    assert "mmdet" in result.stdout + result.stderr
    assert other.read_text() == "mmcv_maximum_version = '2.1.0'\n"
