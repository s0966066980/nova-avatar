# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The Matcha training venv setup and its checkpoint download, with no network."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import matcha_base_weights as weights

pytestmark = pytest.mark.runtime

ROOT = Path(__file__).resolve().parents[3]
CONTENT = b"fake matcha checkpoint"


@pytest.fixture
def fake_checkpoint(monkeypatch):
    """Pin the module to ``CONTENT`` so the real 75 MB file is never needed."""
    monkeypatch.setattr(weights, "SHA256", hashlib.sha256(CONTENT).hexdigest())


def _write_download(calls):
    def download(url, destination):
        calls.append(url)
        destination.write_bytes(CONTENT)
    return download


def test_checkpoint_is_pinned_to_a_commit_and_a_hash():
    assert len(weights.SHA256) == 64
    assert weights.REVISION in weights.URL
    assert "master" not in weights.URL
    assert weights.URL.startswith("https://")


def test_ensure_downloads_a_missing_checkpoint_and_records_where_it_came_from(tmp_path, fake_checkpoint):
    calls = []
    path = weights.ensure(tmp_path / "base", download=_write_download(calls))
    assert calls == [weights.URL]
    assert path.read_bytes() == CONTENT
    assert not list((tmp_path / "base").glob("*.part"))
    provenance = (tmp_path / "base" / weights.PROVENANCE_NAME).read_text(encoding="utf-8")
    assert weights.SHA256 in provenance
    assert weights.LICENSE_FIELD in provenance
    assert "Research / Non-commercial" in provenance


def test_ensure_does_not_download_an_intact_checkpoint_again(tmp_path, fake_checkpoint):
    weights.ensure(tmp_path, download=_write_download([]))
    calls = []
    weights.ensure(tmp_path, download=_write_download(calls))
    assert calls == []


def test_ensure_discards_a_download_with_the_wrong_hash(tmp_path, fake_checkpoint):
    def tampered(url, destination):
        destination.write_bytes(b"something else")

    with pytest.raises(SystemExit, match="discarded"):
        weights.ensure(tmp_path, download=tampered)
    assert list(tmp_path.iterdir()) == []


def test_ensure_discards_a_partial_file_when_the_download_fails(tmp_path, fake_checkpoint):
    def broken(url, destination):
        destination.write_bytes(b"half")
        raise ConnectionError("dropped")

    with pytest.raises(ConnectionError):
        weights.ensure(tmp_path, download=broken)
    assert list(tmp_path.iterdir()) == []


def test_ensure_refuses_to_replace_an_altered_checkpoint(tmp_path, fake_checkpoint):
    altered = tmp_path / weights.FILE_NAME
    altered.write_bytes(b"edited by hand")
    calls = []
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        weights.ensure(tmp_path, download=_write_download(calls))
    assert calls == []
    assert altered.read_bytes() == b"edited by hand"


def test_verify_reports_missing_and_altered_files(tmp_path, fake_checkpoint):
    assert weights.verify(tmp_path).endswith("(missing)")
    (tmp_path / weights.FILE_NAME).write_bytes(b"x")
    assert weights.verify(tmp_path).endswith("(sha256 mismatch)")
    (tmp_path / weights.FILE_NAME).write_bytes(CONTENT)
    assert weights.verify(tmp_path) is None


def test_fetch_refuses_plain_http(tmp_path):
    with pytest.raises(ValueError, match="non-https"):
        weights.fetch("http://example.invalid/model.bin", tmp_path / "model.bin")


def test_dependency_files_keep_heavy_and_copyleft_packages_out():
    pinned = (ROOT / "integrations/matcha-train/requirements.txt").read_text(encoding="utf-8")
    names = {line.split("==")[0].lower() for line in pinned.splitlines() if "==" in line and not line.startswith(" ")}
    assert {"lightning", "diffusers", "conformer", "numpy", "hydra-core"} <= names
    # torch comes from the variant-specific index; the rest are matcha-tts metadata we skip on purpose.
    assert not names & {"torch", "torchaudio", "gradio", "phonemizer", "hydra-optuna-sweeper", "notebook"}
    matcha = (ROOT / "integrations/matcha-train/matcha-tts.txt").read_text(encoding="utf-8")
    assert "matcha-tts==0.0.7.2" in matcha
    assert "--hash=sha256:" in matcha


