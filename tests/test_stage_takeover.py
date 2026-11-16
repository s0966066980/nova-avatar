# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Tests for single active stage convergence, cross-device takeover, and session client_id guard."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.config.loader import load_yaml_config
from src.config.schema import Config
from src.server import conversations
from src.server.routes import attachments, audio, chat, video, webrtc
from src.server.state import state
from src.server.voice_session import VoiceTurnSession


@pytest.fixture
def webrtc_env(monkeypatch):
    config = Config()
    config.app.max_session = 1
    for name, value in dict(
        config=config,
        model_ready=True,
        model=object(),
        avatar=object(),
        switching=False,
        reply_prewarm_ready=True,
        avatar_streams={},
        voice_sessions={},
        session_roles={},
        pcs=set(),
        session_cleanups={},
        session_clients={},
    ).items():
        monkeypatch.setattr(state, name, value, raising=False)

    peers, voices = [], []

    class FakePeer:
        def __init__(self, configuration):
            self.configuration = configuration
            self.handlers = {}
            self.connectionState = "new"
            peers.append(self)

        def on(self, name):
            def attach(fn):
                self.handlers[name] = fn
                return fn

            return attach

        def addTrack(self, track):
            pass

        def getTransceivers(self):
            return []

        async def setRemoteDescription(self, value):
            pass

        async def createAnswer(self):
            return SimpleNamespace(sdp="answer", type="answer")

        async def setLocalDescription(self, value):
            self.localDescription = value

        async def close(self):
            self.connectionState = "closed"

    def make_voice(*args, **kwargs):
        voice = MagicMock()
        voice.prepare = AsyncMock()
        voice.close = AsyncMock()
        voices.append(voice)
        return voice

    monkeypatch.setattr(webrtc, "RTCPeerConnection", FakePeer)
    monkeypatch.setattr(
        webrtc,
        "HumanPlayer",
        lambda *a, **k: SimpleNamespace(audio=object(), video=object()),
    )
    monkeypatch.setattr(webrtc, "VoiceTurnSession", make_voice)
    monkeypatch.setattr(webrtc, "create_avatar", lambda *a: object())
    return SimpleNamespace(config=config, peers=peers, voices=voices)


def test_jetson_config_converges_max_session_to_one():
    root = Path(__file__).resolve().parents[1]
    raw = load_yaml_config(root / "config" / "config_jetson.yaml")
    assert raw["app"]["max_session"] == 1


def test_second_stage_device_gets_structured_409_stage_occupied_while_console_gets_429(webrtc_env):
    async def run():
        app = web.Application()
        app.router.add_post("/offer", webrtc.offer)
        async with TestClient(TestServer(app)) as client:
            first = await client.post(
                "/offer",
                json={"client_role": "stage", "client_id": "stage-a", "sdp": "good", "type": "offer"},
            )
            assert first.status == 200
            first_sid = (await first.json())["sessionid"]

            second = await client.post(
                "/offer",
                json={"client_role": "stage", "client_id": "stage-b", "sdp": "good", "type": "offer"},
            )
            assert second.status == 409
            payload = await second.json()
            assert payload["code"] == "stage_occupied"
            assert payload["msg"]
            assert state.count_sessions("stage") == 1
            assert state.session_clients.get(first_sid) == "stage-a"
            assert webrtc_env.peers[0].connectionState != "closed"

            # Console remains independent and preserves 429 behavior at capacity.
            c1 = await client.post(
                "/offer",
                json={"client_role": "console", "client_id": "console-a", "sdp": "good", "type": "offer"},
            )
            assert c1.status == 200
            c2 = await client.post(
                "/offer",
                json={"client_role": "console", "client_id": "console-b", "sdp": "good", "type": "offer"},
            )
            assert c2.status == 429

    asyncio.run(run())


