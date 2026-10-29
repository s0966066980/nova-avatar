# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Route access classes, console login and the guard that enforces them.

Every route belongs to exactly one class in ``ROUTE_ACCESS`` (enforced by
tests/test_route_access.py):

* ``PUBLIC``  - no credentials (health check, static frontend, login itself).
* ``STAGE``   - the stage page on the venue host: loopback clients, or a
  logged-in administrator. Other clients get 403.
* ``ADMIN``   - a valid administrator session, loopback included. 401 without
  one; 503 until ``scripts/configure-admin.py`` has set a password.

A few routes serve both pages; their entry is a resolver that inspects the
request and returns ``STAGE`` or ``ADMIN``. State-changing requests must also
come from the same origin as the server.
"""

from __future__ import annotations

import asyncio
import enum
import ipaddress
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from src.server.admin_password import (
    ADMIN_ENV_PATH,
    CONFIGURE_COMMAND,
    MAX_PASSWORD_LENGTH,
    read_password_hash,
    verify_password,
)
from src.server.state import state
from src.utils.logging import logger


class Access(enum.Enum):
    PUBLIC = "public"
    STAGE = "stage"
    ADMIN = "admin"


Resolver = Callable[[web.Request], Awaitable[Access]]

# Key used for the static frontend resource, whose canonical path is empty.
STATIC_FRONTEND = "<static frontend>"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SESSION_COOKIE = "nova_admin_session"


# Resolvers read small JSON bodies only (an SDP offer is a few KiB); anything
# else is treated as a console request before an anonymous client can make the
# server buffer a large body.
RESOLVER_BODY_LIMIT = 256 * 1024


async def _small_json(request: web.Request) -> dict | None:
    length = request.content_length
    if length is None or length > RESOLVER_BODY_LIMIT:
        return None
    try:
        body = await request.json()  # Cached; the handler reads the same body.
    except Exception:
        return None
    return body if isinstance(body, dict) else None


async def offer_access(request: web.Request) -> Access:
    """A stage offer is a stage request; every other offer opens a console session."""
    body = await _small_json(request) or {}
    # Mirror routes.webrtc.offer, which maps unknown roles to the console.
    role = body.get("client_role", "console")
    return Access.STAGE if isinstance(role, str) and role.strip().lower() == "stage" else Access.ADMIN


async def session_access(request: web.Request) -> Access:
    """Routes shared by the console and the stage composer follow their target session.

    The session id comes from the path, or from the JSON body exactly as the
    handler reads it, so the guard and the handler agree on the target.
    """
    if "sessionid" in request.match_info:
        sessionid = int(request.match_info["sessionid"])
    else:
        sessionid = (await _small_json(request) or {}).get("sessionid")
    try:
        role = state.session_roles.get(sessionid)
    except TypeError:
        return Access.ADMIN
    return Access.STAGE if role == "stage" else Access.ADMIN


PUBLIC, STAGE, ADMIN = Access.PUBLIC, Access.STAGE, Access.ADMIN
CONVERSATION = "/api/conversations/{sessionid}"

# (method, canonical path) -> class. HEAD shares its GET entry.
ROUTE_ACCESS: dict[tuple[str, str], Access | Resolver] = {
    # Public
    ("GET", "/health"): PUBLIC,
    ("GET", "/"): PUBLIC,
    ("GET", STATIC_FRONTEND): PUBLIC,
    ("GET", "/api/session"): PUBLIC,
    ("POST", "/api/login"): PUBLIC,
    ("POST", "/api/logout"): PUBLIC,
    # Stage page
    ("GET", "/api/stage"): STAGE,
    ("GET", "/api/vad"): STAGE,
    ("POST", "/offer"): offer_access,
    ("POST", "/human"): session_access,
    ("POST", "/interrupt_talk"): session_access,
    ("GET", CONVERSATION + "/attachments"): session_access,
    ("POST", CONVERSATION + "/attachments"): session_access,
    ("POST", CONVERSATION + "/attachments/selection"): session_access,
    ("DELETE", CONVERSATION + "/attachments/{identity}"): session_access,
    ("POST", CONVERSATION + "/interaction"): session_access,
    # Console: conversations and turns
    ("GET", "/api/conversations"): ADMIN,
    ("POST", "/api/conversations/defaults"): ADMIN,
    ("POST", CONVERSATION): ADMIN,
    ("POST", CONVERSATION + "/clear"): ADMIN,
    ("POST", "/humanaudio"): ADMIN,
    ("POST", "/asr"): ADMIN,
    ("POST", "/set_audiotype"): ADMIN,
    ("POST", "/record"): ADMIN,
    ("POST", "/is_speaking"): ADMIN,
    ("POST", "/clear_history"): ADMIN,
    ("GET", "/download/{filename}"): ADMIN,
    # Console: avatar profiles
    ("GET", "/api/profiles"): ADMIN,
    ("PUT", "/api/profiles"): ADMIN,
    ("POST", "/api/profiles/apply"): ADMIN,
    ("POST", "/api/profiles/return"): ADMIN,
    ("POST", "/api/profiles/stop"): ADMIN,
    ("POST", "/api/profiles/greeting/apply"): ADMIN,
    ("POST", "/api/profiles/greeting/preview"): ADMIN,
    ("POST", "/api/profiles/greeting/try"): ADMIN,
    ("POST", "/api/profiles/media"): ADMIN,
    ("GET", "/api/profiles/media/{asset_id}"): ADMIN,
    ("DELETE", "/api/profiles/media/{asset_id}"): ADMIN,
    # Console: settings
    ("GET", "/api/settings"): ADMIN,
    ("POST", "/api/stage"): ADMIN,
    ("POST", "/api/vad"): ADMIN,
    ("GET", "/api/speech"): ADMIN,
    ("POST", "/api/speech/stt"): ADMIN,
    ("POST", "/api/speech/tts"): ADMIN,
    ("GET", "/api/speech/voices"): ADMIN,
    ("POST", "/api/speech/voices"): ADMIN,
    ("DELETE", "/api/speech/voices/{voice_id}"): ADMIN,
    ("GET", "/api/llm/models"): ADMIN,
    ("POST", "/api/llm/model"): ADMIN,
    ("PUT", "/api/llm/behavior"): ADMIN,
    ("GET", "/api/llm/rules"): ADMIN,
    ("PUT", "/api/llm/rules"): ADMIN,
    ("GET", "/api/ragflow/settings"): ADMIN,
    ("PUT", "/api/ragflow/settings"): ADMIN,
    ("GET", "/api/ragflow/status"): ADMIN,
    ("GET", "/api/ragflow/datasets"): ADMIN,
    ("GET", "/api/ragflow/datasets/{dataset_id}/documents"): ADMIN,
    ("POST", "/api/ragflow/test"): ADMIN,
    # Console: avatars and backgrounds
    ("POST", "/api/avatar"): ADMIN,
    ("POST", "/api/avatar/quality"): ADMIN,
    ("POST", "/api/avatar/output"): ADMIN,
    ("POST", "/api/avatars/import"): ADMIN,
    ("GET", "/api/avatars/import/{job_id}"): ADMIN,
    ("GET", "/api/avatars/{avatar_id}/preview"): ADMIN,
    ("GET", "/api/avatars/{avatar_id}/scene-preview"): ADMIN,
    ("DELETE", "/api/avatars/{avatar_id}"): ADMIN,
    ("GET", "/api/avatars/deleted"): ADMIN,
    ("POST", "/api/avatars/deleted/{archive_name}/restore"): ADMIN,
    ("DELETE", "/api/avatars/deleted/{archive_name}"): ADMIN,
    ("GET", "/api/backgrounds"): ADMIN,
    ("POST", "/api/backgrounds"): ADMIN,
    ("POST", "/api/background"): ADMIN,
    ("GET", "/api/backgrounds/{background_id}/preview"): ADMIN,
    ("DELETE", "/api/backgrounds/{background_id}"): ADMIN,
    ("GET", "/api/backgrounds/deleted"): ADMIN,
    ("POST", "/api/backgrounds/deleted/{archive_name}/restore"): ADMIN,
    # Console: voice verification
    ("GET", "/api/voice-tests"): ADMIN,
    ("POST", "/api/voice-tests/run"): ADMIN,
    ("DELETE", "/api/voice-tests"): ADMIN,
}


def route_key(route: web.AbstractRoute) -> tuple[str, str]:
    """The ``ROUTE_ACCESS`` key of a registered route."""
    method = "GET" if route.method == "HEAD" else route.method
    resource = route.resource
    if isinstance(resource, web.StaticResource):
        return method, STATIC_FRONTEND
    return method, resource.canonical if resource is not None else ""


async def classify(request: web.Request) -> Access:
    entry = ROUTE_ACCESS.get(route_key(request.match_info.route))
    if entry is None:
        logger.error("未分類的路由 %s %s 以管理類處理", request.method, request.path)
        return Access.ADMIN
    return entry if isinstance(entry, Access) else await entry(request)


def is_loopback_address(address: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(address or "")
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


def client_address(request: web.Request) -> str:
    """The client's address; a loopback proxy (Vite dev server) may name the original one.

    Forwarding headers are honoured only when the TCP peer itself is loopback,
    so a LAN client cannot claim to be local.
    """
    remote = request.remote or ""
    if not is_loopback_address(remote):
        return remote
    if request.headers.get("Forwarded"):
        return "forwarded"
    forwarded = ",".join(request.headers.getall("X-Forwarded-For", []))
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    return remote


def same_origin(request: web.Request) -> bool:
    """Whether a state-changing request may come from this page's origin.

    Browsers send ``Origin`` on every non-GET fetch; clients without it are not
    browsers and cannot carry a cross-site cookie or page.
    """
    origin = request.headers.get("Origin")
    if origin is None:
        return request.headers.get("Sec-Fetch-Site", "same-origin") in {"same-origin", "none"}
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return bool(parts.scheme in {"http", "https"} and parts.netloc) and parts.netloc.lower() == (request.host or "").lower()


def host_name(request: web.Request) -> str:
    """The lower-cased host name the client addressed, without port or trailing dot."""
    try:
        name = urlsplit("//" + request.headers.get("Host", "")).hostname or ""
    except ValueError:
        return ""
    return name.rstrip(".")


def allowed_host(name: str, configured: frozenset[str]) -> bool:
    """Whether ``name`` is a name this server answers to.

    DNS rebinding points an attacker's host name at 127.0.0.1; the browser
    still sends that name in ``Host`` and ``Origin``, so the Origin check alone
    passes and the stage's loopback rule would trust the request. Only
    ``localhost``, the names set in ``app.allowed_hosts`` and IP literals are
    accepted. An IP literal cannot be rebound: the browser connects to that
    address and the page's origin is that address.
    """
    if not name:
        return False
    if name == "localhost" or name in configured:
        return True
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def normalize_hosts(names) -> frozenset[str]:
    return frozenset(str(name).strip().lower().rstrip(".") for name in names or () if str(name).strip())


class AdminAuth:
    """Administrator password check, progressive login delay and in-memory sessions."""

    MAX_TRACKED_CLIENTS = 4096

    def __init__(
        self,
        env_path: Path = ADMIN_ENV_PATH,
        *,
        session_ttl: float = 12 * 3600,
        delay_base: float = 0.5,
        delay_cap: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.env_path = Path(env_path)
        self.session_ttl = session_ttl
        self.delay_base = delay_base
        self.delay_cap = delay_cap
        self._clock = clock
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._cached: tuple[float | None, str | None] | None = None
        self._last_unconfigured_log = float("-inf")

    def password_hash(self) -> str | None:
        try:
            mtime: float | None = self.env_path.stat().st_mtime
        except OSError:
            mtime = None  # Removed: remembered as "no password" so a new one is a change.
        if self._cached is None or self._cached[0] != mtime:
            encoded = None if mtime is None else read_password_hash(self.env_path)
            if self._cached is not None and self._cached[1] != encoded:
                self._sessions.clear()  # Any password change, set or removal signs everyone out.
            self._cached = (mtime, encoded)
        return self._cached[1]

    def configured(self) -> bool:
        return self.password_hash() is not None

    def warn_unconfigured(self, *, force: bool = False) -> None:
        now = self._clock()
        if force or now - self._last_unconfigured_log >= 60:
            self._last_unconfigured_log = now
            logger.warning("尚未設定控制台管理者密碼，管理類 API 一律回 503；請執行 %s", CONFIGURE_COMMAND)

    def failure_delay(self, client: str) -> float:
        failures = self._failures.get(client, 0)
        if not failures:
            return 0.0
        return min(self.delay_cap, self.delay_base * 2 ** min(failures - 1, 32))

    async def login(self, password: str, client: str) -> str | None:
        """A new session token, or None. Attempts from one client run one at a time."""
        lock = self._locks.get(client)
        if lock is None:
            if len(self._locks) >= self.MAX_TRACKED_CLIENTS:
                self._locks = {key: held for key, held in self._locks.items() if held.locked()}
            lock = self._locks[client] = asyncio.Lock()
        async with lock:
            delay = self.failure_delay(client)
            if delay:
                await asyncio.sleep(delay)
            encoded = self.password_hash()
            if not await asyncio.to_thread(verify_password, password, encoded):
                self._record_failure(client)
                return None
            self._failures.pop(client, None)
            return self._new_session()

    def _record_failure(self, client: str) -> None:
        self._failures[client] = self._failures.pop(client, 0) + 1
        while len(self._failures) > self.MAX_TRACKED_CLIENTS:
            self._failures.pop(next(iter(self._failures)))

    def _new_session(self) -> str:
        now = self._clock()
        self._sessions = {token: expiry for token, expiry in self._sessions.items() if expiry > now}
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + self.session_ttl
        return token

    def session_valid(self, token: str | None) -> bool:
        expiry = self._sessions.get(token or "")
        if expiry is None:
            return False
        if expiry <= self._clock():
            self._sessions.pop(token, None)
            return False
        return True

    def authenticated(self, request: web.Request) -> bool:
        return self.session_valid(request.cookies.get(SESSION_COOKIE))

    def logout(self, request: web.Request) -> None:
        self._sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)


ADMIN_AUTH = web.AppKey("admin_auth", AdminAuth)
ALLOWED_HOSTS = web.AppKey("allowed_hosts", frozenset)


# ``reason`` values of the guard's own denials (the console keys on login_required).
GUARD_DENIALS = frozenset({"host_not_allowed", "origin_mismatch", "stage_local_only", "admin_unconfigured", "login_required"})


def _deny(status: int, reason: str, msg: str) -> web.Response:
    return web.json_response({"code": -1, "reason": reason, "msg": msg}, status=status)


def _unconfigured(auth: AdminAuth) -> web.Response:
    auth.warn_unconfigured()
    return _deny(503, "admin_unconfigured", f"尚未設定管理者密碼，請在主機執行 {CONFIGURE_COMMAND}")


@web.middleware
async def access_guard(request: web.Request, handler):
    if request.match_info.http_exception is not None:
        return await handler(request)  # 404 / 405
    if not allowed_host(host_name(request), request.app[ALLOWED_HOSTS]):
        return _deny(403, "host_not_allowed", "請以 localhost、IP 或設定檔 app.allowed_hosts 中的主機名稱連線")
    if request.method not in SAFE_METHODS and not same_origin(request):
        return _deny(403, "origin_mismatch", "請求來源與伺服器不同源")
    access = await classify(request)
    if access is Access.PUBLIC:
        return await handler(request)
    auth = request.app[ADMIN_AUTH]
    if access is Access.STAGE:
        if is_loopback_address(client_address(request)) or auth.authenticated(request):
            return await handler(request)
        return _deny(403, "stage_local_only", "數位人舞台只能在場域主機本機開啟")
    if not auth.configured():
        return _unconfigured(auth)
    if not auth.authenticated(request):
        return _deny(401, "login_required", "請先登入控制台")
    return await handler(request)


async def session_status(request: web.Request) -> web.Response:
    auth = request.app[ADMIN_AUTH]
    return web.json_response({"code": 0, "data": {
        "authenticated": auth.authenticated(request), "configured": auth.configured(),
    }})


async def login(request: web.Request) -> web.Response:
    auth = request.app[ADMIN_AUTH]
    if not auth.configured():
        return _unconfigured(auth)
    try:
        body = await request.json()
    except Exception:
        body = None
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(password, str) or not password or len(password) > MAX_PASSWORD_LENGTH:
        return _deny(400, "invalid_request", "請輸入密碼")
    client = client_address(request)
    token = await auth.login(password, client)
    if token is None:
        logger.warning("控制台登入失敗：%s", client)
        return _deny(401, "invalid_password", "密碼錯誤")
    response = web.json_response({"code": 0, "data": {"authenticated": True, "configured": True}})
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(auth.session_ttl), path="/",
        secure=True, httponly=True, samesite="Strict",
    )
    return response


async def logout(request: web.Request) -> web.Response:
    request.app[ADMIN_AUTH].logout(request)
    response = web.json_response({"code": 0, "data": {"authenticated": False}})
    response.del_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="Strict")
    return response


def install_access(app: web.Application, admin_env_path: Path | None = None,
                   allowed_hosts=()) -> AdminAuth:
    """Attach the guard's state and login routes to ``app``.

    ``allowed_hosts`` are host names besides localhost and IP literals that
    clients may address (``app.allowed_hosts``). ``access_guard`` must also be
    in the app's middlewares (create_app puts it first).
    """
    auth = AdminAuth(admin_env_path or ADMIN_ENV_PATH)
    app[ADMIN_AUTH] = auth
    app[ALLOWED_HOSTS] = normalize_hosts(allowed_hosts)
    app.router.add_get("/api/session", session_status)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    if not auth.configured():
        auth.warn_unconfigured(force=True)
    return auth
