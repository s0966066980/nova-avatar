# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Voice-model catalog: which ``models/tts/<id>/`` directories can be chosen."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from nova_tts.voice_models import (
    LABEL_FILE,
    REQUIRED_FILES,
    RULE_FSTS,
    VoiceModelNotFound,
    delete_voice_model,
    list_voice_models,
)

pytestmark = pytest.mark.speech

INSTALL_DOC = Path(__file__).resolve().parents[3] / "docs/guides/voice-models.md"

LABEL = {
    "name": "曉臻（測試）",
    "usage": "Development only",
    "languages": ["zh-TW", "en-US"],
    "source": "fixture distilled for tests",
}


def _voice_model_dir(root: Path, model_id: str, label: dict | None = LABEL) -> Path:
    model_dir = root / model_id
    model_dir.mkdir(parents=True)
    for name in ("model.onnx", "vocos-16khz-univ.onnx", "lexicon.txt", "tokens.txt"):
        (model_dir / name).write_bytes(b"fixture")
    if label is not None:
        (model_dir / "voice.json").write_text(json.dumps(label), encoding="utf-8")
    return model_dir


def test_complete_labelled_directory_is_listed(tmp_path):
    model_dir = _voice_model_dir(tmp_path, "zh-tw-test")

    [model] = list_voice_models(tmp_path)

    assert model.id == "zh-tw-test"
    assert model.name == "曉臻（測試）"
    assert model.usage == "Development only"
    assert model.languages == ("zh-TW", "en-US")
    assert model.source == "fixture distilled for tests"
    assert model.acoustic_model == model_dir / "model.onnx"
    assert model.vocoder == model_dir / "vocos-16khz-univ.onnx"
    assert model.lexicon == model_dir / "lexicon.txt"
    assert model.tokens == model_dir / "tokens.txt"


def test_directory_without_usage_label_is_not_listed_and_the_reason_is_logged(tmp_path, caplog):
    _voice_model_dir(tmp_path, "matcha-icefall-zh-en", label=None)
    _voice_model_dir(tmp_path, "zh-tw-test")

    with caplog.at_level("INFO"):
        models = list_voice_models(tmp_path)

    assert [model.id for model in models] == ["zh-tw-test"]
    assert "matcha-icefall-zh-en" in caplog.text
    assert "voice.json" in caplog.text


@pytest.mark.parametrize(
    "missing", ["model.onnx", "vocos-16khz-univ.onnx", "lexicon.txt", "tokens.txt"]
)
def test_directory_missing_a_required_file_is_not_listed(tmp_path, caplog, missing):
    model_dir = _voice_model_dir(tmp_path, "zh-tw-test")
    (model_dir / missing).unlink()

    with caplog.at_level("INFO"):
        assert list_voice_models(tmp_path) == []

    assert "zh-tw-test" in caplog.text
    assert missing in caplog.text


@pytest.mark.parametrize(
    "label_text",
    [
        "{not json",
        json.dumps(["Development only"]),
        json.dumps({**LABEL, "name": ""}),
        json.dumps({k: v for k, v in LABEL.items() if k != "source"}),
        json.dumps({**LABEL, "usage": "Commercial"}),
        json.dumps({**LABEL, "languages": []}),
        json.dumps({**LABEL, "languages": "zh-TW"}),
    ],
    ids=[
        "malformed",
        "not-an-object",
        "empty-name",
        "no-source",
        "unknown-usage",
        "no-languages",
        "languages-not-a-list",
    ],
)
def test_directory_with_an_invalid_usage_label_is_not_listed(tmp_path, caplog, label_text):
    model_dir = _voice_model_dir(tmp_path, "zh-tw-test")
    (model_dir / "voice.json").write_text(label_text, encoding="utf-8")

    with caplog.at_level("INFO"):
        assert list_voice_models(tmp_path) == []

    assert "zh-tw-test" in caplog.text


@pytest.mark.parametrize("usage", ["Development only", "Research / Non-commercial"])
def test_each_spec_usage_label_is_accepted(tmp_path, usage):
    _voice_model_dir(tmp_path, "zh-tw-test", label={**LABEL, "usage": usage})

    [model] = list_voice_models(tmp_path)

    assert model.usage == usage


