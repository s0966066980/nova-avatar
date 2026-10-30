# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Before any role profile is applied the avatar speaks with the main role's voice.

The main role profile is the only source of the global TTS voice; the ``tts``
block an older console wrote to ``config/runtime_overrides.yaml`` is ignored
when loading and dropped on the next save.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from src.config import loader, overrides
from src.config.schema import Config
from src.profiles import coordinator
from src.profiles.store import ProfileStore
from src.server import deferred_settings
from src.server.state import state

OLD_OVERRIDE_TTS = {"type": "edgetts", "ref_file": "zh-TW-HsiaoYuNeural", "ref_text": None,
                    "tts_server": "", "model": ""}


@pytest.fixture
def overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "runtime_overrides.yaml"
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", path)
    return path


def saved_profiles(tmp_path, monkeypatch, *, main_voice, config=None):
    """A saved role library whose main role speaks with ``main_voice``."""
    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    config = config or Config()
    store = ProfileStore(tmp_path / "avatar_profiles.yaml")
    library = store.initialize(config)
    raw = yaml.safe_load(store.path.read_text("utf-8"))
    main = next(p for p in raw["profiles"] if p["id"] == library["pair"]["main"])
    main["tts"].update(main_voice)
    store.path.write_text(yaml.safe_dump(raw, allow_unicode=True), "utf-8")
    return store


def test_old_override_tts_block_is_not_a_second_voice_source(tmp_path, overrides_file, caplog):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"tts": {"type": "edgetts", "ref_file": "zh-TW-YunJheNeural"}}), "utf-8")
    overrides_file.write_text(yaml.safe_dump({"tts": OLD_OVERRIDE_TTS, "asr": {"model_size": "base"}}), "utf-8")
    with caplog.at_level(logging.INFO):
        config = loader.load_config(str(config_file))
    assert config.tts.ref_file == "zh-TW-YunJheNeural"
    assert config.asr.model_size == "base", "other override sections still apply"
    assert "runtime_overrides.yaml" in caplog.text and "tts" in caplog.text


def test_saving_overrides_drops_the_old_tts_block(overrides_file):
    overrides_file.write_text(yaml.safe_dump({"tts": OLD_OVERRIDE_TTS}), "utf-8")
    overrides.persist_runtime_overrides(Config())
    saved = yaml.safe_load(overrides_file.read_text("utf-8"))
    assert "tts" not in saved
    assert "asr" in saved
    assert "tts" not in overrides_file.read_text("utf-8").splitlines()[1]


def test_startup_config_adopts_the_saved_main_voice(tmp_path, monkeypatch):
    store = saved_profiles(tmp_path, monkeypatch, main_voice={"ref_file": "zh-TW-YunJheNeural"})
    config = Config()
    assert config.tts.ref_file != "zh-TW-YunJheNeural"
    assert coordinator.adopt_saved_main_voice(config, store.path)
    assert (config.tts.type, config.tts.ref_file) == ("edgetts", "zh-TW-YunJheNeural")


def test_startup_keeps_the_configured_voice_without_saved_profiles(tmp_path):
    config = Config()
    before = config.tts.ref_file
    assert not coordinator.adopt_saved_main_voice(config, tmp_path / "avatar_profiles.yaml")
    assert config.tts.ref_file == before


def test_startup_keeps_the_configured_voice_when_saved_profiles_are_unreadable(tmp_path, caplog):
    path = tmp_path / "avatar_profiles.yaml"
    path.write_text("version: [", "utf-8")
    config = Config()
    before = config.tts.ref_file
    with caplog.at_level(logging.WARNING):
        assert not coordinator.adopt_saved_main_voice(config, path)
    assert config.tts.ref_file == before
    assert "主數位人" in caplog.text


def roles_state(tmp_path, config):
    return SimpleNamespace(config=config, config_path=str(tmp_path / "config.yaml"),
                           voice_sessions={}, avatar_streams={}, avatar=object(),
                           switching=False, settings_applying=False)


