# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Reference-audio library and the TTS inputs that may name files, models or servers."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import numpy as np
import pytest
import soundfile as sf
import yaml

from src.config.schema import Config
from src.server.state import state
from src.tts import voice_library
from src.tts.voice_library import VoiceLibraryError
from tests.access_helpers import access_client, same_origin

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UNSAFE_REFERENCES = [
    "/etc/passwd",
    "config/ragflow.env",
    str(PROJECT_ROOT / "config" / "ragflow.env"),
    "../config/admin.env",
    "zh-TW-HsiaoChenNeural/../../etc/passwd",
]
EXTERNAL_SERVERS = [
    "http://evil.example:8020",
    "http://192.168.50.9:8020",
    "http://127.0.0.1@evil.example:8020",
    "https://8.8.8.8",
    "file:///etc/passwd",
    "http://127.0.0.1:8020/upload?x=1",
]


def wav_bytes(seconds: float = 1.0, rate: int = 16000, fmt: str = "WAV") -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    buffer = io.BytesIO()
    sf.write(buffer, (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def voices(tmp_path, monkeypatch):
    root = tmp_path / "voices"
    monkeypatch.setattr(voice_library, "VOICES_ROOT", root)
    return root


@pytest.fixture
def stored_voice(voices, tmp_path):
    source = tmp_path / "clip.wav"
    source.write_bytes(wav_bytes())
    return voice_library.add_voice(source, "clip")["id"]


@pytest.fixture
def server_config():
    previous = state.config
    state.config = Config()
    yield state.config
    state.config = previous


# ---------------------------------------------------------------- library


def test_upload_is_converted_to_a_wav_in_the_library(voices, tmp_path):
    source = tmp_path / "speaker.flac"
    source.write_bytes(wav_bytes(seconds=1.5, rate=44100, fmt="FLAC"))
    voice = voice_library.add_voice(source, "講者 A")
    assert voice_library.VOICE_ID.fullmatch(voice["id"])
    stored = voices / f"{voice['id']}.wav"
    assert voice_library.voice_path(voice["id"]) == stored
    audio, rate = sf.read(stored)
    assert audio.ndim == 1 and rate == 44100
    assert abs(len(audio) / rate - 1.5) < 0.05
    assert voice_library.list_voices() == [voice]
    assert voice["name"] == "講者 A"
    # The same audio is the same voice.
    assert voice_library.add_voice(source, "again")["id"] == voice["id"]
    archived = voice_library.delete_voice(voice["id"])
    assert voice_library.list_voices() == []
    assert not stored.exists()
    # Deleted voices go to the recycle bin rather than being erased.
    assert archived.parent == voices / ".deleted"
    assert sorted(path.name for path in archived.iterdir()) == [f"{voice['id']}.json", f"{voice['id']}.wav"]


@pytest.mark.parametrize("content", [
    b"root:x:0:0:root:/root:/bin/bash\n",
    b"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n",
    b"ffconcat version 1.0\nfile '/etc/passwd'\n",
    b"",
])
def test_non_audio_uploads_are_rejected(voices, tmp_path, content):
    source = tmp_path / "upload.wav"
    source.write_bytes(content)
    with pytest.raises(VoiceLibraryError):
        voice_library.add_voice(source, "bad")
    assert voice_library.list_voices() == []


def test_overlong_audio_is_rejected_from_its_header(voices, tmp_path, monkeypatch):
    monkeypatch.setattr(voice_library, "MAX_SECONDS", 2.0)
    source = tmp_path / "long.wav"
    source.write_bytes(wav_bytes(seconds=3.0))
    with pytest.raises(VoiceLibraryError, match="秒"):
        voice_library.add_voice(source, "long")
    assert voice_library.list_voices() == []


@pytest.mark.parametrize("voice_id", ["", "../voices", "/etc/passwd", "ABCDEF0123456789", "0" * 15, "0" * 16])
def test_unknown_or_malformed_ids_do_not_resolve(voices, voice_id):
    with pytest.raises(VoiceLibraryError):
        voice_library.voice_path(voice_id)


def test_development_voices_are_marked_for_the_console(voices, tmp_path):
    source = tmp_path / "sample.wav"
    source.write_bytes(wav_bytes())
    voice = voice_library.add_voice(source, "測試音檔", "逐字稿。", development=True)
    assert voice["development"] is True
    assert voice_library.list_voices() == [voice]
    other = tmp_path / "own.wav"
    other.write_bytes(wav_bytes(seconds=2.0))
    assert voice_library.add_voice(other, "自錄", "逐字稿。")["development"] is False


def test_dev_voice_import_script_is_repeatable(tmp_path):
    source = tmp_path / "prompt.wav"
    source.write_bytes(wav_bytes(seconds=1.5))
    root = tmp_path / "voices"
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "import-dev-voice.py"),
               str(source), "--voices-dir", str(root)]
    for _ in range(2):
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
    records = list(root.glob("*.json"))
    assert len(records) == 1 and len(list(root.glob("*.wav"))) == 1
    record = json.loads(records[0].read_text("utf-8"))
    assert record["name"] == "BreezyVoice 測試音檔（僅開發用）"
    assert record["transcript"] == "在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。"
    assert record["development"] is True


