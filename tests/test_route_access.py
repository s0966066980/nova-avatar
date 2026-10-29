# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Route access contract: every route is public, stage (loopback) or admin."""

from __future__ import annotations

import asyncio
import os
import re
import stat
import tempfile
from pathlib import Path

import pytest

from src.server import access
from src.server.access import ROUTE_ACCESS, Access, AdminAuth, route_key
from src.server.admin_password import hash_password, read_password_hash, verify_password
from src.server.server import create_app
from src.server.state import state
from tests.access_helpers import (
    LAN_ADDRESS,
    TEST_ADMIN_PASSWORD,
    access_client,
    configure_admin,
    guard_denial,
    same_origin,
)

SAFE_METHODS = {"GET", "HEAD"}
STAGE_SESSION = 424242
CONSOLE_SESSION = 535353


def registered_routes():
    """(method, canonical path) of every route create_app() serves, HEAD folded into GET."""
    app = create_app(admin_env_path=Path(tempfile.gettempdir()) / "nova-avatar-missing-admin.env")
    return sorted({route_key(route) for route in app.router.routes()})


def url_for(path: str, sessionid: int = 1) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(sessionid) if m.group(1) == "sessionid" else "sample", path)


def routes_of(kind: Access):
    return [(method, path) for method, path in registered_routes() if ROUTE_ACCESS.get((method, path)) is kind]


def resolver_routes():
    return [(method, path) for method, path in registered_routes() if callable(ROUTE_ACCESS.get((method, path)))]


@pytest.fixture
def session_roles():
    previous = dict(state.session_roles)
    state.session_roles[STAGE_SESSION] = "stage"
    state.session_roles[CONSOLE_SESSION] = "console"
    yield
    state.session_roles.clear()
    state.session_roles.update(previous)


def test_every_route_has_exactly_one_access_class():
    routes = registered_routes()
    missing = [route for route in routes if route not in ROUTE_ACCESS]
    assert not missing, f"Classify these routes in src/server/access.py ROUTE_ACCESS: {missing}"
    stale = sorted(set(ROUTE_ACCESS) - set(routes))
    assert not stale, f"ROUTE_ACCESS names routes create_app() no longer registers: {stale}"
    for key, kind in ROUTE_ACCESS.items():
        assert isinstance(kind, Access) or callable(kind), key


def test_spec_route_classes():
    assert ROUTE_ACCESS[("GET", "/health")] is Access.PUBLIC
    assert ROUTE_ACCESS[("GET", access.STATIC_FRONTEND)] is Access.PUBLIC
    assert ROUTE_ACCESS[("GET", "/api/stage")] is Access.STAGE
    assert ROUTE_ACCESS[("GET", "/api/vad")] is Access.STAGE
    assert ROUTE_ACCESS[("POST", "/api/stage")] is Access.ADMIN
    assert ROUTE_ACCESS[("GET", "/api/conversations")] is Access.ADMIN
    assert ROUTE_ACCESS[("POST", "/api/conversations/{sessionid}/clear")] is Access.ADMIN


def test_admin_routes_reject_requests_without_login_even_from_loopback():
    async def run():
        async with access_client(admin=False) as client:
            for method, path in routes_of(Access.ADMIN) + resolver_routes():
                response = await client.request(method, url_for(path))
                assert response.status == 401, (method, path, response.status)
    asyncio.run(run())


def test_admin_routes_answer_503_until_a_password_is_configured():
    async def run():
        async with access_client(admin=False, configured=False) as client:
            for method, path in routes_of(Access.ADMIN):
                response = await client.request(method, url_for(path))
                assert response.status == 503, (method, path, response.status)
            response = await client.post("/api/login", json={"password": TEST_ADMIN_PASSWORD})
            assert response.status == 503
            assert "configure-admin.py" in (await response.json())["msg"]
            session = await (await client.get("/api/session")).json()
            assert session["data"] == {"authenticated": False, "configured": False}
    asyncio.run(run())


