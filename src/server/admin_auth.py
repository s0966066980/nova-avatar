# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Lightweight single-admin password/PIN + HttpOnly session cookie auth."""
from __future__ import annotations

import base64
from collections import deque
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any

from aiohttp import web

from src.server.request_origin import _header, is_loopback_ip
from src.server.session_guard import extract_client_id, extract_client_role
from src.server.state import state


SESSION_COOKIE_NAME = "nova_admin_session"
SESSION_TTL_SECONDS = 12 * 3600
RATE_LIMIT_MAX_FAILURES = 5
RATE_LIMIT_WINDOW_SECONDS = 300
RATE_LIMIT_LOCKOUT_SECONDS = 60

_CONV_PATH_RE = re.compile(r"^/api/conversations/(?P<sessionid>\d+)(?P<suffix>/clear)?$")
_PRES_MEDIA_RE = re.compile(r"^/api/presentation/[^/]+/media/[^/]+$")
_PRES_BG_RE = re.compile(r"^/api/presentation/background/[^/]+$")
_PRES_JOB_RE = re.compile(r"^/api/presentation/jobs/[^/]+$")
_PRES_JOB_CANCEL_RE = re.compile(r"^/api/presentation/jobs/[^/]+/cancel$")
_PRES_AVATAR_RE = re.compile(r"^/api/presentation/[^/]+$")
_ATTACH_PATH_RE = re.compile(
    r"^/api/conversations/(?P<sessionid>\d+)/(?:attachments(?:/[^/]+)?|interaction)$"
)
_STAGE_SESSION_POST_PATHS = frozenset(
    {
        "/api/sessions/release",
        "/human",
        "/interrupt_talk",
        "/is_speaking",
        "/clear_history",
        "/humanaudio",
        "/set_audiotype",
        "/record",
    }
)


def resolve_admin_password(config: Any = None) -> str:
    """Resolve the active admin password from env or AppConfig."""
    env_password = os.environ.get("NOVA_ADMIN_PASSWORD", "")
    if env_password:
        return env_password
    cfg = config if config is not None else state.config
    app_cfg = getattr(cfg, "app", None)
    configured = getattr(app_cfg, "admin_password", "") if app_cfg is not None else ""
    return str(configured) if configured else ""


def _client_ip(request: web.Request) -> str:
    remote = str(getattr(request, "remote", "") or "").strip()
    forwarded_for = _header(getattr(request, "headers", None), "X-Forwarded-For")
    if forwarded_for and (not remote or is_loopback_ip(remote)):
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    return remote or "unknown"


def _is_secure_request(request: web.Request) -> bool:
    if getattr(request, "secure", False):
        return True
    proto = _header(getattr(request, "headers", None), "X-Forwarded-Proto").lower()
    if proto == "https":
        return True
    app_cfg = getattr(state.config, "app", None) if state.config is not None else None
    return bool(getattr(app_cfg, "ssl", False))


async def _read_json_mapping(request: web.Request) -> dict[str, Any] | None:
    if "json" not in (getattr(request, "content_type", "") or "").lower():
        return None
    try:
        raw = await request.read()
        if not raw:
            return None
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


