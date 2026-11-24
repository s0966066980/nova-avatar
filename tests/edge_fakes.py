# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Edge TTS fixtures: a tiny MP3 and a rejected WebSocket handshake."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import aiohttp
import numpy as np


def _mp3_fixture() -> bytes:
    import av

    sample_rate = 24000
    tone_samples = int(sample_rate * 0.12)
    tone = (
        np.sin(2 * np.pi * 440 * np.arange(tone_samples) / sample_rate) * 8000
    ).astype(np.int16)
    output = BytesIO()
    with av.open(output, mode="w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=sample_rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            tone.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = sample_rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    payload = output.getvalue()
    marker = payload.find(b"\xff\xf3")
    return payload[marker:] if marker >= 0 else payload


def _handshake_error(status: int) -> aiohttp.WSServerHandshakeError:
    info = SimpleNamespace(real_url="wss://example.invalid/")
    return aiohttp.WSServerHandshakeError(info, (), status=status, message="rejected")
