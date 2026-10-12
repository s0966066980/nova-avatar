# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Reuse Edge TTS WebSocket connections so synthesis skips connection setup.

edge-tts opens a new TCP + TLS + WebSocket connection for every request. On the
field host that setup occasionally stalls for 1-10 s (packet loss on the path
to the service), while a request on an open connection answers in 0.1-0.3 s.
One open connection serves any number of sequential requests and stays usable
for at least a minute of idle time, so this pool keeps a spare connection ready
and puts used ones back. A stalled setup then happens in the background
instead of in front of the visitor.

The protocol messages come from edge-tts itself; only connection ownership
differs from ``edge_tts.Communicate``.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional
from xml.sax.saxutils import escape

import aiohttp
from edge_tts import communicate as _edge
from edge_tts.data_classes import TTSConfig
from edge_tts.drm import DRM

from src.utils.logging import logger

# Idle connections older than this are not used: a minute of idle time is
# verified against the service, longer is not, and the URL token is time-based.
MAX_IDLE_AGE_SECONDS = 60.0
# A kiosk can sit idle for hours, so the spare is replaced this long before it
# expires; the visitor's first sentence never waits for a connection setup.
REFRESH_BEFORE_EXPIRY_SECONDS = 10.0
MAX_IDLE_CONNECTIONS = 2
# Upper bound for one request on an open connection to answer at all.
RESPONSE_TIMEOUT_SECONDS = 15.0
# Background warm-up failures (for example a 429) wait this long before trying again.
WARM_RETRY_SECONDS = 15.0
_MAX_REQUEST_BYTES = 4096

_SPEECH_CONFIG = (
    "X-Timestamp:{timestamp}\r\n"
    "Content-Type:application/json; charset=utf-8\r\n"
    "Path:speech.config\r\n\r\n"
    '{{"context":{{"synthesis":{{"audio":{{"metadataoptions":{{'
    '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"}},'
    '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}}}}}\r\n'
)


class StaleConnection(Exception):
    """A reused connection closed before it produced any audio."""


@dataclass
class _Connection:
    ws: aiohttp.ClientWebSocketResponse
    opened_at: float


def _default_url() -> str:
    # edge_endpoint swaps edge-tts's WSS_URL when a host rejects handshakes;
    # read it at connect time so both paths follow the same host.
    return (
        f"{_edge.WSS_URL}&ConnectionId={_edge.connect_id()}"
        f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
        f"&Sec-MS-GEC-Version={_edge.SEC_MS_GEC_VERSION}"
    )


