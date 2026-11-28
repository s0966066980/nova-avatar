# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""A model declares its vision projector in a descriptor beside the GGUF."""
from __future__ import annotations

import json
import logging

from nova_llm.model_profile import projector_for, sidecar_path
import pytest

pytestmark = pytest.mark.llm


def _model(folder, name="some-model-Q4.gguf"):
    gguf = folder / name
    gguf.write_bytes(b"GGUF")
    return gguf


def _descriptor(gguf, body):
    sidecar_path(gguf).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")


def test_a_model_without_a_descriptor_is_text_only(tmp_path):
    gguf = _model(tmp_path)
    (tmp_path / "some-model-mmproj.gguf").write_bytes(b"GGUF")  # never guessed from names
    assert projector_for(gguf) is None


def test_the_descriptor_is_named_after_the_model_without_gguf(tmp_path):
    gguf = _model(tmp_path, "Qwen3.5-9B-UD-Q4_K_XL.gguf")
    assert sidecar_path(gguf).name == "Qwen3.5-9B-UD-Q4_K_XL.model.json"


def test_a_descriptor_attaches_the_projector_it_names(tmp_path):
    gguf = _model(tmp_path)
    projector = tmp_path / "vision-mmproj.gguf"
    projector.write_bytes(b"GGUF")
    _descriptor(gguf, {"mmproj": "vision-mmproj.gguf"})
    assert projector_for(gguf) == projector


def test_the_tested_gemma_pairing_is_built_in(tmp_path):
    gguf = _model(tmp_path, "gemma-4-E2B_q4_0-it.gguf")
    assert projector_for(gguf) is None  # projector not installed
    projector = tmp_path / "gemma-4-E2B-it-mmproj.gguf"
    projector.write_bytes(b"GGUF")
    assert projector_for(gguf) == projector


def test_a_descriptor_overrides_the_built_in_pairing(tmp_path):
    gguf = _model(tmp_path, "gemma-4-E2B_q4_0-it.gguf")
    (tmp_path / "gemma-4-E2B-it-mmproj.gguf").write_bytes(b"GGUF")
    _descriptor(gguf, {"mmproj": None})
    assert projector_for(gguf) is None


def test_a_projector_that_is_not_in_the_folder_is_ignored_with_a_warning(tmp_path, caplog):
    gguf = _model(tmp_path)
    _descriptor(gguf, {"mmproj": "missing.gguf"})
    with caplog.at_level(logging.WARNING):
        assert projector_for(gguf) is None
    assert "missing.gguf" in caplog.text


def test_a_descriptor_that_cannot_be_used_leaves_the_model_text_only(tmp_path, caplog):
    gguf = _model(tmp_path)
    (tmp_path / "vision-mmproj.gguf").write_bytes(b"GGUF")
    outside = tmp_path.parent / "elsewhere.gguf"
    outside.write_bytes(b"GGUF")
    for body in (
        "{not json",
        "[]",
        {"mmproj": "vision-mmproj.gguf", "thinking": False},  # unknown field
        {"mmproj": "../elsewhere.gguf"},  # outside the folder
        {"mmproj": str(outside)},
        {"mmproj": "vision-mmproj.bin"},
        {"mmproj": 7},
    ):
        _descriptor(gguf, body)
        assert projector_for(gguf) is None, body
    assert "not used" in caplog.text