def test_stage_takeover_emits_session_displaced_and_evicts_only_stage(webrtc_env, monkeypatch):
    async def run():
        order = []

        def track_voice(*args, **kwargs):
            voice = MagicMock()
            voice.prepare = AsyncMock()

            def emit(event_type, **payload):
                order.append(("emit", event_type, payload))

            async def close():
                order.append(("voice_close", len(order)))

            voice._emit = MagicMock(side_effect=emit)
            voice.close = AsyncMock(side_effect=close)
            webrtc_env.voices.append(voice)
            return voice

        monkeypatch.setattr(webrtc, "VoiceTurnSession", track_voice)

        app = web.Application()
        app.router.add_post("/offer", webrtc.offer)
        async with TestClient(TestServer(app)) as client:
            c1 = await client.post(
                "/offer",
                json={"client_role": "console", "client_id": "console-a", "sdp": "good", "type": "offer"},
            )
            assert c1.status == 200
            console_sid = (await c1.json())["sessionid"]

            s1 = await client.post(
                "/offer",
                json={"client_role": "stage", "client_id": "stage-a", "sdp": "good", "type": "offer"},
            )
            assert s1.status == 200
            first_sid = (await s1.json())["sessionid"]

            s2 = await client.post(
                "/offer",
                json={
                    "client_role": "stage",
                    "client_id": "stage-b",
                    "takeover": True,
                    "sdp": "good",
                    "type": "offer",
                },
            )
            assert s2.status == 200
            second_sid = (await s2.json())["sessionid"]
            assert second_sid != first_sid

            assert state.count_sessions("stage") == 1
            assert state.count_sessions("console") == 1
            assert first_sid not in state.avatar_streams
            assert state.session_clients.get(second_sid) == "stage-b"
            assert state.session_clients.get(console_sid) == "console-a"
            assert webrtc_env.peers[1].connectionState == "closed"
            assert webrtc_env.peers[0].connectionState != "closed"
            assert order[0] == ("emit", "session_displaced", {"reason": "takeover"})
            assert order[1][0] == "voice_close"

    asyncio.run(run())


def test_stage_takeover_still_guards_if_uncleanable_reservation_remains(webrtc_env):
    async def run():
        state.add_session(123456, None, role="stage")
        state.session_clients[123456] = "stage-in-flight"

        app = web.Application()
        app.router.add_post("/offer", webrtc.offer)
        async with TestClient(TestServer(app)) as client:
            res = await client.post(
                "/offer",
                json={
                    "client_role": "stage",
                    "client_id": "stage-b",
                    "takeover": True,
                    "sdp": "good",
                    "type": "offer",
                },
            )
            assert res.status == 409
            payload = await res.json()
            assert payload["code"] == "stage_occupied"
            assert state.count_sessions("stage") == 1

    asyncio.run(run())


