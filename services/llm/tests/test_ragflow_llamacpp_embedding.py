# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""RAGFlow's BGE-M3 embeddings come from a CPU-only llama.cpp server (issue 15)."""
from __future__ import annotations

import configparser
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "integrations/ragflow/nova-ragflow-llamacpp-embedding.service"
LAUNCHER = ROOT / "scripts/ragflow_llamacpp_embedding.sh"


def _fake_bin(directory: Path, name: str, body: str) -> Path:
    script = directory / name
    script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    script.chmod(0o755)
    return script


@pytest.fixture
def launch(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / LAUNCHER.name).write_text(LAUNCHER.read_text())
    gguf = project / "models/ragflow/bge-m3-f16.gguf"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_bin(bin_dir, "docker", 'print("172.17.0.1")\n')
    record = tmp_path / "server.json"
    server = _fake_bin(tmp_path, "llama-server", f"""\
        import json, os, sys
        with open({str(record)!r}, "w") as out:
            json.dump({{"args": sys.argv[1:], "cuda": os.environ.get("CUDA_VISIBLE_DEVICES")}}, out)
    """)

    def run(**env):
        result = subprocess.run(
            ["bash", str(project / "scripts" / LAUNCHER.name)],
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                 "NOVA_RAGFLOW_LLAMA_SERVER": str(server), **env},
            capture_output=True, text=True, timeout=15,
        )
        started = json.loads(record.read_text()) if record.exists() else None
        return result, started

    return gguf, run


def _option(args: list[str], name: str) -> str:
    return args[args.index(name) + 1]


def test_embedding_server_is_cpu_only_and_bound_to_the_docker_bridge(launch):
    gguf, run = launch
    gguf.parent.mkdir(parents=True)
    gguf.write_text("weights")
    result, started = run(CUDA_VISIBLE_DEVICES="0")
    assert result.returncode == 0, result.stderr
    args = started["args"]
    assert started["cuda"] == ""
    assert _option(args, "-ngl") == "0"
    assert _option(args, "--host") == "172.17.0.1"
    assert _option(args, "--port") == "11437"
    assert Path(_option(args, "-m")) == gguf
    assert "--embedding" in args
    assert _option(args, "--pooling") == "cls"
    # BGE-M3 encodes the whole input in one micro-batch.
    assert _option(args, "-c") == _option(args, "-ub") == _option(args, "-b")


def test_embedding_server_refuses_to_start_without_the_verified_gguf(launch):
    _, run = launch
    result, started = run()
    assert result.returncode != 0
    assert "pull-model" in result.stderr
    assert started is None


def test_unit_runs_the_launcher_with_cpu_and_memory_limits():
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(UNIT.read_text())
    service = parser["Service"]
    assert service["ExecStart"].endswith("/scripts/ragflow_llamacpp_embedding.sh")
    assert service["CPUQuota"] == "400%"
    assert service["MemoryMax"] == "4G"
    assert service["NoNewPrivileges"] == "yes"
    assert "GPU" not in parser["Unit"]["Description"]


# --- RAGFlow model configuration ------------------------------------------


