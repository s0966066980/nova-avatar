# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's configuration reaches each processing layer through one entry point."""
from __future__ import annotations

import ast
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "core" / "nova_core" / "config"
LAYER_PACKAGES = ("nova_stt", "nova_llm", "nova_tts", "nova_render")


def _layer_imports(path: Path) -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            # ``from nova_llm import config_section`` names the submodule.
            if node.module in LAYER_PACKAGES:
                modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
            else:
                modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return [name for name in modules if name.split(".")[0] in LAYER_PACKAGES]


def test_config_reaches_processing_layers_only_through_their_config_entry_points():
    files = sorted(CONFIG_DIR.glob("*.py"))
    assert files, f"no modules under {CONFIG_DIR}"
    reached = {
        f"{path.name}: {module}"
        for path in files
        for module in _layer_imports(path)
        if module.split(".")[1:] != ["config_section"]
    }
    assert reached == set()


def test_an_old_runtime_overrides_file_with_removed_engines_and_fields_still_loads(
        tmp_path, monkeypatch):
    from nova_core.config import loader, overrides

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({
        "tts": {"type": "edgetts", "ref_file": "zh-TW-HsiaoYuNeural",
                "mode": "sft", "speaker": "old", "device": "cuda"},
    }), "utf-8")
    overrides_file = tmp_path / "runtime_overrides.yaml"
    overrides_file.write_text(yaml.safe_dump({
        "asr": {"type": "funasr", "model_size": "Fun-ASR-Nano-2512",
                "output_script": "simplified"},
        "llm": {"response_router": {"enabled": True}, "system_prompt": "舊的角色設定"},
        "model": {"type": "musetalk", "avatar_id": "musetalk_avatar",
                  "ernerf": {"x": 1}, "talkinggaussian": {"x": 1},
                  "wav2lip": {"pad_bottom": 10}},
        "tts": {"type": "cosyvoice", "ref_file": "/tmp/old.wav"},
    }), "utf-8")
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", overrides_file)

    config = loader.load_config(str(config_file))

    assert (config.asr.type, config.asr.model_size) == ("whisper", "small")
    assert not hasattr(config.asr, "output_script")
    assert not hasattr(config.llm, "response_router")
    assert config.llm.assistant_profile.system_prompt == "舊的角色設定"
    assert (config.model.type, config.model.avatar_id) == ("musetalk", "musetalk_avatar")
    assert not hasattr(config.model, "wav2lip")
    assert (config.tts.type, config.tts.ref_file) == ("edgetts", "zh-TW-HsiaoYuNeural")
    assert not hasattr(config.tts, "speaker")
