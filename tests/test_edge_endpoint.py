# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Edge TTS host selection survives one host rejecting the WebSocket handshake."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
from edge_tts import communicate

from src.tts import edge_endpoint
from tests.test_edge_tts_worker import _mp3_fixture


def _handshake_error(status: int) -> aiohttp.WSServerHandshakeError:
    info = SimpleNamespace(real_url="wss://example.invalid/")
    return aiohttp.WSServerHandshakeError(info, (), status=status, message="rejected")


class EdgeEndpointTests(unittest.TestCase):
    def setUp(self):
        edge_endpoint.reset()
        self.addCleanup(edge_endpoint.reset)

    def test_edge_tts_is_pointed_at_the_primary_host_on_import(self):
        self.assertEqual(communicate.WSS_URL, edge_endpoint.PRIMARY_WSS_URL)
        self.assertNotEqual(
            edge_endpoint.PRIMARY_WSS_URL, edge_endpoint.FALLBACK_WSS_URL
        )

    def test_rejected_handshake_swaps_host_and_swaps_back_on_next_rejection(self):
        self.assertTrue(edge_endpoint.note_failure(_handshake_error(403)))
        self.assertEqual(communicate.WSS_URL, edge_endpoint.FALLBACK_WSS_URL)
        self.assertTrue(edge_endpoint.note_failure(_handshake_error(403)))
        self.assertEqual(communicate.WSS_URL, edge_endpoint.PRIMARY_WSS_URL)

    def test_failures_that_do_not_name_a_bad_host_keep_the_choice(self):
        for exc in (
            _handshake_error(500),
            RuntimeError("Edge TTS returned no decodable audio"),
            TimeoutError(),
            None,
        ):
            with self.subTest(exc=repr(exc)):
                self.assertFalse(edge_endpoint.note_failure(exc))
                self.assertEqual(communicate.WSS_URL, edge_endpoint.PRIMARY_WSS_URL)

    def test_missing_wss_url_attribute_disables_selection_without_raising(self):
        with patch.object(communicate, "WSS_URL", create=True):
            del communicate.WSS_URL
            self.assertFalse(edge_endpoint.note_failure(_handshake_error(403)))
            self.assertEqual(edge_endpoint.current_url(), edge_endpoint.PRIMARY_WSS_URL)

    def test_prewarm_rejection_retries_the_other_host_before_first_turn(self):
        from src.tts.engines.edge import prewarm_edge_tts

        attempted_urls = []

        class Rejected:
            async def stream(self):
                attempted_urls.append(communicate.WSS_URL)
                raise _handshake_error(403)
                yield  # pragma: no cover

        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: Rejected(),
        ):
            self.assertFalse(prewarm_edge_tts("zh-TW-YunJheNeural", timeout_seconds=1))

        self.assertEqual(attempted_urls, [edge_endpoint.PRIMARY_WSS_URL, edge_endpoint.FALLBACK_WSS_URL])
        # Both hosts rejected prewarm. Ordinary request recovery should begin
        # at the host other than the last rejected one.
        self.assertEqual(communicate.WSS_URL, edge_endpoint.PRIMARY_WSS_URL)


class EdgeWorkerHostFailoverTests(unittest.TestCase):
    def setUp(self):
        edge_endpoint.reset()
        self.addCleanup(edge_endpoint.reset)

    def test_first_attempt_rejection_retries_on_the_other_host_and_speaks(self):
        from src.tts.engines.edge import EdgeTTS

        payload = _mp3_fixture()
        hosts_used = []
        frames = []

        class Parent:
            def put_audio_frame(self, frame, _eventpoint):
                frames.append(frame)

        class Rejected:
            async def stream(self):
                hosts_used.append(communicate.WSS_URL)
                raise _handshake_error(403)
                yield  # pragma: no cover

        class Working:
            async def stream(self):
                hosts_used.append(communicate.WSS_URL)
                yield {"type": "audio", "data": payload}

        communicates = [Rejected, Working]
        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(
                ref_file="zh-TW-YunJheNeural",
                edge_persistent_worker=True,
                edge_prefetch=True,
            ),
        )
        tts = EdgeTTS(config, Parent())
        self.addCleanup(tts.close_worker)

        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: communicates.pop(0)(),
        ):
            tts.txt_to_audio(("你好。", {}))

        self.assertEqual(
            hosts_used,
            [edge_endpoint.PRIMARY_WSS_URL, edge_endpoint.FALLBACK_WSS_URL],
        )
        self.assertTrue(frames)


if __name__ == "__main__":
    unittest.main()