def test_failed_startup_apply_still_speaks_with_the_main_voice(tmp_path, monkeypatch):
    saved_profiles(tmp_path, monkeypatch, main_voice={"ref_file": "zh-TW-YunJheNeural"})
    monkeypatch.setattr("src.avatars.catalog.avatar_bootable", lambda *_: (False, "素材不存在"))
    apply_tts = Mock(side_effect=AssertionError("startup must not synthesize a preview"))
    monkeypatch.setattr("src.server.runtime_settings.apply_tts_settings", apply_tts)
    roles_state_ = roles_state(tmp_path, Config())
    roles = asyncio.run(coordinator.initialize_roles(roles_state_))
    assert not roles.profiles_applied
    assert roles_state_.config.tts.ref_file == "zh-TW-YunJheNeural"
    assert roles.config_for_session().tts.ref_file == "zh-TW-YunJheNeural"
    apply_tts.assert_not_called()


def test_startup_with_a_breezyvoice_main_starts_its_server_without_a_preview(tmp_path, monkeypatch):
    config = Config()
    config.llm.provider = "ollama"
    breezy = {"type": "breezyvoice", "ref_file": "0123456789abcdef", "ref_text": "逐字稿。",
              "tts_server": "http://127.0.0.1:50001", "model": ""}
    saved_profiles(tmp_path, monkeypatch, main_voice=breezy, config=config)
    monkeypatch.setattr("src.profiles.store.voice_transcript", lambda _: "逐字稿。")
    monkeypatch.setattr("src.tts.voice_library.check_reference", lambda _engine, value: value)
    monkeypatch.setattr("src.profiles.store.check_reference", lambda _engine, value: value)
    monkeypatch.setattr("src.avatars.catalog.avatar_bootable", lambda *_: (True, ""))
    apply_tts = Mock(side_effect=AssertionError("startup must not synthesize a preview"))
    monkeypatch.setattr("src.server.runtime_settings.apply_tts_settings", apply_tts)
    start = Mock(return_value="http://127.0.0.1:50001")
    monkeypatch.setattr("src.tts.cosyvoice_runtime.ensure_server", start)
    state_ = roles_state(tmp_path, config)
    roles = asyncio.run(coordinator.initialize_roles(state_))
    assert roles.profiles_applied, roles.error
    assert state_.config.tts.type == "breezyvoice"
    start.assert_called_once_with(model_dir="", host="127.0.0.1", port=50001)
    apply_tts.assert_not_called()


def test_applying_a_new_main_voice_updates_the_default_voice_without_saving_it(tmp_path, monkeypatch, overrides_file):
    store = saved_profiles(tmp_path, monkeypatch, main_voice={"ref_file": "zh-TW-HsiaoChenNeural"})
    monkeypatch.setattr("src.avatars.catalog.avatar_bootable", lambda *_: (True, ""))
    config = Config()
    config.llm.provider = "ollama"
    library = store.load()
    roles = coordinator.RoleCoordinator(roles_state(tmp_path, config), store, library)
    library["profiles"][0]["tts"]["ref_file"] = "zh-TW-YunJheNeural"
    asyncio.run(roles.apply(library))
    assert config.tts.ref_file == "zh-TW-YunJheNeural"
    assert not overrides_file.exists(), "the default voice lives in the main role profile only"


def test_a_pending_global_tts_change_from_the_removed_page_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "config", Config())
    monkeypatch.setattr(state, "config_path", str(tmp_path / "config.yaml"))
    monkeypatch.setattr(state, "avatar_streams", {})
    monkeypatch.setattr(state, "switching", False)
    monkeypatch.setattr(state, "settings_applying", False)
    monkeypatch.setattr(deferred_settings, "_stores", {})
    (tmp_path / "pending_settings.json").write_text(json.dumps({
        "語音合成": {"type": "breezyvoice", "ref_file": "0123456789abcdef"},
        "語音辨識": {"type": "whisper", "model_size": "small"},
    }, ensure_ascii=False), "utf-8")
    apply_stt = Mock(return_value={})
    monkeypatch.setattr("src.server.routes.settings.apply_stt_settings", apply_stt)
    log = Mock()
    monkeypatch.setattr(deferred_settings, "logger", log)
    asyncio.run(deferred_settings.apply_pending())
    apply_stt.assert_called_once()
    assert deferred_settings.snapshot() == {"items": [], "error": ""}
    assert "語音合成" in log.warning.call_args.args