def test_session_routes_enforce_client_id_while_preserving_console_stage_control(monkeypatch):
    from copy import deepcopy
    from unittest.mock import Mock

    config = Config()
    config.stage.composer_enabled = True
    config.stage.idle_reset_seconds = 0
    monkeypatch.setattr(state, "config", config)
    monkeypatch.setattr(state, "avatar_streams", {})
    monkeypatch.setattr(state, "voice_sessions", {})
    monkeypatch.setattr(state, "session_roles", {})
    monkeypatch.setattr(state, "session_clients", {})
    monkeypatch.setattr(conversations, "warm_voice", AsyncMock())

    async def run():
        avatar = SimpleNamespace(
            config=deepcopy(config),
            flush_talk=Mock(),
            is_speaking=Mock(return_value=False),
            put_audio_file=Mock(),
            set_custom_state=Mock(),
            recording=False,
            width=540,
            height=960,
            start_recording=Mock(),
            stop_recording=Mock(),
            current_record_file="",
        )
        stage_session = VoiceTurnSession(101, config, avatar, presenter="stage")
        stage_session.attach_event_sink(lambda _: None)
        stage_session.start_text_turn = AsyncMock(return_value={"turn_id": "t-1"})
        stage_session.interrupt = AsyncMock()
        stage_session.reset_conversation = Mock()

        state.add_session(101, avatar, role="stage")
        state.voice_sessions[101] = stage_session
        state.session_clients[101] = "stage-owner"

        app = web.Application()
        app.router.add_post("/human", chat.human)
        app.router.add_post("/humanaudio", audio.humanaudio)
        app.router.add_post("/set_audiotype", video.set_audiotype)
        app.router.add_post("/record", video.record)
        app.router.add_post("/interrupt_talk", chat.interrupt_talk)
        app.router.add_post("/is_speaking", chat.is_speaking)
        app.router.add_post("/clear_history", chat.clear_history)
        app.router.add_post("/api/sessions/release", webrtc.release_session)
        app.router.add_post(r"/api/conversations/{sessionid:\d+}", conversations.update_conversation)
        app.router.add_post(r"/api/conversations/{sessionid:\d+}/clear", conversations.clear_conversation)
        attachments.register(app)

        try:
            async with TestClient(TestServer(app)) as client:
                # 1. Missing or mismatched client_id is rejected on registered session routes.
                for path, body in [
                    ("/human", {"sessionid": 101, "type": "chat", "text": "hi"}),
                    ("/interrupt_talk", {"sessionid": 101}),
                    ("/is_speaking", {"sessionid": 101}),
                    ("/clear_history", {"sessionid": 101}),
                    ("/set_audiotype", {"sessionid": 101, "audiotype": 1, "reinit": False}),
                    ("/record", {"sessionid": 101, "type": "start_record"}),
                    ("/api/sessions/release", {"sessionid": 101}),
                ]:
                    missing = await client.post(path, json=body)
                    assert missing.status == 403, path
                    wrong = await client.post(path, json={**body, "client_id": "intruder"})
                    assert wrong.status == 403, path
                    wrong_header = await client.post(path, json=body, headers={"X-Client-Id": "intruder"})
                    assert wrong_header.status == 403, path

                # Multipart /humanaudio enforces client_id as well.
                from aiohttp import FormData

                def _audio_form(cid=None):
                    form = FormData()
                    form.add_field("sessionid", "101")
                    if cid is not None:
                        form.add_field("client_id", cid)
                    form.add_field("file", b"RIFF", filename="clip.wav", content_type="audio/wav")
                    return form

                assert (await client.post("/humanaudio", data=_audio_form())).status == 403
                assert (
                    await client.post("/humanaudio", data=_audio_form("intruder"))
                ).status == 403
                assert (
                    await client.post(
                        "/humanaudio",
                        data=_audio_form(),
                        headers={"X-Client-Id": "stage-owner"},
                    )
                ).status == 200

                # Matching client_id via header, query, or JSON body succeeds.
                ok_body = await client.post(
                    "/human",
                    json={"sessionid": 101, "type": "chat", "text": "hi", "client_id": "stage-owner"},
                )
                assert ok_body.status == 200
                ok_header = await client.post(
                    "/interrupt_talk",
                    json={"sessionid": 101},
                    headers={"X-Client-Id": "stage-owner"},
                )
                assert ok_header.status == 200
                ok_query = await client.post(
                    "/clear_history?client_id=stage-owner",
                    json={"sessionid": 101},
                )
                assert ok_query.status == 200
                ok_record = await client.post(
                    "/record",
                    json={"sessionid": 101, "type": "start_record"},
                    headers={"X-Client-Id": "stage-owner"},
                )
                assert ok_record.status == 200
                ok_audiotype = await client.post(
                    "/set_audiotype",
                    json={"sessionid": 101, "audiotype": 1, "reinit": False, "client_id": "stage-owner"},
                )
                assert ok_audiotype.status == 200

                # 2. Attachment routes enforce client_id.
                assert (await client.get("/api/conversations/101/attachments")).status == 403
                assert (
                    await client.get(
                        "/api/conversations/101/attachments",
                        headers={"X-Client-Id": "intruder"},
                    )
                ).status == 403
                assert (
                    await client.get(
                        "/api/conversations/101/attachments",
                        headers={"X-Client-Id": "stage-owner"},
                    )
                ).status == 200
                assert (
                    await client.post(
                        "/api/conversations/101/interaction",
                        json={"editing": True},
                    )
                ).status == 403
                assert (
                    await client.post(
                        "/api/conversations/101/interaction",
                        json={"editing": True},
                        headers={"X-Client-Id": "stage-owner"},
                    )
                ).status == 200

                # 3. Conversation settings/clear reject anonymous or wrong client_id,
                #    allow owner client_id, and allow explicit console-targeting-stage control.
                assert (
                    await client.post("/api/conversations/101", json={"history_max_messages": 10})
                ).status == 403
                assert (
                    await client.post(
                        "/api/conversations/101",
                        json={"history_max_messages": 10},
                        headers={"X-Client-Id": "intruder"},
                    )
                ).status == 403
                assert (await client.post("/api/conversations/101/clear")).status == 403

                # Even with X-Client-Role: console, /human on stage is still forbidden.
                assert (
                    await client.post(
                        "/human",
                        json={"sessionid": 101, "type": "chat", "text": "hijack"},
                        headers={"X-Client-Role": "console"},
                    )
                ).status == 403

                # Remote X-Client-Role: console without an active console session must be rejected.
                assert (
                    await client.post(
                        "/api/conversations/101",
                        json={"history_max_messages": 12},
                        headers={"X-Client-Role": "console", "X-Forwarded-For": "192.168.1.99"},
                    )
                ).status == 403
                assert (
                    await client.post(
                        "/api/conversations/101/clear",
                        headers={
                            "X-Client-Role": "console",
                            "X-Client-Id": "intruder",
                            "X-Forwarded-For": "192.168.1.99",
                        },
                    )
                ).status == 403

                # Explicit loopback console control succeeds when no console WebRTC session exists.
                console_update = await client.post(
                    "/api/conversations/101",
                    json={"history_max_messages": 12},
                    headers={"X-Client-Role": "console"},
                )
                assert console_update.status == 200
                console_clear = await client.post(
                    "/api/conversations/101/clear",
                    headers={"X-Client-Role": "console"},
                )
                assert console_clear.status == 200

                # When an active console WebRTC session exists, console control requires matching client_id.
                state.add_session(303, avatar, role="console")
                state.session_clients[303] = "console-owner"
                try:
                    assert (
                        await client.post(
                            "/api/conversations/101",
                            json={"history_max_messages": 13},
                            headers={"X-Client-Role": "console"},
                        )
                    ).status == 403
                    assert (
                        await client.post(
                            "/api/conversations/101/clear",
                            headers={"X-Client-Role": "console", "X-Client-Id": "intruder"},
                        )
                    ).status == 403
                    assert (
                        await client.post(
                            "/api/conversations/101",
                            json={"history_max_messages": 13},
                            headers={"X-Client-Role": "console", "X-Client-Id": "console-owner"},
                        )
                    ).status == 200
                finally:
                    state.remove_session(303)

                # Owner can also update/clear with matching X-Client-Id.
                owner_update = await client.post(
                    "/api/conversations/101",
                    json={"history_max_messages": 15},
                    headers={"X-Client-Id": "stage-owner"},
                )
                assert owner_update.status == 200

                # 4. Unregistered test sessions without client_id still work,
                #    but providing an explicit mismatched client_id is rejected.
                unreg_avatar = SimpleNamespace(config=deepcopy(config), flush_talk=Mock())
                unreg_session = VoiceTurnSession(202, config, unreg_avatar, presenter="stage")
                state.voice_sessions[202] = unreg_session
                try:
                    assert (
                        await client.post("/api/conversations/202", json={"history_max_messages": 9})
                    ).status == 200
                    assert (
                        await client.post(
                            "/api/conversations/202",
                            json={"history_max_messages": 9},
                            headers={"X-Client-Id": "wrong"},
                        )
                    ).status == 403
                finally:
                    await unreg_session.close()
        finally:
            await stage_session.close()

    asyncio.run(run())