# ---------------------------------------------------------------- input rules


@pytest.mark.parametrize("reference", UNSAFE_REFERENCES)
def test_reference_audio_engines_only_accept_library_ids(voices, stored_voice, reference):
    with pytest.raises(VoiceLibraryError):
        voice_library.check_reference("breezyvoice", reference)
    assert voice_library.check_reference("breezyvoice", stored_voice) == stored_voice


@pytest.mark.parametrize("reference", UNSAFE_REFERENCES)
def test_server_side_references_cannot_be_paths(reference):
    with pytest.raises(VoiceLibraryError):
        voice_library.check_reference("edgetts", reference)
    assert voice_library.check_reference("edgetts", "zh-TW-YunJheNeural") == "zh-TW-YunJheNeural"


@pytest.mark.parametrize("server", EXTERNAL_SERVERS)
def test_tts_server_must_be_loopback(server):
    with pytest.raises(VoiceLibraryError):
        voice_library.check_tts_server(server)


@pytest.mark.parametrize("server, normalized", [
    ("http://127.0.0.1:9880", "http://127.0.0.1:9880"),
    ("http://localhost:8020/", "http://localhost:8020"),
    ("http://[::1]:50000", "http://[::1]:50000"),
    ("", ""),
])
def test_loopback_tts_servers_are_accepted(server, normalized):
    assert voice_library.check_tts_server(server) == normalized


def test_tts_models_come_from_the_models_folder(tmp_path, monkeypatch):
    from src.tts import cosyvoice_runtime as runtime

    models = tmp_path / "models"
    for folder in ("BreezyVoice", "tts/BreezyVoice-tw"):
        (models / folder).mkdir(parents=True)
        (models / folder / "cosyvoice.yaml").write_text("")
        (models / folder / "word_utils.py").write_text("")
    (models / "Fun-CosyVoice3-0.5B").mkdir()
    (models / "Fun-CosyVoice3-0.5B" / "cosyvoice3.yaml").write_text("")
    (models / "whisper-small").mkdir()
    monkeypatch.setattr(runtime, "MODELS_ROOT", models)
    assert runtime.local_models() == [{"id": "BreezyVoice"}, {"id": "tts/BreezyVoice-tw"}]
    assert runtime.resolve_model_dir("tts/BreezyVoice-tw") == models / "tts" / "BreezyVoice-tw"
    for bad in ("/tmp", str(models / "whisper-small"), "../models/BreezyVoice", "whisper-small",
                "Fun-CosyVoice3-0.5B"):
        with pytest.raises(FileNotFoundError):
            runtime.resolve_model_dir(bad)


# ---------------------------------------------------------------- HTTP regression


def run(coro):
    return asyncio.run(coro)


def test_global_tts_route_is_gone(server_config):
    """The default voice is the main role profile's; there is no global TTS form."""
    from src.server.access import ROUTE_ACCESS

    async def scenario():
        async with access_client() as client:
            response = await client.post("/api/speech/tts", headers=same_origin(client), json={
                "type": "breezyvoice", "ref_file": "/etc/passwd", "tts_server": "http://evil.example:8020",
            })
            assert response.status in {404, 405}
    run(scenario())
    assert ("POST", "/api/speech/tts") not in ROUTE_ACCESS
    assert server_config.tts.ref_file == Config().tts.ref_file


def test_path_picker_route_is_gone(server_config):
    async def scenario():
        async with access_client() as client:
            response = await client.post("/api/speech/path-picker", headers=same_origin(client), json={"kind": "file"})
            assert response.status in {404, 405}
    run(scenario())


