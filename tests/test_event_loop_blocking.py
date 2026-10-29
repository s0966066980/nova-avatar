# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Uploads and recordings bound their work and keep it off the event loop."""

from __future__ import annotations

import asyncio
import io
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import numpy as np
import pytest
import soundfile as sf

from src.asr import factory as asr_factory
from src.avatars import base as avatar_base
from src.avatars.base import BaseAvatar
from src.config.schema import Config
from src.server.routes import audio as audio_routes
from src.server.state import state
from src.vad import audio as vad_audio
from tests.access_helpers import access_client

SESSION = 271828
BLOCK_SECONDS = 2.0


def audio_bytes(seconds: float, sample_rate: int = 16000, fmt: str = "WAV") -> bytes:
    buffer = io.BytesIO()
    samples = np.zeros(int(seconds * sample_rate), dtype=np.int16)
    sf.write(buffer, samples, sample_rate, format=fmt, subtype="PCM_16")
    return buffer.getvalue()


def audio_form(data: bytes, sessionid: int = SESSION) -> aiohttp.FormData:
    form = aiohttp.FormData()
    form.add_field("sessionid", str(sessionid))
    form.add_field("file", data, filename="clip.wav", content_type="audio/wav")
    return form


def forbid(*_args, **_kwargs):
    raise AssertionError("this must not run")


class Blocker:
    """A blocking call that records whether the loop served others while it waited."""

    def __init__(self, result=None):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.order: list[str] = []
        self.result = result

    def __call__(self, *_args, **_kwargs):
        self.entered.set()
        self.release.wait(BLOCK_SECONDS)
        self.order.append("blocking call returned")
        return self.result


async def assert_loop_serves_while_blocked(client, blocker: Blocker, request):
    """Start ``request``; while ``blocker`` holds it, another request must complete."""
    pending = asyncio.ensure_future(request)
    for _ in range(200):
        if blocker.entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert blocker.entered.is_set(), "the request never reached the blocking call"
    health = await asyncio.wait_for(client.get("/health"), BLOCK_SECONDS)
    assert health.status == 200
    blocker.order.append("other request served")
    blocker.release.set()
    response = await pending
    assert blocker.order[0] == "other request served", blocker.order
    assert set(blocker.order[1:]) == {"blocking call returned"}
    return response


@pytest.fixture
def server(monkeypatch):
    config = Config()
    config.vad.enabled = False
    for name, value in dict(config=config, config_path=None, roles=None, avatar_streams={},
                            voice_sessions={}, session_roles={}).items():
        monkeypatch.setattr(state, name, value, raising=False)
    return config


def bare_avatar(tmp_path: Path | None = None) -> BaseAvatar:
    avatar = BaseAvatar.__new__(BaseAvatar)
    avatar.config = SimpleNamespace(sessionid=SESSION)
    avatar.sessionid = SESSION
    avatar.sample_rate = 16000
    avatar.chunk = 320
    avatar.width = avatar.height = 0
    avatar.current_record_file = None
    avatar._init_recording_state()
    avatar.frames = []
    avatar.put_audio_frame = lambda chunk, _info=None: avatar.frames.append(chunk)
    return avatar


# --- /asr ------------------------------------------------------------------


def test_asr_checks_the_session_before_decoding(server, monkeypatch):
    monkeypatch.setattr(audio_routes, "ensure_audio_within", forbid)
    monkeypatch.setattr(sf, "read", forbid)

    async def run():
        async with access_client() as client:
            response = await client.post("/asr", data=audio_form(audio_bytes(1)))
            assert response.status == 404
    asyncio.run(run())


def test_asr_rejects_long_audio_from_its_header_without_decoding_it(server, monkeypatch):
    state.avatar_streams[SESSION] = SimpleNamespace(put_msg_txt=forbid)
    monkeypatch.setattr(asr_factory, "create_asr_engine", forbid)
    monkeypatch.setattr(sf, "read", forbid)
    monkeypatch.setattr(sf.SoundFile, "read", forbid)
    # Ten minutes of silence compresses to a few KB of FLAC.
    clip = audio_bytes(600, sample_rate=8000, fmt="FLAC")
    assert len(clip) < 64 * 1024

    async def run():
        async with access_client() as client:
            response = await client.post("/asr", data=audio_form(clip))
            assert response.status == 413
            assert "秒" in (await response.json())["msg"]
    asyncio.run(run())