class EdgeConnectionPool:
    """Open Edge connections owned by one event loop."""

    def __init__(
        self,
        *,
        url_factory: Callable[[], str] = _default_url,
        clock: Callable[[], float] = time.monotonic,
        max_idle: int = MAX_IDLE_CONNECTIONS,
        max_age: float = MAX_IDLE_AGE_SECONDS,
    ) -> None:
        self._url_factory = url_factory
        self._clock = clock
        self._max_idle = max_idle
        self._max_age = max_age
        self._idle: deque[_Connection] = deque()
        self._session: Optional[aiohttp.ClientSession] = None
        self._warm_task: Optional[asyncio.Task] = None
        self._closed = False
        self.opened = 0
        self.reused = 0

    @property
    def idle_count(self) -> int:
        return len(self._idle)

    async def _open(self) -> _Connection:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(trust_env=True)
        ws = await self._session.ws_connect(
            self._url_factory(),
            compress=15,
            headers=DRM.headers_with_muid(_edge.WSS_HEADERS),
            ssl=_edge._SSL_CTX,
        )
        self.opened += 1
        return _Connection(ws=ws, opened_at=self._clock())

    def _take_idle(self) -> Optional[_Connection]:
        while self._idle:
            connection = self._idle.pop()
            fresh = self._clock() - connection.opened_at < self._max_age
            if fresh and not connection.ws.closed:
                return connection
            asyncio.ensure_future(connection.ws.close())
        return None

    def _put_back(self, connection: _Connection) -> None:
        if self._closed or connection.ws.closed or len(self._idle) >= self._max_idle:
            asyncio.ensure_future(connection.ws.close())
            return
        self._idle.append(connection)

    def ensure_warm(self) -> None:
        """Keep a fresh spare connection ready in the background."""
        if self._closed:
            return
        if self._warm_task is not None and not self._warm_task.done():
            return
        self._warm_task = asyncio.ensure_future(self._keep_warm())

    def _prune_expired(self) -> None:
        now = self._clock()
        for connection in list(self._idle):
            if connection.ws.closed or now - connection.opened_at >= self._max_age:
                self._idle.remove(connection)
                asyncio.ensure_future(connection.ws.close())

    async def _keep_warm(self) -> None:
        refresh_age = max(self._max_age - REFRESH_BEFORE_EXPIRY_SECONDS, self._max_age / 2)
        while not self._closed:
            self._prune_expired()
            newest = self._idle[-1] if self._idle else None
            age = None if newest is None else self._clock() - newest.opened_at
            if age is not None and age < refresh_age:
                await asyncio.sleep(max(refresh_age - age, 0.05))
                continue
            try:
                connection = await self._open()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Edge TTS spare connection failed: %s", exc)
                await asyncio.sleep(WARM_RETRY_SECONDS)
                continue
            self._put_back(connection)

    async def stream(self, text: str, voice: str) -> AsyncIterator[dict]:
        """Yield ``{"type": "audio", "data": bytes}`` chunks for ``text``.

        A reused connection that turns out to be closed is replaced once,
        transparently, before any audio has been yielded.
        """
        config = TTSConfig(voice, "+0%", "+0%", "+0Hz", "SentenceBoundary")
        requests = _edge.split_text_by_byte_length(
            escape(_edge.remove_incompatible_characters(text)), _MAX_REQUEST_BYTES
        )
        connection = self._take_idle()
        reused = connection is not None
        if connection is None:
            connection = await self._open()
        else:
            self.reused += 1
        clean = False
        try:
            yielded = False
            for index, request in enumerate(requests):
                while True:
                    try:
                        async for chunk in self._request(connection, config, request):
                            yielded = True
                            yield chunk
                        break
                    except StaleConnection:
                        if yielded or not reused or index:
                            raise
                        await connection.ws.close()
                        connection = await self._open()
                        reused = False
            clean = True
        finally:
            if clean:
                self._put_back(connection)
            else:
                # Cancelled or failed mid-request: the socket state is unknown.
                await connection.ws.close()
            self.ensure_warm()

    async def _request(
        self, connection: _Connection, config: TTSConfig, request: bytes
    ) -> AsyncIterator[dict]:
        ws = connection.ws
        try:
            await ws.send_str(_SPEECH_CONFIG.format(timestamp=_edge.date_to_string()))
            await ws.send_str(
                _edge.ssml_headers_plus_data(
                    _edge.connect_id(), _edge.date_to_string(), _edge.mkssml(config, request)
                )
            )
        except (ConnectionError, aiohttp.ClientError, RuntimeError) as exc:
            raise StaleConnection(str(exc)) from exc
        audio_seen = False
        while True:
            message = await asyncio.wait_for(ws.receive(), timeout=RESPONSE_TIMEOUT_SECONDS)
            if message.type == aiohttp.WSMsgType.TEXT:
                if "Path:turn.end" in message.data:
                    if not audio_seen:
                        raise RuntimeError("Edge TTS turn ended without audio")
                    return
                continue
            if message.type == aiohttp.WSMsgType.BINARY:
                data = message.data
                if len(data) < 2:
                    continue
                # Same framing as edge-tts: a 2-byte header length, headers, audio.
                header_length = int.from_bytes(data[:2], "big")
                headers, payload = _edge.get_headers_and_data(data, header_length)
                if headers.get(b"Path") == b"audio" and payload:
                    audio_seen = True
                    yield {"type": "audio", "data": payload}
                continue
            if not audio_seen:
                raise StaleConnection(f"socket {message.type.name}")
            raise ConnectionError(f"Edge TTS socket {message.type.name} mid-stream")

    async def close(self) -> None:
        self._closed = True
        if self._warm_task is not None:
            self._warm_task.cancel()
            try:
                await self._warm_task
            except BaseException:
                pass
        while self._idle:
            await self._idle.pop().ws.close()
        if self._session is not None:
            await self._session.close()
