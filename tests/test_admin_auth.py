# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Tests for single-admin password/PIN auth, session cookies, rate limiting, and stage isolation."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.config.schema import Config
from src.server.server import create_app
from src.server.state import state


@pytest.fixture
def server_env(monkeypatch, tmp_path):
    from src.config import overrides
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", tmp_path / "runtime_overrides.yaml")
    config = Config()
    for name, value in dict(
        config=config,
        server_ready=True,
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
    monkeypatch.delenv("NOVA_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("NOVA_ADMIN_SESSION_SECRET", raising=False)
    return config


@pytest.mark.anyio
async def test_auth_disabled_by_default_allows_status_and_admin_routes(server_env):
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        status_resp = await client.get("/api/admin/status")
        assert status_resp.status == 200
        status_payload = await status_resp.json()
        assert status_payload["code"] == 0
        assert status_payload["data"] == {
            "auth_enabled": False,
            "authenticated": True,
        }

        vad_resp = await client.get("/api/vad")
        assert vad_resp.status == 200
        conv_resp = await client.get("/api/conversations")
        assert conv_resp.status == 200


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["env", "config"])
async def test_unauthenticated_admin_routes_return_401_while_public_routes_stay_open(
    server_env, monkeypatch, source
):
    if source == "env":
        monkeypatch.setenv("NOVA_ADMIN_PASSWORD", "pin-90210")
    else:
        server_env.app.admin_password = "pin-90210"

    app = create_app()
    async with TestClient(TestServer(app)) as client:
        status_resp = await client.get("/api/admin/status")
        assert status_resp.status == 200
        assert (await status_resp.json())["data"] == {
            "auth_enabled": True,
            "authenticated": False,
        }

        # Public SPA/stage/health/read routes remain accessible without login.
        for public_path in ("/", "/stage.html", "/health", "/api/vad", "/api/stage"):
            resp = await client.get(public_path)
            assert resp.status == 200, public_path

        # Admin routes must reject unauthenticated callers with HTTP 401.
        protected_calls = [
            ("GET", "/api/settings", None),
            ("GET", "/api/conversations", None),
            ("POST", "/api/conversations/defaults", {"locale": "zh-TW"}),
            ("GET", "/api/llm/models", None),
            ("POST", "/api/llm/model", {"model": "gemma"}),
            ("PUT", "/api/llm/behavior", {"response_max_chars": 100}),
            ("GET", "/api/llm/rules", None),
            ("PUT", "/api/llm/rules", {"rules": {}}),
            ("GET", "/api/ragflow/settings", None),
            ("PUT", "/api/ragflow/settings", {"enabled": True}),
            ("GET", "/api/ragflow/datasets", None),
            ("POST", "/api/ragflow/test", {"question": "hi"}),
            ("GET", "/api/weather/settings", None),
            ("PUT", "/api/weather/settings", {"enabled": True}),
            ("POST", "/api/weather/test", {"location": "Taipei"}),
            ("POST", "/api/avatar", {"type": "musetalk", "avatar_id": "a1"}),
            ("POST", "/api/avatar/quality", {}),
            ("POST", "/api/avatar/output", {"max_height": 720}),
            ("GET", "/api/avatars/deleted", None),
            ("DELETE", "/api/avatars/alpha", None),
            ("GET", "/api/avatars/alpha/preview", None),
            ("GET", "/api/avatars/alpha/scene-preview", None),
            ("POST", "/api/avatars/import", {}),
            ("GET", "/api/backgrounds", None),
            ("POST", "/api/backgrounds", {}),
            ("POST", "/api/background", {"background_id": "none"}),
            ("GET", "/api/backgrounds/deleted", None),
            ("DELETE", "/api/backgrounds/b1", None),
            ("GET", "/api/speech", None),
            ("POST", "/api/speech/stt", {}),
            ("POST", "/api/speech/tts", {}),
            ("POST", "/api/speech/path-picker", {"kind": "file"}),
            ("GET", "/api/voice-tests", None),
            ("POST", "/api/voice-tests/run", {"prompt": "hi"}),
            ("DELETE", "/api/voice-tests", None),
            ("POST", "/api/vad", {"enabled": True}),
            ("POST", "/api/stage", {"caption_max_chars": 120}),
            ("POST", "/api/presentation/alpha", {"action": "mode", "mode": "prerecorded"}),
            ("POST", "/api/presentation/alpha/upload/idle", {}),
            ("POST", "/api/presentation/alpha/generate", {"text": "hi"}),
            ("POST", "/asr", {}),
            ("POST", "/offer", {"client_role": "console", "sdp": "x", "type": "offer"}),
        ]
        for method, path, body in protected_calls:
            resp = await client.request(method, path, json=body) if body is not None else await client.request(method, path)
            assert resp.status == 401, f"{method} {path} returned {resp.status}"


@pytest.mark.anyio
async def test_admin_login_sets_httponly_cookie_allows_admin_and_logout_revokes(server_env, monkeypatch):
    monkeypatch.setenv("NOVA_ADMIN_PASSWORD", "s3cr3t-pin!")
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        # Wrong password fails with 401 and sets no session cookie.
        bad_login = await client.post("/api/admin/login", json={"password": "wrong"})
        assert bad_login.status == 401
        assert "nova_admin_session" not in bad_login.cookies

        # Valid login returns 200 and sets HttpOnly SameSite=Lax cookie.
        ok_login = await client.post("/api/admin/login", json={"password": "s3cr3t-pin!"})
        assert ok_login.status == 200
        assert (await ok_login.json())["data"] == {
            "auth_enabled": True,
            "authenticated": True,
        }
        cookie = ok_login.cookies.get("nova_admin_session")
        assert cookie is not None
        assert cookie["httponly"] in (True, "True", "")
        assert bool(cookie["httponly"]) is True
        assert str(cookie["samesite"]).lower() == "lax"
        assert cookie["path"] == "/"

        # Authenticated session passes status & protected admin endpoints.
        status_resp = await client.get("/api/admin/status")
        assert (await status_resp.json())["data"] == {
            "auth_enabled": True,
            "authenticated": True,
        }
        settings_resp = await client.get("/api/settings")
        assert settings_resp.status == 200
        stage_post = await client.post("/api/stage", json={"caption_max_chars": 150})
        assert stage_post.status == 200

        # Tampered cookie must be rejected.
        tampered = cookie.value[:-2] + ("aa" if not cookie.value.endswith("aa") else "bb")
        async with TestClient(TestServer(app)) as other_client:
            other_client.session.cookie_jar.update_cookies({"nova_admin_session": tampered})
            tampered_resp = await other_client.get("/api/settings")
            assert tampered_resp.status == 401

        # Logout clears cookie and revokes access.
        logout_resp = await client.post("/api/admin/logout")
        assert logout_resp.status == 200
        assert (await logout_resp.json())["data"] == {
            "auth_enabled": True,
            "authenticated": False,
        }
        after_logout = await client.get("/api/settings")
        assert after_logout.status == 401


@pytest.mark.anyio
async def test_admin_login_rate_limits_repeated_failures_with_429(server_env, monkeypatch):
    monkeypatch.setenv("NOVA_ADMIN_PASSWORD", "correct-pin")
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        for _ in range(5):
            resp = await client.post("/api/admin/login", json={"password": "bad"})
            assert resp.status == 401

        # Even with the right password, the locked-out client gets 429 + Retry-After.
        blocked = await client.post("/api/admin/login", json={"password": "correct-pin"})
        assert blocked.status == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        blocked_json = await blocked.json()
        assert blocked_json["retry_after"] >= 1

        # A distinct client IP is unaffected by the first IP's lockout.
        other_ip = await client.post(
            "/api/admin/login",
            json={"password": "correct-pin"},
            headers={"X-Forwarded-For": "192.168.1.42"},
        )
        assert other_ip.status == 200


@pytest.mark.anyio
async def test_stage_visitor_session_works_without_admin_login_and_cannot_escalate(server_env, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, Mock
    from aiohttp import FormData
    from src.server import conversations
    from src.server.routes import webrtc
    from src.server.voice_session import VoiceTurnSession

    monkeypatch.setenv("NOVA_ADMIN_PASSWORD", "admin-pin-2026")
    monkeypatch.setattr(conversations, "warm_voice", AsyncMock())
    server_env.stage.composer_enabled = True

    # Register an active stage session (101) and an active console session (202).
    def _mock_avatar():
        return SimpleNamespace(
            config=deepcopy(server_env),
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

    stage_avatar = _mock_avatar()
    stage_session = VoiceTurnSession(101, server_env, stage_avatar, presenter="stage")
    stage_session.attach_event_sink(lambda _: None)
    stage_session.start_text_turn = AsyncMock(return_value={"turn_id": "t-1"})
    stage_session.interrupt = AsyncMock()
    stage_session.reset_conversation = Mock()
    state.add_session(101, stage_avatar, role="stage")
    state.voice_sessions[101] = stage_session
    state.session_clients[101] = "stage-visitor-1"
    state.session_cleanups[101] = AsyncMock()

    console_avatar = _mock_avatar()
    console_session = VoiceTurnSession(202, server_env, console_avatar, presenter="console")
    console_session.attach_event_sink(lambda _: None)
    state.add_session(202, console_avatar, role="console")
    state.voice_sessions[202] = console_session
    state.session_clients[202] = "console-admin-1"

    # Mock WebRTC offer dependencies to verify stage /offer succeeds while console /offer returns 401.
    class FakePeer:
        def __init__(self, configuration):
            self.handlers = {}
            self.connectionState = "new"

        def on(self, name):
            return lambda fn: self.handlers.setdefault(name, fn)

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
            pass

    monkeypatch.setattr(webrtc, "RTCPeerConnection", FakePeer)
    monkeypatch.setattr(webrtc, "HumanPlayer", lambda *a, **k: SimpleNamespace(audio=object(), video=object()))
    fake_voice = MagicMock()
    fake_voice.prepare = AsyncMock()
    fake_voice.close = AsyncMock()
    monkeypatch.setattr(webrtc, "VoiceTurnSession", lambda *a, **k: fake_voice)
    monkeypatch.setattr(webrtc, "create_avatar", lambda *a: _mock_avatar())

    app = create_app()
    try:
        async with TestClient(TestServer(app)) as client:
            # 1. Stage visitor can call stage-scoped endpoints with its own client_id without admin login.
            for path, body in [
                ("/human", {"sessionid": 101, "type": "chat", "text": "hello"}),
                ("/interrupt_talk", {"sessionid": 101}),
                ("/is_speaking", {"sessionid": 101}),
                ("/clear_history", {"sessionid": 101}),
                ("/set_audiotype", {"sessionid": 101, "audiotype": 1, "reinit": False}),
                ("/record", {"sessionid": 101, "type": "start_record"}),
            ]:
                resp = await client.post(path, json=body, headers={"X-Client-Id": "stage-visitor-1"})
                assert resp.status == 200, f"{path} -> {resp.status}"

            form = FormData()
            form.add_field("sessionid", "101")
            form.add_field("file", b"RIFF", filename="clip.wav", content_type="audio/wav")
            audio_resp = await client.post("/humanaudio", data=form, headers={"X-Client-Id": "stage-visitor-1"})
            assert audio_resp.status == 200

            att_resp = await client.get(
                "/api/conversations/101/attachments",
                headers={"X-Client-Id": "stage-visitor-1"},
            )
            assert att_resp.status == 200

            conv_update = await client.post(
                "/api/conversations/101",
                json={"history_max_messages": 10},
                headers={"X-Client-Id": "stage-visitor-1"},
            )
            assert conv_update.status == 200

            conv_clear_own = await client.post(
                "/api/conversations/101/clear",
                headers={"X-Client-Id": "stage-visitor-1"},
            )
            assert conv_clear_own.status == 200

            # Prerecorded background polling on stage remains readable without admin login.
            pres_read = await client.get(f"/api/presentation/{server_env.model.avatar_id}")
            assert pres_read.status == 200

            # 2. Unauthenticated callers cannot clear/update someone else's session or spoof console role.
            assert (await client.post("/api/conversations/101/clear")).status == 401
            assert (
                await client.post(
                    "/api/conversations/101/clear",
                    headers={"X-Client-Id": "intruder"},
                )
            ).status == 401
            assert (
                await client.post(
                    "/api/conversations/101/clear",
                    headers={"X-Client-Role": "console"},
                )
            ).status == 401
            assert (
                await client.post(
                    "/api/conversations/101",
                    json={"history_max_messages": 12},
                    headers={"X-Client-Role": "console"},
                )
            ).status == 401

            # 3. Unauthenticated callers cannot interact with console sessions.
            assert (
                await client.post(
                    "/human",
                    json={"sessionid": 202, "type": "chat", "text": "hijack"},
                    headers={"X-Client-Id": "console-admin-1"},
                )
            ).status == 401
            assert (
                await client.get(
                    "/api/conversations/202/attachments",
                    headers={"X-Client-Id": "console-admin-1"},
                )
            ).status == 401
            bad_form = FormData()
            bad_form.add_field("sessionid", "202")
            bad_form.add_field("file", b"RIFF", filename="clip.wav", content_type="audio/wav")
            assert (
                await client.post(
                    "/humanaudio",
                    data=bad_form,
                    headers={"X-Client-Id": "console-admin-1"},
                )
            ).status == 401

            # 4. /offer rejects console role when unauthenticated, accepts stage role (when slot available).
            assert (
                await client.post(
                    "/offer",
                    json={"client_role": "console", "client_id": "c-1", "sdp": "x", "type": "offer"},
                )
            ).status == 401

            # Stage visitor releasing its own session works without admin login,
            # freeing the single stage slot for a fresh stage /offer.
            rel = await client.post(
                "/api/sessions/release",
                json={"sessionid": 101},
                headers={"X-Client-Id": "stage-visitor-1"},
            )
            assert rel.status == 200
            state.remove_session(101)
            stage_offer = await client.post(
                "/offer",
                json={"client_role": "stage", "client_id": "stage-visitor-2", "sdp": "x", "type": "offer"},
            )
            assert stage_offer.status == 200

            # 5. Once authenticated as admin, console control of stage session and console /offer succeed.
            login = await client.post("/api/admin/login", json={"password": "admin-pin-2026"})
            assert login.status == 200
            state.add_session(101, stage_avatar, role="stage")
            state.voice_sessions[101] = stage_session
            state.session_clients[101] = "stage-visitor-1"
            admin_clear = await client.post(
                "/api/conversations/101/clear",
                headers={"X-Client-Role": "console", "X-Client-Id": "console-admin-1"},
            )
            assert admin_clear.status == 200
    finally:
        await stage_session.close()
        await console_session.close()