def test_asr_bounds_decoding_of_audio_without_a_duration_header(monkeypatch):
    calls = []
    real = vad_audio._decode_with_av

    def spy(data, target_sr, max_seconds=None):
        calls.append(max_seconds)
        return real(data, target_sr, max_seconds)

    monkeypatch.setattr(vad_audio, "_decode_with_soundfile", lambda *_a, **_k: None)
    monkeypatch.setattr(vad_audio, "_decode_with_av", spy)
    with pytest.raises(vad_audio.AudioTooLongError):
        vad_audio.ensure_audio_within(audio_bytes(3), max_seconds=1)
    assert calls == [1]
    vad_audio.ensure_audio_within(audio_bytes(0.5), max_seconds=1)


def test_asr_reuses_the_session_recognizer(server, monkeypatch):
    created = []

    class Recognizer:
        def __init__(self):
            self.languages = []

        def set_language(self, language):
            self.languages.append(language)

        def transcribe(self, _audio, *, language=None):
            return {"text": f"hello ({language})"}

    def create(**kwargs):
        created.append(kwargs)
        return Recognizer()

    monkeypatch.setattr(asr_factory, "create_asr_engine", create)
    monkeypatch.setattr(asr_factory, "_asr_instance", None)
    monkeypatch.setattr(asr_factory, "_asr_instance_key", None)
    monkeypatch.setattr(audio_routes, "llm_response", lambda text, *_a: f"reply to {text}")
    server.asr.device = "cuda"
    server.asr.language = "en"
    replies = []
    state.avatar_streams[SESSION] = SimpleNamespace(put_msg_txt=replies.append)
    # A voice session (or prewarm) loads the shared recognizer like this.
    session_engine = asr_factory.get_asr_engine(
        server.asr.type, model_size=server.asr.model_size, config=server)

    async def run():
        async with access_client() as client:
            for _ in range(2):
                response = await client.post("/asr", data=audio_form(audio_bytes(1)))
                body = await response.json()
                assert response.status == 200, body
                assert body["text"] == "hello (en)"
    asyncio.run(run())
    assert len(created) == 1
    assert asr_factory._asr_instance is session_engine
    # The shared recognizer's language stays as the session configured it.
    assert session_engine.languages == ["en"]
    assert replies == ["reply to hello (en)"] * 2


@pytest.mark.parametrize("stage", ["decode", "load"])
def test_asr_decodes_and_loads_the_recognizer_off_the_loop(server, monkeypatch, stage):
    recognizer = SimpleNamespace(transcribe=lambda _audio, language=None: {"text": ""})
    blocker = Blocker(recognizer if stage == "load" else None)
    if stage == "decode":
        monkeypatch.setattr(audio_routes, "ensure_audio_within", blocker)
        monkeypatch.setattr(audio_routes, "get_asr_engine", lambda *_a, **_k: recognizer)
    else:
        monkeypatch.setattr(audio_routes, "get_asr_engine", blocker)
    state.avatar_streams[SESSION] = SimpleNamespace(put_msg_txt=forbid)

    async def run():
        async with access_client() as client:
            response = await assert_loop_serves_while_blocked(
                client, blocker, client.post("/asr", data=audio_form(audio_bytes(1))))
            assert (await response.json())["msg"] == "未識別到語音內容"
    asyncio.run(run())


# --- /humanaudio -----------------------------------------------------------


def test_humanaudio_checks_the_session_before_decoding(server, monkeypatch):
    monkeypatch.setattr(sf, "read", forbid)

    async def run():
        async with access_client() as client:
            response = await client.post("/humanaudio", data=audio_form(audio_bytes(1)))
            assert response.status == 404
    asyncio.run(run())


def test_humanaudio_rejects_long_audio_from_its_header(server, monkeypatch):
    avatar = bare_avatar()
    state.avatar_streams[SESSION] = avatar
    monkeypatch.setattr(sf, "read", forbid)
    monkeypatch.setattr(sf.SoundFile, "read", forbid)
    clip = audio_bytes(600, sample_rate=8000, fmt="FLAC")

    async def run():
        async with access_client() as client:
            response = await client.post("/humanaudio", data=audio_form(clip))
            assert response.status == 413
    asyncio.run(run())
    assert avatar.frames == []


def test_humanaudio_decodes_resamples_and_queues_audio(server):
    avatar = bare_avatar()
    state.avatar_streams[SESSION] = avatar

    async def run():
        async with access_client() as client:
            response = await client.post("/humanaudio", data=audio_form(audio_bytes(1, sample_rate=8000)))
            assert response.status == 200
            assert (await response.json())["code"] == 0
    asyncio.run(run())
    assert len(avatar.frames) == 16000 // 320


