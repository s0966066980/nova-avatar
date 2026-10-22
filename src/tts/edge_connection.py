# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Reusable Edge sockets owned by one persistent asyncio loop.

Adapted from Nova Avatar main's connection pool. Speech framing comes from
edge-tts; cancellation and interrupted requests always discard the socket.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import math
import time
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit
from xml.sax.saxutils import escape

import aiohttp
from edge_tts import communicate as transport
from edge_tts.data_classes import TTSConfig
from edge_tts.drm import DRM

from src.utils.logging import logger

MAX_IDLE_AGE_SECONDS = 60.0
REFRESH_BEFORE_EXPIRY_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 10.0
RESPONSE_TIMEOUT_SECONDS = 15.0
# A socket can remain locally open after its idle peer stops accepting speech.
# Replace it before the synthesis caller exhausts its first-audio deadline.
REUSED_FIRST_AUDIO_TIMEOUT_SECONDS = 1.0
WARM_RETRY_SECONDS = 15.0

_SPEECH_CONFIG = (
    "X-Timestamp:{timestamp}\r\n"
    "Content-Type:application/json; charset=utf-8\r\n"
    "Path:speech.config\r\n\r\n"
    '{{"context":{{"synthesis":{{"audio":{{"metadataoptions":{{'
    '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"}},'
    '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}}}}}\r\n'
)


def configure_edge_endpoint() -> None:
    """Preserve Nova's legacy endpoint migration and future upstream endpoints."""
    endpoint = urlsplit(transport.WSS_URL)
    if (
        endpoint.netloc == "speech.platform.bing.com"
        and endpoint.path == "/consumer/speech/synthesize/readaloud/edge/v1"
    ):
        token = parse_qs(endpoint.query)["TrustedClientToken"][0]
        transport.WSS_URL = (
            "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?"
            + urlencode({"Ocp-Apim-Subscription-Key": token})
        )


def _default_url() -> str:
    configure_edge_endpoint()
    return (
        f"{transport.WSS_URL}&ConnectionId={transport.connect_id()}"
        f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
        f"&Sec-MS-GEC-Version={transport.SEC_MS_GEC_VERSION}"
    )