def _connection():
    path = ROOT / "scripts/ragflow_connection.py"
    spec = importlib.util.spec_from_file_location("ragflow_connection_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD_ID = "1" * 32
NEW_ID = "2" * 32
OTHER_ID = "3" * 32


class FakeRagflow:
    """In-memory RAGFlow model and dataset API that records every call."""

    def __init__(self, *, check_code=0, retrieval_code=0, defaults=None):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.providers = [{"name": "Ollama"}]
        self.instances: dict[str, list[dict]] = {"Ollama": [{"instance_name": "bge-m3"}]}
        self.models = [{"provider_name": "Ollama", "instance_name": "bge-m3",
                        "name": "bge-m3:latest", "model_id": OLD_ID, "model_type": ["embedding"]}]
        self.datasets = [
            {"id": "a" * 32, "name": "nova_rag", "chunk_count": 1,
             "embedding_model": OLD_ID, "embedding_model_name": "bge-m3:latest@bge-m3@Ollama"},
            {"id": "b" * 32, "name": "other", "chunk_count": 3,
             "embedding_model": OTHER_ID, "embedding_model_name": "nomic-embed-text:latest@bge-m3@Ollama"},
        ]
        self.defaults = defaults if defaults is not None else [
            {"model_type": "embedding", "model_id": OLD_ID}]
        self.check_code = check_code
        self.retrieval_code = retrieval_code

    def __call__(self, key, method, path, body=None):
        self.calls.append((method, path, body))
        route = path.split("?", 1)[0]
        if method == "GET" and route == "/providers":
            return self.providers
        if method == "PUT" and route == "/providers":
            self.providers.append({"name": body["provider_name"]})
            return None
        if route.startswith("/providers/") and route.endswith("/instances"):
            provider = route.split("/")[2]
            if method == "GET":
                return self.instances.get(provider, [])
            self.instances.setdefault(provider, []).append({"instance_name": body["instance_name"]})
            for model in body["model_info"]:
                self.models.append({"provider_name": provider, "instance_name": body["instance_name"],
                                    "name": model["model_name"], "model_id": NEW_ID,
                                    "model_type": model["model_type"]})
            return None
        if method == "GET" and route == "/models":
            return self.models
        if route == "/models/default":
            if method == "GET":
                return {"models": self.defaults}
            self.defaults = [d for d in self.defaults if d["model_type"] != body["model_type"]]
            self.defaults.append({**body, "model_id": NEW_ID})
            return None
        if method == "GET" and route == "/datasets":
            return self.datasets
        if method == "GET" and route.endswith("/documents"):
            return {"docs": [{"id": "d1", "name": "手冊.pdf"}], "total": 1}
        if method == "POST" and route.endswith("/embedding/check"):
            if self.check_code:
                raise RuntimeError("RAGFlow 模型設定失敗")
            return {"summary": {"min_cos_sim": 1.0, "valid": 1}}
        if method == "PUT" and route.startswith("/datasets/"):
            dataset = next(d for d in self.datasets if d["id"] == route.split("/")[2])
            dataset["embedding_model"] = body["embedding_model"]
            return dataset
        if method == "POST" and route == "/retrieval":
            if self.retrieval_code:
                raise RuntimeError("RAGFlow 模型設定失敗")
            return {"chunks": [], "total": 0}
        raise AssertionError(f"unexpected call {method} {path}")

    def mutations(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


@pytest.fixture
def connection(tmp_path, monkeypatch):
    module = _connection()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SHARED_OLLAMA", tmp_path / ".local/ragflow/shared-ollama")
    units: list[list[str]] = []
    monkeypatch.setattr(module.subprocess, "run", lambda args, **_: units.append(args))
    module.units = units
    return module


def test_new_deployment_registers_the_llamacpp_embedding_as_default(connection):
    api = FakeRagflow(defaults=[])
    connection.model_api = api
    connection.configure_embedding("key")
    connection.configure_embedding("key")
    creates = [body for method, path, body in api.calls
               if method == "POST" and path == "/providers/OpenAI-API-Compatible/instances"]
    assert len(creates) == 1
    assert creates[0]["base_url"] == "http://host.docker.internal:11437/v1"
    # RAGFlow's OpenAI client rejects an empty key; the server has no auth.
    assert creates[0]["api_key"] == "x"
    assert creates[0]["model_info"][0]["model_name"] == "bge-m3"
    assert creates[0]["model_info"][0]["model_type"] == ["embedding"]
    assert api.defaults[0]["model_provider"] == "OpenAI-API-Compatible"
    assert api.defaults[0]["model_name"] == "bge-m3"


def test_existing_default_embedding_is_kept_by_connect(connection):
    api = FakeRagflow()
    connection.model_api = api
    connection.configure_embedding("key")
    assert api.defaults == [{"model_type": "embedding", "model_id": OLD_ID}]


def test_switch_backs_up_checks_switches_and_only_then_stops_the_gpu_service(connection, tmp_path):
    api = FakeRagflow()
    connection.model_api = api
    connection.switch_embedding("key")

    backups = list((tmp_path / ".local/ragflow/backups").glob("embedding-switch-*.json"))
    assert len(backups) == 1
    assert backups[0].stat().st_mode & 0o777 == 0o600
    saved = json.loads(backups[0].read_text())
    assert saved["datasets"][0]["embedding_model"] == OLD_ID
    assert saved["documents"]["a" * 32][0]["name"] == "手冊.pdf"
    assert saved["defaults"] == [{"model_type": "embedding", "model_id": OLD_ID}]

    order = [path for _, path in api.mutations()]
    check = order.index(f"/datasets/{'a' * 32}/embedding/check")
    switch = order.index(f"/datasets/{'a' * 32}")
    assert check < switch < order.index("/retrieval")
    assert api.datasets[0]["embedding_model"] == NEW_ID
    # A dataset on another embedding model is never moved to BGE-M3.
    assert api.datasets[1]["embedding_model"] == OTHER_ID
    assert not any("b" * 32 in path for path in order)
    assert next(d for d in api.defaults if d["model_type"] == "embedding")["model_id"] == NEW_ID
    assert connection.units == [
        ["systemctl", "--user", "disable", "--now", "nova-ragflow-embedding.service"]]
    # No document is deleted or re-parsed.
    assert not any(method == "DELETE" or "parse" in path for method, path in api.mutations())


def test_switch_keeps_everything_when_the_vectors_differ(connection):
    api = FakeRagflow(check_code=1)
    connection.model_api = api
    with pytest.raises(RuntimeError):
        connection.switch_embedding("key")
    assert api.datasets[0]["embedding_model"] == OLD_ID
    assert next(d for d in api.defaults if d["model_type"] == "embedding")["model_id"] == OLD_ID
    assert connection.units == []


def test_gpu_service_keeps_running_when_retrieval_fails_after_the_switch(connection):
    api = FakeRagflow(retrieval_code=1)
    connection.model_api = api
    with pytest.raises(RuntimeError):
        connection.switch_embedding("key")
    assert connection.units == []


def test_switch_is_idempotent(connection):
    api = FakeRagflow()
    connection.model_api = api
    connection.switch_embedding("key")
    api.calls.clear()
    connection.switch_embedding("key")
    assert not any(path.startswith("/datasets/") and method == "PUT" for method, path in api.mutations())


def test_ollama_embedding_models_are_not_offered_to_ragflow(connection, monkeypatch):
    added = []

    def api(key, method, path, body=None):
        if method == "GET":
            return {
                "/providers": [{"name": "Ollama"}],
                "/providers/Ollama/instances": [{"instance_name": "nova-chat"}],
                "/providers/Ollama/instances/nova-chat": {"base_url": connection.SHARED_MODEL_URL},
                "/models": [],
            }[path]
        added.append(body["model_name"])

    capabilities = {"bge-m3:latest": ["embedding"], "qwen3.5:4b": ["completion", "vision"]}
    connection.model_api = api
    monkeypatch.setattr(connection, "ollama_api", lambda path, body=None, **_: (
        {"models": [{"name": name} for name in capabilities]} if path == "/api/tags"
        else {"capabilities": capabilities[body["model"]]}))
    connection.sync_models("key")
    assert added == ["qwen3.5:4b"]


def test_unify_refuses_while_a_dataset_still_embeds_with_ollama(connection, monkeypatch):
    api = FakeRagflow()
    connection.model_api = api
    monkeypatch.setattr(connection, "read_key", lambda: "key")
    monkeypatch.setattr(connection, "works", lambda key: True)
    with pytest.raises(RuntimeError, match="switch-embedding"):
        connection.unify_models()
    assert api.mutations() == []
    assert connection.units == []
