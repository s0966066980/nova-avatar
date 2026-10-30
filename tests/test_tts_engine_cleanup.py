# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Only BreezyVoice and Edge TTS remain; saved removed engines fall back to Edge TTS."""

from __future__ import annotations

import io
import logging
from dataclasses import fields
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
import yaml

from src.config.schema import Config, TTSConfig
from src.server.runtime_settings import (
    SettingsError,
    TTS_ENGINE_META,
    apply_tts_settings,
    speech_snapshot,
)
from src.tts import voice_library
from src.tts.factory import create_tts_engine

REMOVED = ("cosyvoice", "fun-cosyvoice3", "fishtts", "gpt-sovits", "indextts2", "xtts")
LEGACY_FIELDS = {"mode": "zero_shot", "language": "zh", "speaker": "Vivian", "instruct": "", "device": "auto"}


@pytest.fixture
def voices(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_library, "VOICES_ROOT", tmp_path / "voices")
    voice_library.clear_removed_engine_notice()
    yield tmp_path / "voices"
    voice_library.clear_removed_engine_notice()


@pytest.fixture
def stored_voice(voices, tmp_path):
    buffer = io.BytesIO()
    sf.write(buffer, np.full(16000, 0.1, dtype=np.float32), 16000, format="WAV")
    source = tmp_path / "reference.wav"
    source.write_bytes(buffer.getvalue())
    return voice_library.add_voice(source, "reference")["id"]


def test_only_breezyvoice_and_edge_tts_are_offered():
    assert set(TTS_ENGINE_META) == {"edgetts", "breezyvoice"}
    engines = {item["id"] for item in speech_snapshot(Config())["tts"]["engines"]}
    assert engines == {"edgetts", "breezyvoice"}
    assert voice_library.TTS_ENGINES == frozenset(TTS_ENGINE_META)


def test_removed_engine_settings_fields_are_gone():
    names = {item.name for item in fields(TTSConfig)}
    assert not names & set(LEGACY_FIELDS)
    snapshot = speech_snapshot(Config())["tts"]
    assert not {"mode", "language", "speaker", "instruct", "device", "languages", "speakers"} & set(snapshot)


@pytest.mark.parametrize("engine", REMOVED)
def test_removed_engines_are_rejected_when_applied_or_built(engine):
    with pytest.raises(SettingsError, match="不支援"):
        apply_tts_settings(Config(), {"type": engine}, session_count=0)
    config = SimpleNamespace(audio=SimpleNamespace(fps=50), tts=SimpleNamespace(type=engine))
    with pytest.raises(ValueError):
        create_tts_engine(engine, config, None)


@pytest.mark.parametrize("engine", REMOVED)
def test_saved_removed_engine_falls_back_to_edge_tts_with_a_log_and_console_notice(
        voices, stored_voice, engine, caplog):
    values = {"type": engine, "ref_file": stored_voice, "tts_server": "http://127.0.0.1:9880",
              "model": "", **LEGACY_FIELDS}
    with caplog.at_level(logging.WARNING):
        assert voice_library.migrate_tts_values(values, where="設定檔") is True
    assert values["type"] == "edgetts"
    assert values["ref_file"] == voice_library.DEFAULT_EDGE_VOICE
    assert values["tts_server"] == "" and values["model"] == ""
    assert not set(LEGACY_FIELDS) & set(values)
    assert engine in caplog.text and "Edge TTS" in caplog.text
    notice = speech_snapshot(Config())["tts"]["notice"]
    assert engine in notice and "Edge TTS" in notice


def test_supported_engines_keep_their_settings_and_leave_no_notice(voices, stored_voice):
    values = {"type": "breezyvoice", "ref_file": stored_voice, "tts_server": "", "model": ""}
    assert voice_library.migrate_tts_values(values, where="設定檔") is False
    assert values["type"] == "breezyvoice" and values["ref_file"] == stored_voice
    assert speech_snapshot(Config())["tts"]["notice"] == ""


def test_startup_config_with_a_removed_engine_and_legacy_fields_loads_on_edge_tts(
        voices, stored_voice, tmp_path, monkeypatch, caplog):
    from src.config import loader, overrides

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"tts": {
        "type": "fun-cosyvoice3", "ref_file": stored_voice, "ref_text": "逐字稿",
        "tts_server": "http://127.0.0.1:50000", "model": "", **LEGACY_FIELDS}}), "utf-8")
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", tmp_path / "missing.yaml")
    with caplog.at_level(logging.WARNING):
        config = loader.load_config(str(config_file))
    assert config.tts.type == "edgetts"
    assert config.tts.ref_file == voice_library.DEFAULT_EDGE_VOICE
    assert "fun-cosyvoice3" in caplog.text
    assert "fun-cosyvoice3" in speech_snapshot(config)["tts"]["notice"]


def test_applying_a_tts_engine_clears_the_fallback_notice(voices, monkeypatch):
    voice_library.migrate_tts_values({"type": "xtts", "ref_file": ""}, where="設定檔")
    monkeypatch.setattr("src.server.runtime_settings._preview_tts", lambda *a, **k: "data:audio/wav;base64,dA==")
    monkeypatch.setattr("src.server.runtime_settings.persist_runtime_overrides", lambda config: None)
    result = apply_tts_settings(Config(), {"type": "edgetts", "ref_file": "zh-TW-HsiaoYuNeural"},
                                session_count=0)
    assert result["notice"] == ""


def test_saved_role_with_a_removed_engine_starts_on_edge_tts(voices, stored_voice, tmp_path, monkeypatch):
    from src.profiles.store import ProfileError, ProfileStore

    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    store = ProfileStore(tmp_path / "profiles.yaml")
    store.initialize(config)

    raw = yaml.safe_load(store.path.read_text("utf-8"))
    raw["profiles"][0]["tts"].update(type="gpt-sovits", ref_file=stored_voice, **LEGACY_FIELDS)
    store.path.write_text(yaml.safe_dump(raw, allow_unicode=True), "utf-8")
    loaded = store.initialize(config)
    tts = loaded["profiles"][0]["tts"]
    assert tts["type"] == "edgetts" and tts["ref_file"] == voice_library.DEFAULT_EDGE_VOICE
    assert not set(LEGACY_FIELDS) & set(tts)
    saved = yaml.safe_load(store.path.read_text("utf-8"))["profiles"][0]["tts"]
    assert saved["type"] == "edgetts" and not set(LEGACY_FIELDS) & set(saved)
    assert "gpt-sovits" in speech_snapshot(config)["tts"]["notice"]

    attempt = store.load()
    attempt["profiles"][0]["tts"]["type"] = "xtts"
    with pytest.raises(ProfileError, match="xtts"):
        store.save(attempt, expected_revision=attempt["revision"])