def test_humanaudio_queues_audio_off_the_loop(server):
    blocker = Blocker()
    state.avatar_streams[SESSION] = SimpleNamespace(put_audio_file=blocker)

    async def run():
        async with access_client() as client:
            response = await assert_loop_serves_while_blocked(
                client, blocker, client.post("/humanaudio", data=audio_form(audio_bytes(1))))
            assert response.status == 200
    asyncio.run(run())


# --- recording -------------------------------------------------------------


class FakePipe:
    def __init__(self, wait=None):
        self.stdin = SimpleNamespace(closed=False, write=lambda _data: None)
        self.stdin.close = lambda: setattr(self.stdin, "closed", True)
        self._wait = wait
        self.killed = False

    def wait(self, timeout=None):
        if self._wait is not None:
            self._wait()
        return 0

    def kill(self):
        self.killed = True


def recording_avatar(tmp_path, monkeypatch, wait=None):
    avatar = bare_avatar()
    monkeypatch.setattr(avatar_base, "RECORDS_DIR", tmp_path / "records")
    monkeypatch.setattr(avatar_base.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(avatar_base.subprocess, "Popen", lambda *_a, **_k: FakePipe(wait))
    monkeypatch.setattr(avatar_base.os, "system", forbid)
    avatar.start_recording()
    avatar.record_video_data(np.zeros((4, 6, 3), np.uint8))
    avatar.record_audio_data(np.zeros(320, np.int16))
    temporary = avatar._record_dir
    for name in ("video.mp4", "audio.aac"):
        (temporary / name).write_bytes(b"media")
    return avatar, temporary


def fake_merge(monkeypatch):
    commands = []

    async def create_subprocess_exec(*argv, **kwargs):
        commands.append(argv)
        Path(argv[-1]).write_bytes(b"merged")  # noqa: ASYNC240 -- test fake for the ffmpeg child
        process = SimpleNamespace(returncode=0, kill=lambda: None)

        async def wait():
            return 0
        process.wait = wait
        return process

    monkeypatch.setattr(avatar_base.asyncio, "create_subprocess_exec", create_subprocess_exec)
    return commands


def test_stop_recording_merges_with_an_argv_subprocess_and_clears_temporaries(tmp_path, monkeypatch):
    avatar, temporary = recording_avatar(tmp_path, monkeypatch)
    commands = fake_merge(monkeypatch)
    output = asyncio.run(avatar.stop_recording())
    assert output is not None and Path(output).read_bytes() == b"merged"
    assert Path(output).parent == tmp_path / "records"
    assert len(commands) == 1
    argv = commands[0]
    assert argv[0] == "ffmpeg"
    assert str(temporary / "audio.aac") in argv and str(temporary / "video.mp4") in argv
    assert not temporary.exists()
    assert avatar.recording is False
    assert avatar.current_record_file == output


def test_record_route_waits_for_ffmpeg_off_the_loop(tmp_path, monkeypatch, server):
    blocker = Blocker()
    avatar, temporary = recording_avatar(tmp_path, monkeypatch, wait=blocker)
    fake_merge(monkeypatch)
    state.avatar_streams[SESSION] = avatar

    async def run():
        async with access_client() as client:
            request = client.post("/record", json={"sessionid": SESSION, "type": "end_record"})
            response = await assert_loop_serves_while_blocked(client, blocker, request)
            body = await response.json()
            assert response.status == 200, body
            assert body["filename"].startswith("record_")
    asyncio.run(run())
    assert not temporary.exists()


def test_discarding_a_recording_stops_ffmpeg_and_clears_temporaries(tmp_path, monkeypatch):
    avatar, temporary = recording_avatar(tmp_path, monkeypatch)
    pipes = (avatar._record_video_pipe, avatar._record_audio_pipe)
    monkeypatch.setattr(avatar_base.asyncio, "create_subprocess_exec", forbid)
    asyncio.run(avatar.discard_recording())
    assert all(pipe.stdin.closed for pipe in pipes)
    assert not temporary.exists()
    assert avatar.recording is False
    assert not (tmp_path / "records").exists()
    # Frames that arrive after the stop are dropped, not written to a closed pipe.
    avatar.record_video_data(np.zeros((4, 6, 3), np.uint8))
    asyncio.run(avatar.discard_recording())


def test_stopped_ffmpeg_that_hangs_is_killed():
    waits = []

    def wait(timeout=None):
        waits.append(timeout)
        if not pipe.killed:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return -9
    pipe = FakePipe()
    pipe.wait = wait
    BaseAvatar._close_recording_pipes((pipe, None), timeout=0.01)
    assert pipe.killed and pipe.stdin.closed
    assert waits == [0.01, None]
