# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Installing a trained voice model into the catalog."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from nova_tts.training import bundle
from nova_tts.training.bundle import BundleError, check_model_name, install_voice_model, new_model_id, source_description
from nova_tts.voice_models import REQUIRED_FILES, VOICE_MODEL_ID, list_voice_models


@pytest.fixture
def staging(tmp_path):
    path = tmp_path / "staging"
    path.mkdir()
    for name in (*REQUIRED_FILES, "number-zh.fst"):
        (path / name).write_bytes(name.encode())
    return path


def test_installed_model_is_listed_with_its_label(staging, tmp_path):
    root = tmp_path / "models-tts"
    target = install_voice_model(
        staging, "trained-1", name="我的聲音", usage="Research / Non-commercial", source=source_description("self-recorded"), root=root
    )
    assert target == root / "trained-1"
    (model,) = list_voice_models(root)
    assert (model.id, model.name, model.usage) == ("trained-1", "我的聲音", "Research / Non-commercial")
    assert model.languages == ("zh-TW", "en-US")
    assert model.source == "Fine-tuned from dengcunqin/matcha_tts_zh_en_20251010; corpus source: self-recorded"
    assert [path.name for path in model.rule_fsts] == ["number-zh.fst"]
    label = json.loads((target / "voice.json").read_text(encoding="utf-8"))
    assert sorted(label) == ["languages", "name", "source", "usage"]


def test_staging_is_left_alone_and_nothing_else_appears_in_the_catalog_directory(staging, tmp_path):
    root = tmp_path / "models-tts"
    install_voice_model(staging, "trained-1", name="x", usage="Development only", source="s", root=root)
    assert staging.is_dir() and not (staging / "voice.json").exists()
    assert [path.name for path in root.iterdir()] == ["trained-1"]


def test_a_failure_while_copying_leaves_no_partial_model(staging, tmp_path, monkeypatch):
    root = tmp_path / "models-tts"

    def broken_copy(source, destination):
        destination.mkdir()
        (destination / "model.onnx").write_bytes(b"half")
        raise OSError("disk full")

    monkeypatch.setattr(bundle.shutil, "copytree", broken_copy)
    with pytest.raises(OSError, match="disk full"):
        install_voice_model(staging, "trained-1", name="x", usage="Development only", source="s", root=root)
    assert list(root.iterdir()) == []
    assert list_voice_models(root) == []


def test_an_existing_directory_is_never_replaced(staging, tmp_path):
    root = tmp_path / "models-tts"
    (root / "trained-1").mkdir(parents=True)
    (root / "trained-1" / "keep.txt").write_text("mine")
    with pytest.raises(BundleError) as caught:
        install_voice_model(staging, "trained-1", name="x", usage="Development only", source="s", root=root)
    assert caught.value.status == 409
    assert (root / "trained-1" / "keep.txt").read_text() == "mine"


def test_an_incomplete_export_is_refused(staging, tmp_path):
    (staging / "model.onnx").unlink()
    with pytest.raises(BundleError, match="model.onnx"):
        install_voice_model(staging, "trained-1", name="x", usage="Development only", source="s", root=tmp_path / "m")


@pytest.mark.parametrize("voice_id", ["../escape", "a/b", ".hidden", "", "x" * 81])
def test_ids_that_are_not_catalog_ids_are_refused(staging, tmp_path, voice_id):
    with pytest.raises(BundleError):
        install_voice_model(staging, voice_id, name="x", usage="Development only", source="s", root=tmp_path / "m")


def test_an_unknown_usage_label_is_refused(staging, tmp_path):
    with pytest.raises(BundleError, match="標示"):
        install_voice_model(staging, "trained-1", name="x", usage="Commercial", source="s", root=tmp_path / "m")


def test_generated_ids_are_valid_and_unique():
    now = datetime(2026, 11, 24, 14, 30, tzinfo=timezone.utc)
    ids = set()
    for _ in range(50):
        new_id = new_model_id(ids, now)
        assert VOICE_MODEL_ID.fullmatch(new_id) and new_id.startswith("trained-20261124-1430-")
        ids.add(new_id)
    assert len(ids) == 50


@pytest.mark.parametrize(
    ("name", "message"),
    [("", "必填"), ("   ", "必填"), (None, "必填"), ("x" * 41, "40"), ("a\x00b", "控制"), ("Alice", "同名"), (" ａｌｉｃｅ ", "同名")],
)
def test_names_are_required_short_and_unique(name, message):
    with pytest.raises(BundleError, match=message):
        check_model_name(name, ["Alice"])


def test_a_valid_name_is_trimmed_and_may_be_forty_characters():
    assert check_model_name("  我的  聲音 ", []) == "我的 聲音"
    assert len(check_model_name("字" * 40, [])) == 40


# --- the sherpa-onnx load check (a fake sherpa_onnx module) -------------------------


@pytest.fixture
def fake_sherpa(monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    module = ModuleType("sherpa_onnx")
    seen = {}
    audio = SimpleNamespace(samples=[0.0] * 16000, sample_rate=16000)

    def namespace(**fields):
        return SimpleNamespace(**fields)

    class Tts:
        def __init__(self, config):
            seen["config"] = config

        def generate(self, text, sid, speed):
            seen["text"] = text
            return audio

    module.OfflineTtsConfig = namespace
    module.OfflineTtsModelConfig = namespace
    module.OfflineTtsMatchaModelConfig = namespace
    module.OfflineTts = Tts
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    return SimpleNamespace(seen=seen, audio=audio)


def test_verify_loads_the_bundle_on_the_cpu_and_returns_the_seconds_synthesised(staging, fake_sherpa):
    from nova_tts.training import verify_bundle

    assert verify_bundle.verify(staging) == 1.0
    config = fake_sherpa.seen["config"]
    assert config.model.provider == "cpu"
    assert config.model.matcha.acoustic_model == str(staging / "model.onnx")
    assert config.rule_fsts == str(staging / "number-zh.fst")


def test_verify_rejects_audio_that_is_not_16_khz_speech(staging, fake_sherpa):
    from nova_tts.training import verify_bundle

    fake_sherpa.audio.sample_rate = 22050
    with pytest.raises(RuntimeError, match="unexpected audio"):
        verify_bundle.verify(staging)


def test_the_check_exits_zero_or_one_with_the_reason(staging, fake_sherpa, capsys):
    from nova_tts.training import verify_bundle

    assert verify_bundle.main([str(staging)]) == 0
    assert capsys.readouterr().out == "OK 1.00\n"
    fake_sherpa.audio.samples = []
    assert verify_bundle.main([str(staging)]) == 1
    assert "unexpected audio" in capsys.readouterr().err
    assert verify_bundle.main([]) == 2