# --- services/tts/scripts/setup-matcha-train.sh, with stand-ins for uv and the venv's python ---

FAKE_UV = """#!/bin/bash
echo "uv $*" >> "$NOVA_TEST_LOG"
if [ "$1" = "venv" ]; then
    mkdir -p "${@: -1}/bin"
    cp "$NOVA_TEST_PYTHON" "${@: -1}/bin/python"
    chmod +x "${@: -1}/bin/python"
fi
"""
FAKE_PYTHON = """#!/bin/bash
echo "python CUDA=[${CUDA_VISIBLE_DEVICES-unset}] $*" >> "$NOVA_TEST_LOG"
"""


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "services/tts/scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "services/tts/scripts/setup-matcha-train.sh", root / "services/tts/scripts")
    shutil.copytree(ROOT / "integrations/matcha-train", root / "integrations/matcha-train")
    (root / ".venv").mkdir()
    (root / ".venv/marker").write_text("main venv")
    return root


@pytest.fixture
def run_setup(project, tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in (("uv", FAKE_UV), ("python-stub", FAKE_PYTHON)):
        (fake_bin / name).write_text(body)
        (fake_bin / name).chmod(0o755)
    log = tmp_path / "log"
    log.touch()

    def run(**env):
        return subprocess.run(
            ["bash", str(project / "services/tts/scripts/setup-matcha-train.sh")],
            capture_output=True, text=True, timeout=30, cwd=tmp_path,
            env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "NOVA_TEST_LOG": str(log),
                 "NOVA_TEST_PYTHON": str(fake_bin / "python-stub"), **env},
        )

    return run, log


def test_setup_installs_into_local_matcha_train_and_never_touches_the_main_venv(project, run_setup):
    run, log = run_setup
    result = run(CUDA_VISIBLE_DEVICES="0")
    assert result.returncode == 0, result.stdout + result.stderr
    venv = project / ".local/matcha-train/venv"
    lines = log.read_text().splitlines()
    assert lines[0] == f"uv venv --python 3.10 {venv}"
    torch = lines[1]
    assert "https://download.pytorch.org/whl/cu124" in torch and "torch==2.5.0" in torch
    assert f"-r {project}/integrations/matcha-train/requirements.txt" in lines[2]
    assert "--no-deps --require-hashes" in lines[3] and lines[3].endswith("matcha-tts.txt")
    assert all(str(project / ".venv") not in line for line in lines)
    assert (project / ".venv/marker").read_text() == "main venv"
    # Checkpoint download, then the check against it with the GPU hidden.
    assert lines[4] == f"python CUDA=[0] -I {project}/services/tts/scripts/matcha_base_weights.py --dir {project}/.local/matcha-base"
    assert lines[5] == (
        f"python CUDA=[] -I {project}/services/tts/scripts/matcha_train_env_check.py "
        f"--checkpoint {project}/.local/matcha-base/pytorch_model_sherpa.bin"
    )


def test_setup_can_install_the_cpu_build_of_torch(run_setup):
    run, log = run_setup
    assert run(MATCHA_TRAIN_TORCH="cpu").returncode == 0
    assert "https://download.pytorch.org/whl/cpu" in log.read_text()
    assert "cu124" not in log.read_text()


def test_setup_is_repeatable_and_keeps_an_existing_venv(run_setup):
    run, log = run_setup
    assert run().returncode == 0
    log.write_text("")
    assert run().returncode == 0
    assert "uv venv" not in log.read_text()


def test_setup_rejects_an_unknown_torch_variant_before_installing_anything(run_setup):
    run, log = run_setup
    result = run(MATCHA_TRAIN_TORCH="rocm")
    assert result.returncode != 0
    assert "cu124" in result.stderr
    assert log.read_text() == ""


def test_setup_requires_uv(project, tmp_path):
    only_bash = tmp_path / "only-bash"
    only_bash.mkdir()
    for tool in ("bash", "dirname"):
        (only_bash / tool).symlink_to(shutil.which(tool))
    result = subprocess.run(
        [str(only_bash / "bash"), str(project / "services/tts/scripts/setup-matcha-train.sh")],
        capture_output=True, text=True, timeout=30, env={"PATH": str(only_bash)},
    )
    assert result.returncode != 0
    assert "uv" in result.stderr
    assert not (project / ".local").exists()