def test_voice_library_routes_upload_list_and_delete(voices, server_config):
    async def scenario():
        async with access_client() as client:
            form = aiohttp.FormData()
            form.add_field("name", "接待員")
            form.add_field("voice", wav_bytes(), filename="ref.wav", content_type="audio/wav")
            response = await client.post("/api/speech/voices", headers=same_origin(client), data=form)
            assert response.status == 200, await response.text()
            voice = (await response.json())["data"]
            assert voice["name"] == "接待員"
            listed = await (await client.get("/api/speech/voices")).json()
            assert listed["data"]["items"] == [voice]
            speech = await (await client.get("/api/speech")).json()
            assert speech["data"]["tts"]["voices"] == [voice]

            form = aiohttp.FormData()
            form.add_field("voice", b"root:x:0:0:root", filename="passwd.wav", content_type="audio/wav")
            response = await client.post("/api/speech/voices", headers=same_origin(client), data=form)
            assert response.status == 400

            server_config.tts.type, server_config.tts.ref_file = "breezyvoice", voice["id"]
            response = await client.delete(f"/api/speech/voices/{voice['id']}", headers=same_origin(client))
            assert response.status == 409
            server_config.tts.type, server_config.tts.ref_file = "edgetts", "zh-TW-HsiaoChenNeural"
            response = await client.delete(f"/api/speech/voices/{voice['id']}", headers=same_origin(client))
            assert response.status == 200
            response = await client.delete("/api/speech/voices/..%2F..%2Fetc", headers=same_origin(client))
            assert response.status == 404
        async with access_client(admin=False) as client:
            assert (await client.get("/api/speech/voices")).status == 401
    run(scenario())
    assert sorted(path.name for path in voices.iterdir()) == [".deleted"]


def test_voice_library_audio_can_be_previewed_by_administrators_only(voices, stored_voice, server_config):
    async def scenario():
        async with access_client() as client:
            response = await client.get(f"/api/speech/voices/{stored_voice}/audio")
            assert response.status == 200, await response.text()
            assert response.content_type == "audio/wav"
            assert await response.read() == voice_library.voice_path(stored_voice).read_bytes()
            for bad in ("0" * 16, "..%2F..%2Fetc%2Fpasswd", "ABCDEF0123456789"):
                assert (await client.get(f"/api/speech/voices/{bad}/audio")).status == 404
        async with access_client(admin=False) as client:
            assert (await client.get(f"/api/speech/voices/{stored_voice}/audio")).status == 401
    run(scenario())


def test_voice_upload_keeps_its_transcript(voices, server_config):
    async def scenario():
        async with access_client() as client:
            form = aiohttp.FormData()
            form.add_field("transcript", "在密碼學中，加密是方法。")
            form.add_field("voice", wav_bytes(), filename="ref.wav", content_type="audio/wav")
            response = await client.post("/api/speech/voices", headers=same_origin(client), data=form)
            assert response.status == 200, await response.text()
            assert (await response.json())["data"]["transcript"] == "在密碼學中，加密是方法。"

            form = aiohttp.FormData()
            form.add_field("transcript", "字" * (voice_library.MAX_TRANSCRIPT_CHARS + 1))
            form.add_field("voice", wav_bytes(2.0), filename="long.wav", content_type="audio/wav")
            response = await client.post("/api/speech/voices", headers=same_origin(client), data=form)
            assert response.status == 400
    run(scenario())


def test_oversized_voice_upload_is_rejected_and_cleaned(voices, server_config, monkeypatch):
    monkeypatch.setattr(voice_library, "MAX_UPLOAD_BYTES", 1024)

    async def scenario():
        async with access_client() as client:
            form = aiohttp.FormData()
            form.add_field("voice", wav_bytes(), filename="ref.wav", content_type="audio/wav")
            response = await client.post("/api/speech/voices", headers=same_origin(client), data=form)
            assert response.status == 413
    run(scenario())
    assert list(voices.iterdir()) == []


# ---------------------------------------------------------------- stored settings