def test_stage_routes_only_accept_loopback_without_login():
    async def run():
        async with access_client(admin=False, remote=LAN_ADDRESS) as client:
            for method, path in routes_of(Access.STAGE):
                response = await client.request(method, url_for(path))
                assert response.status == 403, (method, path, response.status)
        async with access_client(admin=False) as client:
            for method, path in routes_of(Access.STAGE):
                response = await client.request(method, url_for(path))
                assert await guard_denial(response) is None, (method, path, response.status)
    asyncio.run(run())


def test_stage_offer_is_loopback_only_and_console_offer_needs_login():
    stage_offer = {"client_role": "stage", "sdp": "", "type": "offer"}
    async def run():
        async with access_client(admin=False, remote=LAN_ADDRESS) as client:
            assert (await client.post("/offer", json=stage_offer)).status == 403
        async with access_client(admin=False) as client:
            response = await client.post("/offer", json=stage_offer)
            assert await guard_denial(response) is None, response.status
            response = await client.post("/offer", json={**stage_offer, "client_role": "console"})
            assert response.status == 401
            # Like the handler, the guard normalizes the role and treats unknown roles as console.
            response = await client.post("/offer", json={**stage_offer, "client_role": " Stage"})
            assert await guard_denial(response) is None
            response = await client.post("/offer", json={**stage_offer, "client_role": "director"})
            assert response.status == 401
            # Anonymous clients cannot make the guard buffer a large body.
            padded = {**stage_offer, "pad": "x" * access.RESOLVER_BODY_LIMIT}
            assert (await client.post("/offer", json=padded)).status == 401
    asyncio.run(run())


def test_stage_session_routes_follow_the_target_session(session_roles):
    async def run():
        attachments = f"/api/conversations/{STAGE_SESSION}/attachments"
        async with access_client(admin=False) as client:
            # Allowed through the guard; the handler reports the missing session.
            assert (await client.get(attachments)).status == 404
            response = await client.post("/human", json={"sessionid": STAGE_SESSION, "text": "hi"})
            assert await guard_denial(response) is None
            console = f"/api/conversations/{CONSOLE_SESSION}/attachments"
            assert (await client.get(console)).status == 401
            response = await client.post("/human", json={"sessionid": CONSOLE_SESSION, "text": "hi"})
            assert response.status == 401
            response = await client.post("/human", json={"sessionid": str(STAGE_SESSION), "text": "hi"})
            assert response.status == 401
        async with access_client(admin=False, remote=LAN_ADDRESS) as client:
            assert (await client.get(attachments)).status == 403
            response = await client.post("/interrupt_talk", json={"sessionid": STAGE_SESSION})
            assert response.status == 403
    asyncio.run(run())


def test_logged_in_admin_from_lan_reaches_admin_and_stage_routes():
    async def run():
        async with access_client(remote=LAN_ADDRESS) as client:
            response = await client.get("/api/conversations")
            assert await guard_denial(response) is None
            response = await client.get("/api/stage")
            assert await guard_denial(response) is None
            session = await (await client.get("/api/session")).json()
            assert session["data"] == {"authenticated": True, "configured": True}
    asyncio.run(run())


def test_cross_origin_state_changes_are_rejected():
    async def run():
        async with access_client() as client:
            evil = {"Origin": "https://evil.example"}
            for method, path in registered_routes():
                if method in SAFE_METHODS:
                    continue
                response = await client.request(method, url_for(path), headers=evil)
                assert response.status == 403, (method, path, response.status)
            # A different port on the same host is a different origin.
            other_port = {"Origin": f"http://{client.host}:{client.port + 1}"}
            assert (await client.post("/api/logout", headers=other_port)).status == 403
            assert (await client.post("/api/logout", headers={"Origin": "null"})).status == 403
            cross_site = {"Sec-Fetch-Site": "cross-site"}
            assert (await client.post("/api/logout", headers=cross_site)).status == 403
            assert (await client.post("/api/logout", headers=same_origin(client))).status == 200
    asyncio.run(run())


