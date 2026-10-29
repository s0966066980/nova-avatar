# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Downloaded tools, weights, images, and models are pinned and verified."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import textwrap

import pytest

from scripts import musetalk_weights, ragflow_prepare
from scripts.ragflow_validate import EXPECTED_SERVICES, RAGFLOW_IMAGE, validate

ROOT = Path(__file__).resolve().parents[1]
SETUP_ENV = ROOT / "scripts" / "setup-env.sh"
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")


def _fake_bin(directory: Path, name: str, body: str) -> None:
    script = directory / name
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    script.chmod(0o755)


# --- uv installer ---------------------------------------------------------


def _uv_archive(target: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in ("uv", "uvx"):
            data = b"#!/bin/sh\necho 'uv 0.0.0-test'\n"
            info = tarfile.TarInfo(f"uv-{target}/{name}")
            info.size, info.mode = len(data), 0o755
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _install_uv(tmp_path: Path, expected_sha: str | None):
    """Source setup-env.sh and run only its uv installer with a fake download."""
    target = "x86_64-unknown-linux-gnu"
    payload = tmp_path / "payload.tar.gz"
    payload.write_bytes(_uv_archive(target))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_bin(bin_dir, "curl", f"""\
        import shutil, sys
        from pathlib import Path
        args = sys.argv[1:]
        Path({str(tmp_path / 'curl.log')!r}).write_text(" ".join(args))
        shutil.copyfile({str(payload)!r}, args[args.index("-o") + 1])
    """)
    _fake_bin(bin_dir, "uname", "print('x86_64')\n")
    home = tmp_path / "home"
    home.mkdir()
    override = "" if expected_sha is None else f"UV_SHA256[{target}]={expected_sha}; "
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(SETUP_ENV))}; {override}install_uv"],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home)},
        capture_output=True, text=True, timeout=30,
    )
    return result, home / ".local" / "bin" / "uv", (tmp_path / "curl.log")


def test_setup_env_does_not_pipe_a_remote_installer_into_a_shell():
    text = SETUP_ENV.read_text(encoding="utf-8")
    assert not re.search(r"curl[^\n|]*\|\s*(ba)?sh", text)
    assert re.search(r'^UV_VERSION_PIN="\d+\.\d+\.\d+"$', text, re.M)
    pins = re.findall(r"\[(\S+-linux-gnu)\]=([0-9a-f]+)", text)
    assert {target for target, _ in pins} == {"x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"}
    assert all(HEX64.fullmatch(value) for _, value in pins)


def test_uv_installer_rejects_a_release_archive_with_the_wrong_checksum(tmp_path):
    result, uv, curl_log = _install_uv(tmp_path, expected_sha=None)
    assert result.returncode != 0
    assert "sha256" in (result.stdout + result.stderr).lower()
    assert not uv.exists()
    pinned = re.search(r'^UV_VERSION_PIN="(.+)"$', SETUP_ENV.read_text(encoding="utf-8"), re.M)[1]
    assert f"releases/download/{pinned}/uv-x86_64-unknown-linux-gnu.tar.gz" in curl_log.read_text()


def test_uv_installer_installs_the_verified_release(tmp_path):
    digest = hashlib.sha256(_uv_archive("x86_64-unknown-linux-gnu")).hexdigest()
    result, uv, _ = _install_uv(tmp_path, expected_sha=digest)
    assert result.returncode == 0, result.stderr
    assert os.access(uv, os.X_OK)
    assert uv.with_name("uvx").exists()