def test_saved_paths_migrate_into_the_library_or_are_cleared(voices, tmp_path, monkeypatch, caplog):
    allowed = tmp_path / "data" / "tts"
    allowed.mkdir(parents=True)
    (allowed / "host.wav").write_bytes(wav_bytes())
    outside = tmp_path / "outside.wav"
    outside.write_bytes(wav_bytes(seconds=0.8))
    monkeypatch.setattr(voice_library, "MIGRATION_ROOTS", (tmp_path / "data",))

    values = {"type": "breezyvoice", "ref_file": str(allowed / "host.wav"), "tts_server": "http://127.0.0.1:50000", "model": ""}
    assert voice_library.migrate_tts_values(values, where="test") is True
    assert voice_library.voice_path(values["ref_file"]).is_file()
    assert voice_library.migrate_tts_values(values, where="test") is False

    with caplog.at_level(logging.WARNING):
        for reference in (str(outside), "/etc/passwd", str(allowed / ".." / ".." / "outside.wav")):
            values = {"type": "breezyvoice", "ref_file": reference, "tts_server": "http://evil.example", "model": "/tmp"}
            assert voice_library.migrate_tts_values(values, where="test") is True
            assert values == {"type": "breezyvoice", "ref_file": "", "tts_server": "", "model": ""}
    assert "ref_file" in caplog.text and "tts_server" in caplog.text
    assert len(voice_library.list_voices()) == 1


def test_load_config_migrates_runtime_override_paths(voices, tmp_path, monkeypatch):
    from src.config import loader, overrides

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"tts": {"type": "breezyvoice", "ref_file": "/etc/passwd",
                                                   "tts_server": "http://evil.example:8020"}}))
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", tmp_path / "missing.yaml")
    config = loader.load_config(str(config_file))
    assert config.tts.ref_file == ""
    assert config.tts.tts_server == ""


def test_profiles_reject_unsafe_voice_settings_and_migrate_saved_ones(voices, stored_voice, tmp_path, monkeypatch):
    from src.profiles.store import ProfileError, ProfileStore

    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    store = ProfileStore(tmp_path / "profiles.yaml")
    library = store.initialize(config)
    for change in ({"type": "breezyvoice", "ref_file": "/etc/passwd"},
                   {"type": "breezyvoice", "ref_file": stored_voice, "tts_server": "http://evil.example:8020"},
                   {"type": "breezyvoice", "ref_file": "", "model": "/tmp"}):
        attempt = deepcopy(library)
        attempt["profiles"][0]["tts"].update(change)
        with pytest.raises(ProfileError):
            store.save(attempt, expected_revision=library["revision"])
    source = tmp_path / "spoken.wav"
    source.write_bytes(wav_bytes(seconds=2.0))
    spoken = voice_library.add_voice(source, "有逐字稿", "參考逐字稿。")["id"]
    good = deepcopy(library)
    good["profiles"][0]["tts"].update(type="breezyvoice", ref_file=spoken, tts_server="http://127.0.0.1:50000")
    library = store.save(good, expected_revision=library["revision"])

    raw = yaml.safe_load(store.path.read_text("utf-8"))
    raw["profiles"][0]["tts"].update(ref_file="/etc/passwd", tts_server="http://evil.example:8020")
    store.path.write_text(yaml.safe_dump(raw, allow_unicode=True), "utf-8")
    loaded = store.initialize(config)
    assert loaded["profiles"][0]["tts"]["ref_file"] == ""
    assert loaded["profiles"][0]["tts"]["tts_server"] == ""
    assert "/etc/passwd" not in store.path.read_text("utf-8")


def test_breezyvoice_profiles_need_a_transcribed_reference_before_saving(voices, stored_voice, tmp_path, monkeypatch):
    from src.profiles.store import ProfileError, ProfileStore

    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    store = ProfileStore(tmp_path / "profiles.yaml")
    library = store.initialize(config)
    for change, message in (({"type": "breezyvoice", "ref_file": ""}, "參考音檔"),
                            ({"type": "breezyvoice", "ref_file": stored_voice, "ref_text": ""}, "逐字稿")):
        attempt = deepcopy(library)
        attempt["profiles"][0]["tts"].update(change)
        with pytest.raises(ProfileError, match=message):
            store.save(attempt, expected_revision=library["revision"])
    source = tmp_path / "spoken.wav"
    source.write_bytes(wav_bytes(seconds=2.0))
    spoken = voice_library.add_voice(source, "有逐字稿", "參考逐字稿。")["id"]
    good = deepcopy(library)
    good["profiles"][0]["tts"].update(type="breezyvoice", ref_file=spoken, ref_text=None)
    assert store.save(good, expected_revision=library["revision"])["profiles"][0]["tts"]["ref_file"] == spoken