def test_rule_fsts_present_in_the_directory_are_part_of_the_voice_model(tmp_path):
    model_dir = _voice_model_dir(tmp_path, "zh-tw-test")
    for name in ("number-zh.fst", "phone-zh.fst"):
        (model_dir / name).write_bytes(b"fixture")

    [model] = list_voice_models(tmp_path)

    assert model.rule_fsts == (model_dir / "phone-zh.fst", model_dir / "number-zh.fst")


def test_missing_root_lists_nothing(tmp_path):
    assert list_voice_models(tmp_path / "absent") == []


def test_only_directories_with_a_safe_id_are_listed(tmp_path, caplog):
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")
    _voice_model_dir(tmp_path, ".hidden")
    _voice_model_dir(tmp_path, "has space")
    _voice_model_dir(tmp_path, "zh-tw-test")

    with caplog.at_level("INFO"):
        models = list_voice_models(tmp_path)

    assert [model.id for model in models] == ["zh-tw-test"]
    assert "has space" in caplog.text


def test_sherpa_onnx_is_a_main_dependency_and_importable():
    """Voice models run on sherpa-onnx; a missing package fails here, never skips."""
    manifest = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text("utf-8"))
    assert any(requirement.startswith("sherpa-onnx") for requirement in manifest["project"]["dependencies"])

    import sherpa_onnx

    assert hasattr(sherpa_onnx, "OfflineTts")


def test_install_doc_voice_json_example_is_a_listable_usage_label(tmp_path):
    """The label people copy from the install doc must be one the catalog accepts."""
    doc = INSTALL_DOC.read_text(encoding="utf-8")
    [example] = re.findall(r"```json\n(.*?)```", doc, re.DOTALL)
    _voice_model_dir(tmp_path, "zh-tw-hsiaochen-edge", json.loads(example))

    [model] = list_voice_models(tmp_path)

    assert model.usage == "Development only"
    assert model.languages == ("zh-TW", "en-US")


def test_install_doc_lists_every_voice_model_file_with_a_sha256():
    doc = INSTALL_DOC.read_text(encoding="utf-8")
    hashes = dict(re.findall(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", doc))

    for name in (*REQUIRED_FILES, *RULE_FSTS):
        assert name in hashes, name
    assert LABEL_FILE in doc


def test_deleting_a_voice_model_moves_it_to_the_recycle_bin(tmp_path):
    _voice_model_dir(tmp_path, "keep-me")
    _voice_model_dir(tmp_path, "drop-me")

    recycled = delete_voice_model("drop-me", tmp_path)

    assert recycled.parent == tmp_path / ".deleted"
    assert (recycled / "model.onnx").is_file()  # moved, not erased
    assert [model.id for model in list_voice_models(tmp_path)] == ["keep-me"]


@pytest.mark.parametrize("voice_id", ["missing", "../outside", "", ".deleted", "x" * 200])
def test_deleting_an_unlisted_voice_model_is_refused(tmp_path, voice_id):
    _voice_model_dir(tmp_path, "keep-me")

    with pytest.raises(VoiceModelNotFound):
        delete_voice_model(voice_id, tmp_path)

    assert [model.id for model in list_voice_models(tmp_path)] == ["keep-me"]
    assert not (tmp_path / ".deleted").exists()


def test_an_incomplete_directory_is_not_deleted_as_a_voice_model(tmp_path):
    _voice_model_dir(tmp_path, "unlabelled", label=None)

    with pytest.raises(VoiceModelNotFound):
        delete_voice_model("unlabelled", tmp_path)

    assert (tmp_path / "unlabelled").is_dir()


def test_a_symlinked_voice_model_is_not_deleted(tmp_path):
    real = _voice_model_dir(tmp_path / "real", "real-model")
    (tmp_path / "linked").symlink_to(real)

    with pytest.raises(VoiceModelNotFound):
        delete_voice_model("linked", tmp_path)

    assert real.is_dir()
