# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Test clients for routes behind the console login and stage loopback rule.

Use ``access_client()`` whenever a test talks to ``create_app()`` (or another
app built with ``install_access``) over HTTP::

    async with access_client() as client:              # logged-in admin, loopback
        await client.get("/api/settings")
    async with access_client(admin=False, remote=LAN_ADDRESS) as client:
        assert (await client.get("/api/stage")).status == 403
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

from src.server.access import GUARD_DENIALS
from src.server.admin_password import write_admin_env

TEST_ADMIN_PASSWORD = "correct horse battery staple"
LOOPBACK_ADDRESS = "127.0.0.1"
LAN_ADDRESS = "192.168.50.20"


def configure_admin(path: Path, password: str = TEST_ADMIN_PASSWORD) -> Path:
    """Write an admin.env holding ``password``'s hash, as configure-admin.py does."""
    write_admin_env(path, password)
    return path


def appear_from(remote: str):
    """Middleware that makes the server see ``remote`` as the client address."""

    @web.middleware
    async def middleware(request, handler):
        return await handler(request.clone(remote=remote))

    return middleware


def default_app_factory(admin_env_path: Path) -> web.Application:
    from src.server.server import create_app

    return create_app(admin_env_path=admin_env_path)


@asynccontextmanager
async def access_client(
    *,
    admin: bool = True,
    remote: str = LOOPBACK_ADDRESS,
    configured: bool = True,
    app_factory: Callable[[Path], web.Application] = default_app_factory,
):
    """Yield a started TestClient for ``app_factory(admin_env_path)``.

    ``admin`` logs in first (the client's cookie jar then carries the Secure
    session cookie over the plain-HTTP test server); ``remote`` sets the client
    address the server sees; ``configured=False`` leaves no admin password.
    """
    with tempfile.TemporaryDirectory() as directory:
        admin_env = Path(directory) / "admin.env"
        if configured:
            configure_admin(admin_env)
        app = app_factory(admin_env)
        app.middlewares.insert(0, appear_from(remote))
        server = TestServer(app)
        await server.start_server()
        jar = CookieJar(unsafe=True, treat_as_secure_origin=str(server.make_url("/")))
        client = TestClient(server, cookie_jar=jar)
        try:
            await client.start_server()
            if admin:
                response = await client.post("/api/login", json={"password": TEST_ADMIN_PASSWORD})
                assert response.status == 200, await response.text()
            yield client
        finally:
            await client.close()


async def guard_denial(response) -> str | None:
    """The access guard's denial reason, or None when the request reached its handler."""
    if response.content_type != "application/json":
        return None
    body = await response.json()
    reason = body.get("reason") if isinstance(body, dict) else None
    return reason if reason in GUARD_DENIALS else None


def same_origin(client: TestClient) -> dict[str, str]:
    """Headers a browser sends on a same-origin state-changing request."""
    return {"Origin": str(client.make_url("/").origin())}