def test_library_transcript_is_the_only_reference_transcript(voices, stored_voice, tmp_path, monkeypatch, caplog):
    """The console no longer edits a profile transcript; a saved one is stale and dropped."""
    from src.profiles.store import ProfileError, ProfileStore

    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    store = ProfileStore(tmp_path / "profiles.yaml")
    store.initialize(config)
    source = tmp_path / "spoken.wav"
    source.write_bytes(wav_bytes(seconds=2.0))
    spoken = voice_library.add_voice(source, "有逐字稿", "音訊庫逐字稿。")["id"]
    raw = yaml.safe_load(store.path.read_text("utf-8"))
    raw["profiles"][0]["tts"].update(type="breezyvoice", ref_file=spoken, ref_text="舊的覆寫逐字稿")
    store.path.write_text(yaml.safe_dump(raw, allow_unicode=True), "utf-8")

    with caplog.at_level(logging.INFO):
        library = store.initialize(config)
    assert library["profiles"][0]["tts"]["ref_text"] is None
    assert "舊的覆寫逐字稿" not in store.path.read_text("utf-8")
    assert "ref_text" in caplog.text and "main" in caplog.text

    attempt = deepcopy(library)
    attempt["profiles"][0]["tts"]["ref_text"] = "又一個覆寫"
    caplog.clear()
    with caplog.at_level(logging.INFO):
        saved = store.save(attempt, expected_revision=library["revision"])
    assert saved["profiles"][0]["tts"]["ref_text"] is None
    assert "又一個覆寫" not in store.path.read_text("utf-8")
    assert "ref_text" in caplog.text

    # An override does not stand in for a library recording without a transcript.
    attempt = deepcopy(saved)
    attempt["profiles"][0]["tts"].update(ref_file=stored_voice, ref_text="覆寫逐字稿")
    with pytest.raises(ProfileError, match="逐字稿"):
        store.save(attempt, expected_revision=saved["revision"])


def test_profile_voice_migration_runs_once_at_startup_and_is_saved(voices, tmp_path, monkeypatch):
    from src.profiles import store as profile_store
    from src.profiles.store import ProfileStore

    allowed = tmp_path / "data" / "tts"
    allowed.mkdir(parents=True)
    (allowed / "host.wav").write_bytes(wav_bytes())
    monkeypatch.setattr(voice_library, "MIGRATION_ROOTS", (tmp_path / "data",))
    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    store = ProfileStore(tmp_path / "profiles.yaml")
    store.initialize(config)
    raw = yaml.safe_load(store.path.read_text("utf-8"))
    raw["profiles"][0]["tts"].update(type="breezyvoice", ref_file=str(allowed / "host.wav"))
    # A legacy role whose URL is not a listed endpoint keeps the file unwritten
    # until an admin picks one; the voice migration must still be saved.
    raw["profiles"][1]["llm"].pop("endpoint")
    raw["profiles"][1]["llm"]["base_url"] = "http://unlisted.example/v1"
    store.path.write_text(yaml.safe_dump(raw, allow_unicode=True), "utf-8")

    library = store.initialize(config)
    voice_id = library["profiles"][0]["tts"]["ref_file"]
    assert voice_library.voice_path(voice_id).is_file()
    saved = yaml.safe_load(store.path.read_text("utf-8"))
    assert saved["profiles"][0]["tts"]["ref_file"] == voice_id
    assert "endpoint" not in saved["profiles"][1]["llm"]

    def no_migration(*_args, **_kwargs):
        raise AssertionError("load() must not decode or hash saved audio again")

    monkeypatch.setattr(profile_store, "migrate_tts_values", no_migration)
    assert store.load()["profiles"][0]["tts"]["ref_file"] == voice_id


# ---------------------------------------------------------------- engine clients


def test_breezyvoice_prompt_comes_from_the_library(voices, stored_voice):
    from src.tts.engines.breezyvoice import BreezyVoiceTTS

    engine = BreezyVoiceTTS.__new__(BreezyVoiceTTS)
    engine.config = SimpleNamespace(tts=SimpleNamespace(type="breezyvoice", ref_file=stored_voice))
    with patch("src.tts.engines.breezyvoice.prepare_prompt_wav", side_effect=lambda path: path) as prepare:
        assert engine._prompt_wav() == str(voices / f"{stored_voice}.wav")
    prepare.assert_called_once()
    engine.config = SimpleNamespace(tts=SimpleNamespace(type="breezyvoice", ref_file="/etc/passwd"))
    with patch("src.tts.engines.breezyvoice.prepare_prompt_wav") as prepare:
        with pytest.raises(VoiceLibraryError):
            engine._prompt_wav()
    prepare.assert_not_called()
