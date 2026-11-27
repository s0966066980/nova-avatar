# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""CI runs only the tests a change can affect."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "select_tests", Path(__file__).resolve().parents[1] / "scripts" / "select-tests.py")
select_tests = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(select_tests)
select = select_tests.select


def test_an_stt_change_does_not_run_the_tts_or_rendering_tests():
    assert select(["services/stt/nova_stt/engines/whisper.py"]) == ["core/tests", "services/stt/tests"]


def test_each_layer_runs_its_own_tests_and_the_integration_tests():
    assert select(["services/tts/nova_tts/factory.py"]) == ["core/tests", "services/tts/tests"]
    assert select(["avatar/nova_render/base.py"]) == ["avatar/tests", "core/tests"]
    assert select(["services/llm/nova_llm/handoff.py", "services/stt/x.py"]) == [
        "core/tests", "services/llm/tests", "services/stt/tests"]


def test_shared_inputs_run_everything():
    for name in ("contracts/nova_contracts/llm.py", "pyproject.toml", "uv.lock", "conftest.py",
                 "core/nova_core/server/app.py", ".github/workflows/ci.yml", "scripts/start-all.sh"):
        assert select([name]) is None, name


def test_docs_and_the_frontend_run_no_python_tests():
    assert select(["README.md", "docs/adr/0001.md", "web/src/app.js", "services/tts/README.md"]) == []


def test_an_unknown_location_is_not_skipped():
    assert select(["somewhere/new.py"]) is None