class AdminAuthManager:
    """Single-admin password verification, HMAC-signed session cookies, and rate limiting."""

    def __init__(self, secret: bytes | None = None, *, session_ttl: int = SESSION_TTL_SECONDS):
        env_secret = os.environ.get("NOVA_ADMIN_SESSION_SECRET", "")
        if secret is not None:
            self._secret = secret
        elif env_secret:
            self._secret = env_secret.encode("utf-8")
        else:
            self._secret = secrets.token_bytes(32)
        self._session_ttl = session_ttl
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(resolve_admin_password())

    def _password_tag(self, password: str) -> str:
        return hmac.new(self._secret, password.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

    def _sign(self, payload_b64: str) -> str:
        return hmac.new(self._secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()

    def issue_token(self, password: str, *, now: float | None = None) -> str:
        issued = int(now if now is not None else time.time())
        payload = {
            "iat": issued,
            "exp": issued + self._session_ttl,
            "nonce": secrets.token_hex(12),
            "tag": self._password_tag(password),
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"{payload_b64}.{self._sign(payload_b64)}"

    def verify_token(self, token: str | None, *, now: float | None = None) -> bool:
        if not token or "." not in token:
            return False
        password = resolve_admin_password()
        if not password:
            return True
        payload_b64, _, sig = token.partition(".")
        if not payload_b64 or not sig:
            return False
        expected_sig = self._sign(payload_b64)
        if not hmac.compare_digest(expected_sig, sig):
            return False
        try:
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        except Exception:
            return False
        if not isinstance(data, dict):
            return False
        exp = data.get("exp")
        tag = data.get("tag")
        current = now if now is not None else time.time()
        if not isinstance(exp, (int, float)) or exp <= current:
            return False
        if not isinstance(tag, str):
            return False
        return hmac.compare_digest(self._password_tag(password), tag)

    def is_authenticated(self, request: web.Request) -> bool:
        if not self.enabled:
            return True
        token = request.cookies.get(SESSION_COOKIE_NAME)
        return self.verify_token(token)

    def lockout_remaining(self, ip: str, *, now: float | None = None) -> int:
        current = now if now is not None else time.time()
        until = self._locked_until.get(ip, 0.0)
        if until > current:
            return max(1, int(until - current + 0.999))
        self._locked_until.pop(ip, None)
        return 0

    def record_failure(self, ip: str, *, now: float | None = None) -> int:
        current = now if now is not None else time.time()
        bucket = self._failures.setdefault(ip, deque())
        cutoff = current - RATE_LIMIT_WINDOW_SECONDS
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(current)
        if len(bucket) >= RATE_LIMIT_MAX_FAILURES:
            self._locked_until[ip] = current + RATE_LIMIT_LOCKOUT_SECONDS
            return RATE_LIMIT_LOCKOUT_SECONDS
        return 0

    def clear_failures(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._locked_until.pop(ip, None)


ADMIN_AUTH_KEY = web.AppKey("admin_auth", AdminAuthManager)


def _unauthorized_response(message: str = "請先登入管理者帳號") -> web.Response:
    return web.json_response({"code": -1, "msg": message}, status=401)


async def admin_status(request: web.Request) -> web.Response:
    auth = request.app[ADMIN_AUTH_KEY]
    enabled = auth.enabled
    authenticated = auth.is_authenticated(request) if enabled else True
    return web.json_response(
        {"code": 0, "data": {"auth_enabled": enabled, "authenticated": authenticated}}
    )


async def admin_login(request: web.Request) -> web.Response:
    auth = request.app[ADMIN_AUTH_KEY]
    if not auth.enabled:
        return web.json_response(
            {"code": 0, "data": {"auth_enabled": False, "authenticated": True}}
        )
    ip = _client_ip(request)
    if (remaining := auth.lockout_remaining(ip)) > 0:
        return web.json_response(
            {"code": -1, "msg": "嘗試次數過多，請稍後再試", "retry_after": remaining},
            status=429,
            headers={"Retry-After": str(remaining)},
        )
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"code": -1, "msg": "請求格式錯誤"}, status=400)
    submitted = payload.get("password") if isinstance(payload, dict) else None
    if not isinstance(submitted, str) or not submitted:
        auth.record_failure(ip)
        return web.json_response({"code": -1, "msg": "請輸入管理者密碼"}, status=401)
    expected = resolve_admin_password()
    if not hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8")):
        auth.record_failure(ip)
        return web.json_response({"code": -1, "msg": "密碼錯誤"}, status=401)

    auth.clear_failures(ip)
    token = auth.issue_token(expected)
    response = web.json_response(
        {"code": 0, "data": {"auth_enabled": True, "authenticated": True}}
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=auth._session_ttl,
        path="/",
        httponly=True,
        samesite="Lax",
        secure=_is_secure_request(request),
    )
    return response


async def admin_logout(request: web.Request) -> web.Response:
    auth = request.app[ADMIN_AUTH_KEY]
    enabled = auth.enabled
    response = web.json_response(
        {"code": 0, "data": {"auth_enabled": enabled, "authenticated": not enabled}}
    )
    response.del_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="Lax",
        secure=_is_secure_request(request),
    )
    return response


def _is_public_read(method: str, path: str) -> bool:
    if method not in {"GET", "HEAD"}:
        return False
    if not path.startswith("/api/"):
        return True
    if path in {"/api/admin/status", "/api/vad", "/api/stage"}:
        return True
    return bool(
        _PRES_MEDIA_RE.match(path)
        or _PRES_BG_RE.match(path)
        or _PRES_JOB_RE.match(path)
        or _PRES_AVATAR_RE.match(path)
    )


def _is_own_stage_session(request: web.Request, sessionid: int, payload: dict[str, Any] | None) -> bool:
    caller_role = extract_client_role(request, payload)
    if caller_role == "console":
        return False
    if state.session_role(sessionid) != "stage":
        return False
    owner_client_id = state.session_owner_id(sessionid)
    provided_client_id = extract_client_id(request, payload)
    return bool(owner_client_id) and provided_client_id == owner_client_id


@web.middleware
async def admin_auth_middleware(request: web.Request, handler):
    """Enforce admin auth boundary on console APIs while keeping visitor stage open."""
    if request.method == "OPTIONS":
        return await handler(request)

    auth = request.app.get(ADMIN_AUTH_KEY)
    if auth is None or not auth.enabled or auth.is_authenticated(request):
        return await handler(request)

    method = request.method
    path = request.path

    if _is_public_read(method, path):
        return await handler(request)

    if method == "POST" and path in {"/api/admin/login", "/api/admin/logout", "/api/presentation/records"}:
        return await handler(request)

    if method == "POST" and _PRES_JOB_CANCEL_RE.match(path):
        return await handler(request)

    if method == "POST" and path == "/offer":
        payload = await _read_json_mapping(request)
        client_role = str((payload or {}).get("client_role", "console")).strip().lower()
        if client_role != "stage":
            return _unauthorized_response()
        return await handler(request)

    if method == "POST" and (conv_match := _CONV_PATH_RE.match(path)):
        payload = await _read_json_mapping(request)
        sessionid = int(conv_match.group("sessionid"))
        if not _is_own_stage_session(request, sessionid, payload):
            return _unauthorized_response()
        return await handler(request)

    if attach_match := _ATTACH_PATH_RE.match(path):
        sessionid = int(attach_match.group("sessionid"))
        if state.session_role(sessionid) == "console" or extract_client_role(request) == "console":
            return _unauthorized_response()
        return await handler(request)

    if method == "POST" and path in _STAGE_SESSION_POST_PATHS:
        payload = await _read_json_mapping(request)
        if extract_client_role(request, payload) == "console":
            return _unauthorized_response()
        raw_sid = (payload or {}).get("sessionid")
        try:
            sessionid = int(raw_sid) if raw_sid is not None else None
        except (TypeError, ValueError):
            sessionid = None
        if sessionid is not None and state.session_role(sessionid) == "console":
            return _unauthorized_response()
        return await handler(request)

    return _unauthorized_response()


def register_admin_auth(app: web.Application) -> AdminAuthManager:
    auth = AdminAuthManager()
    app[ADMIN_AUTH_KEY] = auth
    app.router.add_get("/api/admin/status", admin_status)
    app.router.add_post("/api/admin/login", admin_login)
    app.router.add_post("/api/admin/logout", admin_logout)
    return auth