def _retry_delay(exc: Exception, default: float) -> float:
    value = (getattr(exc, "headers", None) or {}).get("Retry-After", "")
    try:
        delay = float(value)
    except (TypeError, ValueError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return default
    return max(default, delay) if math.isfinite(delay) else default


class StaleConnection(ConnectionError):
    """The peer closed a socket before any audio was received."""


@dataclass
class _Connection:
    ws: aiohttp.ClientWebSocketResponse
    opened_at: float


class EdgeConnectionPool:
    def __init__(
        self, *, url_factory: Callable[[], str] = _default_url,
        clock: Callable[[], float] = time.monotonic,
        max_idle: int = 2, max_age: float = MAX_IDLE_AGE_SECONDS,
    ) -> None:
        self._url_factory = url_factory
        self._clock = clock
        self._max_idle = max_idle
        self._max_age = max_age
        self._idle: list[_Connection] = []
        self._session = None
        self._warm_task = None
        self._closed = False
        self._retry_until = 0.0

    @property
    def idle_count(self) -> int:
        return len(self._idle)

    async def _open(self) -> _Connection:
        if self._closed:
            raise RuntimeError("Edge connection pool is closed")
        while self._retry_until > time.monotonic():
            await asyncio.sleep(self._retry_until - time.monotonic())
        if self._closed:
            raise RuntimeError("Edge connection pool is closed")
        if self._session is None:
            self._session = aiohttp.ClientSession(trust_env=True)
        try:
            ws = await asyncio.wait_for(
                self._session.ws_connect(
                    self._url_factory(), compress=15,
                    headers=DRM.headers_with_muid(transport.WSS_HEADERS),
                    ssl=transport._SSL_CTX,
                ), timeout=CONNECT_TIMEOUT_SECONDS,
            )
        except aiohttp.WSServerHandshakeError as exc:
            if exc.status == 429:
                self._retry_until = max(self._retry_until, time.monotonic() + _retry_delay(exc, 1.0))
            raise
        return _Connection(ws, self._clock())

    async def _prune_expired(self) -> None:
        expired = [
            connection for connection in self._idle
            if connection.ws.closed or self._clock() - connection.opened_at >= self._max_age
        ]
        # Claim all expired sockets before yielding: the background refresher
        # and multiple foreground requests can prune on the same loop.
        self._idle = [connection for connection in self._idle if connection not in expired]
        await asyncio.gather(*(connection.ws.close() for connection in expired))

    async def _put_back(self, connection: _Connection) -> None:
        if self._closed or connection.ws.closed or self._clock() - connection.opened_at >= self._max_age:
            await connection.ws.close()
            return
        self._idle.append(connection)
        if len(self._idle) > self._max_idle:
            # Refresh must replace an older socket even when the idle pool is
            # full. Discarding the new socket here would cause a reconnect loop.
            oldest = min(self._idle, key=lambda item: item.opened_at)
            self._idle.remove(oldest)
            await oldest.ws.close()

    def ensure_warm(self) -> None:
        if not self._closed and (self._warm_task is None or self._warm_task.done()):
            self._warm_task = asyncio.create_task(self._keep_warm())

    async def _keep_warm(self) -> None:
        refresh_age = max(self._max_age - REFRESH_BEFORE_EXPIRY_SECONDS, self._max_age / 2)
        while not self._closed:
            await self._prune_expired()
            newest = max(self._idle, key=lambda item: item.opened_at, default=None)
            age = None if newest is None else self._clock() - newest.opened_at
            if age is not None and age < refresh_age:
                await asyncio.sleep(max(0.05, refresh_age - age))
                continue
            try:
                await self._put_back(await self._open())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = _retry_delay(exc, WARM_RETRY_SECONDS)
                logger.warning("Edge TTS spare unavailable type=%s retry_in=%.1fs", type(exc).__name__, delay)
                await asyncio.sleep(delay)

    async def stream(self, text: str, voice: str):
        config = TTSConfig(voice, "+0%", "+0%", "+0Hz", "SentenceBoundary")
        requests = transport.split_text_by_byte_length(
            escape(transport.remove_incompatible_characters(text)), 4096,
        )
        await self._prune_expired()
        connection = self._idle.pop() if self._idle else None
        reused = connection is not None
        clean = False
        yielded = False
        try:
            if connection is None:
                connection = await self._open()
            for request in requests:
                while True:
                    try:
                        async for chunk in self._request(
                            connection, config, request,
                            first_audio_timeout=(
                                REUSED_FIRST_AUDIO_TIMEOUT_SECONDS
                                if reused and not yielded else RESPONSE_TIMEOUT_SECONDS
                            ),
                        ):
                            yielded = True
                            yield chunk
                        break
                    except (StaleConnection, asyncio.TimeoutError):
                        if yielded or not reused:
                            raise
                        await connection.ws.close()
                        connection = await self._open()
                        reused = False
            clean = True
        finally:
            if connection is not None:
                if clean:
                    await self._put_back(connection)
                else:
                    await connection.ws.close()
            self.ensure_warm()

    async def _request(
        self, connection, config, request, *,
        first_audio_timeout: float = RESPONSE_TIMEOUT_SECONDS,
    ):
        ws = connection.ws
        first_audio_deadline = asyncio.get_running_loop().time() + first_audio_timeout
        try:
            await ws.send_str(_SPEECH_CONFIG.format(timestamp=transport.date_to_string()))
            await ws.send_str(transport.ssml_headers_plus_data(
                transport.connect_id(), transport.date_to_string(), transport.mkssml(config, request),
            ))
        except (ConnectionError, aiohttp.ClientError, RuntimeError) as exc:
            raise StaleConnection() from exc
        audio_seen = False
        while True:
            timeout = (
                RESPONSE_TIMEOUT_SECONDS if audio_seen else
                max(0.0, first_audio_deadline - asyncio.get_running_loop().time())
            )
            message = await asyncio.wait_for(ws.receive(), timeout=timeout)
            if message.type == aiohttp.WSMsgType.TEXT:
                if "Path:turn.end" in message.data:
                    if not audio_seen:
                        raise RuntimeError("Edge TTS turn ended without audio")
                    return
            elif message.type == aiohttp.WSMsgType.BINARY:
                data = message.data
                if len(data) < 2:
                    raise RuntimeError("Invalid Edge audio frame")
                header_length = int.from_bytes(data[:2], "big")
                if header_length > len(data) - 2:
                    raise RuntimeError("Invalid Edge audio header")
                headers = data[2:2 + header_length].split(b"\r\n")
                payload = data[2 + header_length:]
                if b"Path:audio" in headers and payload:
                    audio_seen = True
                    yield {"type": "audio", "data": payload}
            elif not audio_seen:
                raise StaleConnection(f"socket {message.type.name}")
            else:
                raise ConnectionError(f"Edge TTS socket {message.type.name} mid-stream")

    async def close(self) -> None:
        self._closed = True
        if self._warm_task is not None:
            self._warm_task.cancel()
            await asyncio.gather(self._warm_task, return_exceptions=True)
        while self._idle:
            await self._idle.pop().ws.close()
        if self._session is not None:
            await self._session.close()
