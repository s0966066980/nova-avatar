# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Pick the Edge TTS WebSocket host and fail over when one rejects the handshake.

In October 2026 the legacy ``speech.platform.bing.com`` synthesis endpoint began
answering the WebSocket handshake with HTTP 403 for edge-tts 7.2.8 and earlier
(upstream rany2/edge-tts issue #490). Microsoft's own client moved to
``api.msedgeservices.com``, which still accepts the same token and handshake
headers. This module points the installed edge-tts package at that host first
and swaps to the other host when a handshake is rejected, so a single host going
away does not silence every reply.

The swap is process-wide and sticky: the host that last worked stays in use.
"""
from __future__ import annotations

import threading

import aiohttp
from edge_tts import communicate as _communicate
from edge_tts import constants as _constants

from src.utils.logging import logger

PRIMARY_WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    f"?Ocp-Apim-Subscription-Key={_constants.TRUSTED_CLIENT_TOKEN}"
)
FALLBACK_WSS_URL = _constants.WSS_URL

_REJECTED_STATUSES = frozenset({401, 403, 404})

_lock = threading.Lock()
_urls = (PRIMARY_WSS_URL, FALLBACK_WSS_URL)
_index = 0


def current_url() -> str:
    return _urls[_index]


def _install(url: str) -> bool:
    # edge-tts reads WSS_URL from its communicate module when it opens a socket.
    if not hasattr(_communicate, "WSS_URL"):
        logger.warning("edge-tts no longer exposes WSS_URL; Edge host selection skipped")
        return False
    _communicate.WSS_URL = url
    return True


def apply() -> None:
    """Point edge-tts at the host currently in use. Safe to call repeatedly."""
    with _lock:
        _install(current_url())


def is_handshake_rejection(exc: BaseException | None) -> bool:
    return (
        isinstance(exc, aiohttp.WSServerHandshakeError)
        and exc.status in _REJECTED_STATUSES
    )


def is_rate_limited(exc: BaseException | None) -> bool:
    """The service answered the handshake with 429; the host itself is fine."""
    return isinstance(exc, aiohttp.WSServerHandshakeError) and exc.status == 429


def note_failure(exc: BaseException | None) -> bool:
    """Swap to the other host when ``exc`` is a rejected handshake.

    Returns whether a swap happened. Other failures, such as timeouts or a
    broken stream, say nothing about the host and leave the choice unchanged.
    """
    global _index
    if not is_handshake_rejection(exc):
        return False
    with _lock:
        previous = current_url()
        next_index = (_index + 1) % len(_urls)
        if not _install(_urls[next_index]):
            return False
        _index = next_index
    logger.warning(
        "Edge TTS handshake rejected (%s); switching host %s -> %s",
        exc.status,
        previous.split("?", 1)[0],
        current_url().split("?", 1)[0],
    )
    return True


def reset() -> None:
    """Return to the primary host. Intended for tests."""
    global _index
    with _lock:
        _index = 0
        _install(_urls[0])


apply()