def test_setup_env_packages_outside_the_lock_are_pinned():
    text = SETUP_ENV.read_text(encoding="utf-8")
    specs = []
    for line in text.splitlines():
        match = re.search(r"(?:uv pip install|mim install)\s+(.*)$", line)
        if not match:
            continue
        for token in shlex.split(match[1]):
            if token.startswith("-") or token.startswith(("$", "src/", '"')) or "/" in token:
                continue
            specs.append(token)
    assert specs, "expected extra packages in setup-env.sh"
    unpinned = [spec for spec in specs if not re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*", spec)]
    assert unpinned == []


# --- MuseTalk weights -------------------------------------------------------


def test_every_weight_source_has_a_commit_and_file_checksums():
    assert musetalk_weights.MODELS
    for source in musetalk_weights.MODELS:
        assert HEX40.fullmatch(source.revision), source.repo
        assert source.files
        assert all(HEX64.fullmatch(digest) for digest in source.files.values()), source.repo


def test_download_passes_the_pinned_revision(tmp_path):
    calls = []
    musetalk_weights.download(tmp_path, snapshot=lambda repo, **kwargs: calls.append((repo, kwargs)))
    assert [repo for repo, _ in calls] == [source.repo for source in musetalk_weights.MODELS]
    for (_, kwargs), source in zip(calls, musetalk_weights.MODELS):
        assert kwargs["revision"] == source.revision
        assert kwargs["allow_patterns"] == sorted(source.files)
        assert Path(kwargs["local_dir"]) == tmp_path / source.local_dir


def _source(tmp_path, content: bytes):
    return musetalk_weights.WeightSource(
        "example/model", "0" * 40, "models/example",
        {"weights.bin": hashlib.sha256(content).hexdigest()},
    )


def test_verify_rejects_tampered_and_missing_weights(tmp_path):
    source = _source(tmp_path, b"expected weights")
    weights = tmp_path / "models/example/weights.bin"
    assert musetalk_weights.verify(tmp_path, [source]) == ["models/example/weights.bin (missing)"]
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"tampered weights")
    assert musetalk_weights.verify(tmp_path, [source]) == ["models/example/weights.bin (sha256 mismatch)"]
    weights.write_bytes(b"expected weights")
    assert musetalk_weights.verify(tmp_path, [source]) == []


def test_main_exits_non_zero_when_verification_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(musetalk_weights, "MODELS", (_source(tmp_path, b"x"),))
    with pytest.raises(SystemExit) as raised:
        musetalk_weights.main(["--check", "--root", str(tmp_path)])
    assert "weights.bin" in str(raised.value)


def test_download_script_delegates_to_the_pinned_module():
    text = (ROOT / "scripts/download_musetalk_weights.sh").read_text(encoding="utf-8")
    assert "scripts/musetalk_weights.py" in text
    assert "snapshot_download" not in text


# --- RAGFlow image and embedding model -------------------------------------


def _compose_plan(image: str) -> dict:
    services = {name: {"networks": {"ragflow": None}, "mem_limit": "1024", "cpus": 1} for name in EXPECTED_SERVICES}
    services["ragflow-cpu"]["image"] = image
    services["ragflow-cpu"]["ports"] = [
        {"host_ip": "127.0.0.1", "published": "8088", "target": 80},
        {"host_ip": "127.0.0.1", "published": "9380", "target": 9380},
    ]
    return {"services": services}


def test_ragflow_image_is_pinned_by_digest_everywhere():
    assert re.fullmatch(r"infiniflow/ragflow:v[\d.]+@sha256:[0-9a-f]{64}", RAGFLOW_IMAGE)
    assert ragflow_prepare.RAGFLOW_IMAGE == RAGFLOW_IMAGE
    validate(_compose_plan(RAGFLOW_IMAGE))
    with pytest.raises(ValueError):
        validate(_compose_plan(RAGFLOW_IMAGE.split("@", 1)[0]))