def test_login_sets_strict_cookie_and_logout_ends_the_session():
    async def run():
        async with access_client(admin=False) as client:
            response = await client.post("/api/login", json={"password": "wrong"})
            assert response.status == 401
            response = await client.post("/api/login", json={"password": TEST_ADMIN_PASSWORD})
            assert response.status == 200
            cookie = response.cookies[access.SESSION_COOKIE]
            assert cookie["httponly"] and cookie["secure"]
            assert cookie["samesite"] == "Strict"
            assert cookie["path"] == "/"
            assert await guard_denial(await client.get("/api/conversations")) is None
            assert (await client.post("/api/logout")).status == 200
            assert (await client.get("/api/conversations")).status == 401
            for body in ({}, {"password": 7}, []):
                assert (await client.post("/api/login", json=body)).status == 400
    asyncio.run(run())


def test_forwarded_requests_from_a_local_proxy_use_the_original_client():
    async def run():
        async with access_client(admin=False) as client:
            response = await client.get("/api/stage", headers={"X-Forwarded-For": LAN_ADDRESS})
            assert response.status == 403
            response = await client.get("/api/stage", headers={"X-Forwarded-For": f"{LAN_ADDRESS}, 127.0.0.1"})
            assert await guard_denial(response) is None
            response = await client.get("/api/stage", headers={"Forwarded": f"for={LAN_ADDRESS}"})
            assert response.status == 403
        async with access_client(admin=False, remote=LAN_ADDRESS) as client:
            # A LAN client cannot claim loopback by sending the header itself.
            response = await client.get("/api/stage", headers={"X-Forwarded-For": "127.0.0.1"})
            assert response.status == 403
    asyncio.run(run())


@pytest.mark.parametrize("address, loopback", [
    ("127.0.0.1", True), ("127.8.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("192.168.1.2", False), ("::ffff:192.168.1.2", False), ("", False), (None, False), ("localhost", False),
])
def test_loopback_addresses(address, loopback):
    assert access.is_loopback_address(address) is loopback


def test_failed_logins_wait_longer_each_time_and_success_resets(tmp_path):
    auth = AdminAuth(configure_admin(tmp_path / "admin.env"), delay_base=0.0)
    delays = []
    async def run():
        for _ in range(3):
            assert await auth.login("wrong", "10.0.0.9") is None
            delays.append(auth.failure_delay("10.0.0.9"))
        assert auth.failure_delay("10.0.0.10") == 0
        assert await auth.login(TEST_ADMIN_PASSWORD, "10.0.0.9")
        assert auth.failure_delay("10.0.0.9") == 0
    asyncio.run(run())
    auth.delay_base = 0.5
    auth._failures["10.0.0.9"] = 3
    assert auth.failure_delay("10.0.0.9") == 2.0
    auth._failures["10.0.0.9"] = 40
    assert auth.failure_delay("10.0.0.9") == auth.delay_cap


def test_sessions_expire(tmp_path):
    now = [1000.0]
    auth = AdminAuth(configure_admin(tmp_path / "admin.env"), session_ttl=60, clock=lambda: now[0])
    token = asyncio.run(auth.login(TEST_ADMIN_PASSWORD, "127.0.0.1"))
    assert auth.session_valid(token)
    assert not auth.session_valid("forged")
    now[0] += 61
    assert not auth.session_valid(token)


def test_password_hash_round_trip_and_admin_env_permissions(tmp_path):
    encoded = hash_password("s3cret-pass")
    assert encoded.startswith("scrypt$") and "s3cret-pass" not in encoded
    assert verify_password("s3cret-pass", encoded)
    assert not verify_password("s3cret-pasS", encoded)
    assert not verify_password("s3cret-pass", "scrypt$broken")
    path = configure_admin(tmp_path / "admin.env", "s3cret-pass")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert verify_password("s3cret-pass", read_password_hash(path))
    assert read_password_hash(tmp_path / "missing.env") is None


def test_admin_env_is_gitignored():
    ignored = (Path(__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "config/admin.env" in ignored


def test_cors_middleware_is_gone():
    app = create_app(admin_env_path=Path(tempfile.gettempdir()) / "nova-avatar-missing-admin.env")
    assert not [route for route in app.router.routes() if route.method == "OPTIONS"]
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "aiohttp-cors" not in pyproject
