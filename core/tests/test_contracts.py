# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Rules every layer contract in nova_contracts follows (ticket 07)."""
from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

import nova_contracts
from nova_contracts.http import HttpApi
from src.server.reply_streaming.turn import TurnContext

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_openapi.py"


def layer_apis() -> dict[str, HttpApi]:
    """Every contract module that declares a loopback HTTP API, by module name."""
    apis = {}
    for module in pkgutil.iter_modules(nova_contracts.__path__):
        api = getattr(importlib.import_module(f"nova_contracts.{module.name}"), "HTTP_API", None)
        if api is not None:
            apis[module.name] = api
    return apis


def test_stt_declares_a_loopback_http_api():
    assert "stt" in layer_apis()


@pytest.mark.parametrize("layer", sorted(layer_apis()))
def test_each_service_method_is_exactly_one_http_operation(layer):
    api = layer_apis()[layer]
    methods = {name for name, _ in inspect.getmembers(api.service, inspect.isfunction)
               if not name.startswith("_")}

    assert sorted(op.operation_id for op in api.operations) == sorted(methods)


def test_the_stt_openapi_posts_audio_and_returns_a_transcription():
    from nova_contracts.http import openapi_document

    document = openapi_document(layer_apis()["stt"])
    transcribe = document["paths"]["/transcribe"]["post"]

    assert document["info"]["version"] == nova_contracts.CONTRACT_VERSION
    assert "audio/wav" in transcribe["requestBody"]["content"]
    assert transcribe["parameters"][0]["name"] == "language"
    assert transcribe["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Transcription"}
    assert set(document["paths"]) == {"/health", "/engine", "/prepare", "/transcribe"}


def test_the_committed_openapi_documents_are_current():
    result = subprocess.run([sys.executable, str(GENERATOR), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_openapi_check_fails_on_a_stale_or_missing_document(tmp_path):
    def check():
        return subprocess.run([sys.executable, str(GENERATOR), "--check", "--out", str(tmp_path)],
                              capture_output=True, text=True, check=False)

    assert check().returncode == 1  # missing
    subprocess.run([sys.executable, str(GENERATOR), "--out", str(tmp_path)], check=True)
    assert check().returncode == 0
    stale = tmp_path / "stt.json"
    document = json.loads(stale.read_text("utf-8"))
    document["paths"].pop("/prepare")
    stale.write_text(json.dumps(document), "utf-8")
    result = check()
    assert result.returncode == 1
    assert "stt.json" in result.stdout + result.stderr


def test_a_playable_fragment_carries_the_core_turn_identity_to_tts():
    from nova_contracts.tts import PlayableFragment

    envelope = TurnContext(turn_id="turn-1", generation=3).envelope(stage="tts", sequence=2)

    fragment = PlayableFragment(envelope=envelope, text="你好。", estimated_seconds=0.6)

    assert (fragment.envelope.turn_id, fragment.envelope.generation,
            fragment.envelope.sequence) == ("turn-1", 3, 2)
    assert fragment.fragment_id == "turn-1:2"


@pytest.mark.parametrize("text, seconds", [("   ", 0.5), ("你好。", -1.0)])
def test_a_playable_fragment_needs_text_and_a_non_negative_duration(text, seconds):
    from nova_contracts.tts import FragmentEnvelope, PlayableFragment

    envelope = FragmentEnvelope(turn_id="turn-1", generation=0, sequence=0)
    with pytest.raises(ValidationError):
        PlayableFragment(envelope=envelope, text=text, estimated_seconds=seconds)


def test_the_contracts_package_depends_only_on_pydantic():
    import ast
    import re

    project = (ROOT / "contracts" / "pyproject.toml").read_text("utf-8")
    declared = re.search(r"(?ms)^dependencies = \[(.*?)\]", project).group(1)
    assert re.findall(r'"([A-Za-z0-9_.-]+)', declared) == ["pydantic"]
    imported = set()
    for path in (ROOT / "contracts" / "nova_contracts").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
    # numpy appears only under TYPE_CHECKING, for AudioSink's annotations.
    third_party = imported - set(sys.stdlib_module_names) - {"nova_contracts"}
    assert third_party <= {"pydantic", "numpy"}