def test_existing_managed_env_is_moved_to_the_pinned_image_without_touching_secrets(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{ragflow_prepare.MANAGED_MARKER}\nMYSQL_PASSWORD=keep-me\n"
        "RAGFLOW_IMAGE=infiniflow/ragflow:v0.27.2\nTZ=Asia/Taipei\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ragflow_prepare, "ENV_FILE", env_file)
    monkeypatch.setattr(ragflow_prepare, "_stock_env", lambda: "")
    ragflow_prepare.prepare()
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert f"RAGFLOW_IMAGE={RAGFLOW_IMAGE}" in lines
    assert "MYSQL_PASSWORD=keep-me" in lines
    assert env_file.stat().st_mode & 0o777 == 0o600


@pytest.fixture
def ragflow_pull(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/ragflow.sh", project / "scripts/ragflow.sh")
    pinned = re.search(r'^BGE_M3_BLOB="sha256-([0-9a-f]{64})"$',
                       (ROOT / "scripts/ragflow.sh").read_text(encoding="utf-8"), re.M)[1]
    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_bin(bin_dir, "ollama", f"""\
        import sys
        from pathlib import Path
        state = Path({str(state)!r})
        args = sys.argv[1:]
        with (state / "events").open("a") as events:
            events.write(" ".join(args) + "\\n")
        if args[0] == "pull":
            (state / "blob").write_text((state / "registry").read_text())
        elif args[0] == "show":
            if not (state / "blob").exists():
                sys.exit(1)
            print("# Modelfile generated by ollama show")
            print("FROM /models/blobs/sha256-" + (state / "blob").read_text())
    """)

    def run(*, installed=None, registry=pinned):
        if installed is not None:
            (state / "blob").write_text(installed)
        (state / "registry").write_text(registry)
        result = subprocess.run(
            ["bash", str(project / "scripts/ragflow.sh"), "pull-model"],
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            capture_output=True, text=True, timeout=15,
        )
        events = (state / "events").read_text() if (state / "events").exists() else ""
        return result, events

    return pinned, run


def test_bge_m3_pull_is_verified_against_the_pinned_blob(ragflow_pull):
    pinned, run = ragflow_pull
    result, events = run()
    assert result.returncode == 0, result.stderr
    assert "pull bge-m3" in events


def test_bge_m3_pull_fails_when_the_registry_serves_other_weights(ragflow_pull):
    _, run = ragflow_pull
    result, _ = run(registry="f" * 64)
    assert result.returncode != 0
    assert "bge-m3" in result.stderr


def test_existing_bge_m3_with_other_weights_is_rejected_without_pulling(ragflow_pull):
    _, run = ragflow_pull
    result, events = run(installed="e" * 64)
    assert result.returncode != 0
    assert "pull" not in events.split()


# --- Local certificates -----------------------------------------------------


@pytest.fixture
def certs(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/create_ssl_certs.sh", project / "scripts/create_ssl_certs.sh")
    log = tmp_path / "calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Only the tools the script needs, so a host-installed mkcert cannot leak in.
    for tool in ("bash", "mkdir", "mktemp", "chmod", "mv", "rm", "dirname", "cat", "cp", "hostname"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    writer = textwrap.dedent(f"""\
        import sys
        from pathlib import Path
        args = sys.argv[1:]
        with open({str(log)!r}, "a") as calls:
            calls.write(Path(sys.argv[0]).name + " " + " ".join(args) + "\\n")
        def write(flag):
            Path(args[args.index(flag) + 1]).write_text("pem")
    """)
    _fake_bin(bin_dir, "openssl", writer + 'write("-keyout"); write("-out")\n')
    mkcert_body = writer + textwrap.dedent(f"""\
        if args == ["-CAROOT"]:
            print({str(tmp_path / 'caroot')!r})
        else:
            write("-key-file"); write("-cert-file")
    """)

    def run(*, mkcert: bool, **env):
        if mkcert:
            _fake_bin(bin_dir, "mkcert", mkcert_body)
        result = subprocess.run(
            [str(bin_dir / "bash"), str(project / "scripts/create_ssl_certs.sh")],
            env={"PATH": str(bin_dir), "HOME": str(tmp_path), **env},
            capture_output=True, text=True, timeout=15,
        )
        calls = log.read_text() if log.exists() else ""
        return result, calls, project / "ssl_certs"

    return run


def test_mkcert_is_preferred_when_available(certs):
    result, calls, certs_dir = certs(mkcert=True)
    assert result.returncode == 0, result.stderr
    assert "mkcert " in calls and "openssl" not in calls
    mkcert_call = next(line for line in calls.splitlines() if "-cert-file" in line)
    assert {"localhost", "127.0.0.1", "::1"} <= set(mkcert_call.split())
    assert (certs_dir / "localhost.crt").is_file()
    assert (certs_dir / "localhost.key").stat().st_mode & 0o777 == 0o600
    assert "rootCA.pem" in result.stdout


def test_self_signed_fallback_without_mkcert(certs):
    result, calls, certs_dir = certs(mkcert=False)
    assert result.returncode == 0, result.stderr
    assert calls.startswith("openssl ")
    assert (certs_dir / "localhost.crt").is_file()


def test_self_signed_can_be_forced_even_with_mkcert(certs):
    result, calls, _ = certs(mkcert=True, NOVA_SSL_SELF_SIGNED="1")
    assert result.returncode == 0, result.stderr
    assert "mkcert" not in calls
