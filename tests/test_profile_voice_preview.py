# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Profile-editor preview: synthesize a short sentence with a profile's unsaved voice."""

from __future__ import annotations

import asyncio
import io
import threading
import time
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from src.config.schema import Config
from src.server.access import ROUTE_ACCESS, Access
from src.server.state import state
from src.tts import cosyvoice_runtime, voice_library
from tests.access_helpers import access_client, same_origin

PREVIEW = "/api/speech/preview"
STATUS = "/api/speech/breezyvoice/status"


def wav_bytes(seconds: float = 2.0, rate: int = 16000) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    buffer = io.BytesIO()
    sf.write(buffer, (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate, format="WAV")
    return buffer.getvalue()


@pytest.fixture
def voices(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_library, "VOICES_ROOT", tmp_path / "voices")

    def add(transcript: str) -> str:
        source = tmp_path / f"clip-{len(transcript)}.wav"
        source.write_bytes(wav_bytes())
        return voice_library.add_voice(source, "clip", transcript)["id"]
    return add


@pytest.fixture
def server_config(monkeypatch):
    previous = state.config
    state.config = Config()
    monkeypatch.setattr(state, "avatar_streams", {})
    yield state.config
    state.config = previous


@pytest.fixture
def synthesis(monkeypatch):
    """The real TTS factory replaced by an engine that records what it was asked to say."""
    calls = []

    class Engine:
        def __init__(self, engine, config, sink):
            self.engine, self.config, self.sink = engine, config, sink

        def txt_to_audio(self, msg):
            calls.append({"engine": self.engine, "text": msg[0], "ref_file": self.config.tts.ref_file,
                          "tts_server": self.config.tts.tts_server, "model": self.config.tts.model})
            self.sink.put_audio_frame(np.zeros(1600, dtype=np.float32))

    monkeypatch.setattr("src.tts.factory.create_tts_engine", Engine)
    return calls


@pytest.fixture
def breezy_server(monkeypatch):
    server = Mock(ready=False)
    start = Mock(return_value="http://127.0.0.1:50000")
    monkeypatch.setattr(cosyvoice_runtime, "server_ready", lambda *_args, **_kwargs: server.ready)
    monkeypatch.setattr(cosyvoice_runtime, "ensure_server", start)
    server.start = start
    return server


def run(coroutine):
    return asyncio.run(coroutine)


def test_preview_routes_are_admin_only():
    assert ROUTE_ACCESS[("POST", PREVIEW)] is Access.ADMIN
    assert ROUTE_ACCESS[("GET", STATUS)] is Access.ADMIN


def test_breezyvoice_preview_starts_the_server_and_speaks_with_the_library_clip(
        voices, server_config, synthesis, breezy_server):
    spoken = voices("音訊庫逐字稿。")

    async def scenario():
        async with access_client() as client:
            status = await (await client.get(STATUS)).json()
            assert status["data"] == {"ready": False}
            response = await client.post(PREVIEW, headers=same_origin(client), json={"tts": {
                "type": "breezyvoice", "ref_file": spoken, "model": "", "tts_server": "", "ref_text": "覆寫"}})
            assert response.status == 200, await response.text()
            data = (await response.json())["data"]
            assert data["audio"].startswith("data:audio/wav;base64,")
        async with access_client(admin=False) as client:
            assert (await client.get(STATUS)).status == 401
            assert (await client.post(PREVIEW, headers=same_origin(client), json={"tts": {}})).status == 401
    run(scenario())
    breezy_server.start.assert_called_once_with(model_dir="", host="127.0.0.1", port=50000)
    assert synthesis == [{"engine": "breezyvoice", "text": synthesis[0]["text"], "ref_file": spoken,
                          "tts_server": "http://127.0.0.1:50000", "model": ""}]
    assert synthesis[0]["text"]
    # A preview never changes the applied default voice.
    assert server_config.tts.type == Config().tts.type


def test_edge_preview_needs_no_server(voices, server_config, synthesis, breezy_server):
    async def scenario():
        async with access_client() as client:
            response = await client.post(PREVIEW, headers=same_origin(client), json={"tts": {
                "type": "edgetts", "ref_file": "zh-TW-YunJheNeural"}})
            assert response.status == 200, await response.text()
    run(scenario())
    breezy_server.start.assert_not_called()
    assert [(c["engine"], c["ref_file"]) for c in synthesis] == [("edgetts", "zh-TW-YunJheNeural")]


@pytest.mark.parametrize("tts,message", [
    ({"type": "breezyvoice", "ref_file": "/etc/passwd"}, "音訊庫"),
    ({"type": "breezyvoice", "ref_file": "", "tts_server": "http://evil.example:8020"}, "本機"),
    ({"type": "breezyvoice", "ref_file": ""}, "參考音檔"),
    ({"type": "edgetts", "ref_file": ""}, "聲線"),
    ({"type": "cosyvoice", "ref_file": ""}, "TTS"),
])
def test_preview_rejects_unusable_or_unsafe_voices(voices, server_config, synthesis, breezy_server, tts, message):
    async def scenario():
        async with access_client() as client:
            response = await client.post(PREVIEW, headers=same_origin(client), json={"tts": tts})
            assert response.status == 400, await response.text()
            assert message in (await response.json())["msg"]
    run(scenario())
    breezy_server.start.assert_not_called()
    assert synthesis == []


def test_preview_needs_the_library_transcript(voices, server_config, synthesis, breezy_server):
    silent = voices("")

    async def scenario():
        async with access_client() as client:
            response = await client.post(PREVIEW, headers=same_origin(client), json={"tts": {
                "type": "breezyvoice", "ref_file": silent, "ref_text": "覆寫不算數"}})
            assert response.status == 400
            assert "逐字稿" in (await response.json())["msg"]
    run(scenario())
    breezy_server.start.assert_not_called()


def test_preview_does_not_start_or_replace_a_server_under_a_conversation(
        voices, server_config, synthesis, breezy_server, monkeypatch):
    spoken = voices("音訊庫逐字稿。")
    monkeypatch.setattr(state, "avatar_streams", {7: object()})
    body = {"tts": {"type": "breezyvoice", "ref_file": spoken}}

    async def scenario():
        async with access_client() as client:
            response = await client.post(PREVIEW, headers=same_origin(client), json=body)
            assert response.status == 409
            assert "連線" in (await response.json())["msg"]
            breezy_server.ready = True
            response = await client.post(PREVIEW, headers=same_origin(client), json=body)
            assert response.status == 200, await response.text()
    run(scenario())
    breezy_server.start.assert_not_called()
    assert len(synthesis) == 1


def test_preview_does_not_replace_the_default_voices_breezyvoice_server(
        voices, server_config, synthesis, breezy_server):
    spoken = voices("音訊庫逐字稿。")
    server_config.tts.type, server_config.tts.ref_file = "breezyvoice", spoken
    server_config.tts.model, server_config.tts.tts_server = "", ""

    async def scenario():
        async with access_client() as client:
            response = await client.post(PREVIEW, headers=same_origin(client), json={"tts": {
                "type": "breezyvoice", "ref_file": spoken, "tts_server": "http://127.0.0.1:50001"}})
            assert response.status == 409
            assert "預設聲音" in (await response.json())["msg"]
    run(scenario())
    breezy_server.start.assert_not_called()


def test_concurrent_breezyvoice_starts_launch_one_server(monkeypatch, tmp_path):
    """A preview and a profile apply may both start the server; only one process is launched."""
    launched = []

    def popen(*_args, **_kwargs):
        time.sleep(0.2)  # the second caller arrives while the first is launching
        launched.append(1)
        return Mock(poll=Mock(return_value=None))

    monkeypatch.setattr(cosyvoice_runtime, "resolve_model_dir", lambda _model: tmp_path)
    monkeypatch.setattr(cosyvoice_runtime, "resolve_python", lambda: tmp_path / "python")
    monkeypatch.setattr(cosyvoice_runtime, "_stop_listener", lambda _port: None)
    monkeypatch.setattr(cosyvoice_runtime, "_health_ok", lambda *_args, **_kwargs: bool(launched))
    monkeypatch.setattr(cosyvoice_runtime.subprocess, "Popen", popen)
    monkeypatch.setattr(cosyvoice_runtime, "_server_proc", None)
    monkeypatch.setattr(cosyvoice_runtime, "_loaded_model", "")
    threads = [threading.Thread(target=cosyvoice_runtime.ensure_server, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert launched == [1]


def test_breezyvoice_server_urls_bracket_ipv6_loopback():
    assert cosyvoice_runtime.server_url("::1", 50000) == "http://[::1]:50000"
    assert cosyvoice_runtime.server_identity("http://[::1]:50000", "") == ("::1", 50000, "BreezyVoice")
    assert cosyvoice_runtime.server_identity("", "") == cosyvoice_runtime.server_identity(
        "http://127.0.0.1:50000", "BreezyVoice")