def test_stage_recommended_prompt_allowed_even_when_composer_disabled(monkeypatch):
    from copy import deepcopy

    config = Config()
    config.stage.composer_enabled = False
    config.stage.recommended_prompts = ["公司有哪些產品？"]
    for name, value in dict(
        config=config,
        avatar_streams={},
        voice_sessions={},
        session_roles={},
        session_clients={},
    ).items():
        monkeypatch.setattr(state, name, value, raising=False)

    async def run():
        avatar = SimpleNamespace(config=deepcopy(config), flush_talk=MagicMock())
        stage_session = VoiceTurnSession(101, config, avatar, presenter="stage")
        stage_session.attach_event_sink(lambda _raw: None)
        stage_session.start_text_turn = AsyncMock(
            return_value={"turn_id": "t-1", "reply_mode": "legacy", "delivery": "events"}
        )
        state.add_session(101, avatar, role="stage")
        state.voice_sessions[101] = stage_session
        state.session_clients[101] = "stage-owner"

        app = web.Application()
        app.router.add_post("/human", chat.human)
        try:
            async with TestClient(TestServer(app)) as client:
                denied = await client.post(
                    "/human",
                    json={"type": "chat", "sessionid": 101, "client_id": "stage-owner", "text": "未授權的任意提問"},
                )
                assert denied.status == 409
                assert await denied.text() == "composer_disabled"

                allowed = await client.post(
                    "/human",
                    json={"type": "chat", "sessionid": 101, "client_id": "stage-owner", "text": "公司有哪些產品？"},
                )
                assert allowed.status == 200
                stage_session.start_text_turn.assert_awaited_once()
        finally:
            await stage_session.close()

    asyncio.run(run())
