# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Edge synthesis rides out the service's 429 rate limiting."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_edge_endpoint import _handshake_error
from tests.test_edge_tts_worker import _mp3_fixture


class Parent:
    def __init__(self):
        self.frames = []
        self.failures = []

    def put_audio_frame(self, frame, eventpoint):
        self.frames.append(eventpoint)

    def on_fragment_synthesis_failed(self, textevent, reason):
        self.failures.append(reason)


class FakeEdge:
    """Hands out scripted connections in order and records how each ended."""

    def __init__(self, *behaviours):
        self.behaviours = list(behaviours)
        self.opened = 0
        self.closed = []
        self.payload = _mp3_fixture()

    def __call__(self, *_args):
        behaviour = self.behaviours[self.opened]
        index = self.opened
        self.opened += 1
        edge = self

        class Connection:
            async def stream(self):
                try:
                    if behaviour == "429":
                        raise _handshake_error(429)
                    yield {"type": "audio", "data": edge.payload}
                finally:
                    edge.closed.append(index)

        return Connection()


class EdgeResilienceTests(unittest.TestCase):
    def make_tts(self, parent):
        from src.tts.engines.edge import EdgeTTS

        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(
                ref_file="zh-TW-YunJheNeural",
                edge_persistent_worker=True,
                edge_prefetch=True,
            ),
        )
        tts = EdgeTTS(config, parent)
        self.addCleanup(tts.close_worker)
        return tts

    def speak(self, edge, textevent=None, *, uniform=None):
        parent = Parent()
        tts = self.make_tts(parent)
        patches = [
            patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=edge),
            patch("src.tts.engines.edge.random.uniform", side_effect=uniform or (lambda a, b: 0.0)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        tts.txt_to_audio(("測試首音。", dict(textevent or {})))
        return parent

    def test_a_429_is_retried_after_a_short_jittered_wait(self):
        waits = []

        def uniform(low, high):
            waits.append((low, high))
            return 0.0

        edge = FakeEdge("429", "ok")
        parent = self.speak(edge, uniform=uniform)

        self.assertTrue(parent.frames)
        self.assertEqual(edge.opened, 2)
        self.assertEqual(waits, [(0.2, 0.4)])

    def test_repeated_429_earns_exactly_one_extra_attempt(self):
        edge = FakeEdge("429", "429", "ok")
        parent = self.speak(edge)
        self.assertTrue(parent.frames)
        self.assertEqual(edge.opened, 3)

        edge = FakeEdge("429", "429", "429", "ok")
        parent = self.speak(edge)
        self.assertFalse(parent.frames)
        self.assertEqual(edge.opened, 3)


if __name__ == "__main__":
    unittest.main()
