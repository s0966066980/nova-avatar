# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Edge connections are reused so synthesis does not wait for connection setup."""
from __future__ import annotations

import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import WSMsgType, web

from src.tts.edge_connection import EdgeConnectionPool
from tests.test_edge_tts_worker import _mp3_fixture

PAYLOAD = _mp3_fixture()
VOICE = "zh-TW-HsiaoChenNeural"


def _audio_frame(payload: bytes) -> bytes:
    # Edge framing: 2-byte header length, header text, then the audio.
    header = b"X-RequestId:test\r\nContent-Type:audio/mpeg\r\nPath:audio\r\n"
    return len(header).to_bytes(2, "big") + header + payload


class FakeEdgeServer:
    """A local WebSocket endpoint that answers SSML like the Edge service."""

    def __init__(self):
        self.connections = 0
        self.requests = 0
        self.close_after_first_request = False
        self.disconnected = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        app = web.Application()
        app.router.add_get("/ws", self._handle)
        self._runner = web.AppRunner(app)
        self._loop.run_until_complete(self._runner.setup())
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        self._loop.run_until_complete(site.start())
        self.port = site._server.sockets[0].getsockname()[1]
        self._ready.set()
        self._loop.run_forever()

    async def _handle(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        async for message in ws:
            if message.type == WSMsgType.TEXT and "Path:ssml" in message.data:
                self.requests += 1
                await ws.send_str("X-RequestId:test\r\nPath:turn.start\r\n\r\n{}")
                await ws.send_bytes(_audio_frame(PAYLOAD))
                await ws.send_str("X-RequestId:test\r\nPath:turn.end\r\n\r\n{}")
                if self.close_after_first_request:
                    await ws.close()
        self.disconnected.set()
        return ws

    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws?test=1"

    def stop(self):
        async def shutdown():
            await self._runner.cleanup()
        asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)


async def _speak(pool, text="測試。") -> int:
    size = 0
    async for chunk in pool.stream(text, VOICE):
        assert chunk["type"] == "audio"
        size += len(chunk["data"])
    return size


class EdgeConnectionPoolTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeEdgeServer()
        self.addCleanup(self.server.stop)

    def run_pool(self, scenario, **pool_kwargs):
        async def main():
            pool = EdgeConnectionPool(url_factory=self.server.url, **pool_kwargs)
            try:
                return await scenario(pool)
            finally:
                await pool.close()
        return asyncio.run(main())

    def test_sequential_requests_share_one_connection(self):
        async def scenario(pool):
            sizes = [await _speak(pool), await _speak(pool), await _speak(pool)]
            return sizes, pool.opened, pool.reused

        sizes, opened, reused = self.run_pool(scenario)
        self.assertTrue(all(size == len(PAYLOAD) for size in sizes))
        # Only the first request pays for a connection; at most one more is
        # opened in the background as the spare.
        self.assertEqual(reused, 2)
        self.assertLessEqual(opened, 2)
        self.assertEqual(self.server.requests, 3)

    def test_a_warm_spare_serves_the_first_request(self):
        async def scenario(pool):
            pool.ensure_warm()
            for _ in range(100):
                if pool.idle_count:
                    break
                await asyncio.sleep(0.01)
            await _speak(pool)
            return pool.opened, pool.reused

        self.assertEqual(self.run_pool(scenario), (1, 1))

    def test_a_connection_closed_while_idle_is_replaced_without_failing(self):
        self.server.close_after_first_request = True

        async def scenario(pool):
            await _speak(pool)
            await asyncio.sleep(0.1)
            return await _speak(pool), pool.opened

        size, opened = self.run_pool(scenario)
        self.assertEqual(size, len(PAYLOAD))
        self.assertEqual(opened, 2)

    def test_an_old_idle_connection_is_not_reused(self):
        now = [0.0]

        async def scenario(pool):
            await _speak(pool)
            now[0] = 1000.0
            await _speak(pool)
            return pool.opened, pool.reused

        opened, reused = self.run_pool(scenario, clock=lambda: now[0], max_age=240.0)
        self.assertEqual(reused, 0)
        self.assertEqual(self.server.requests, 2)

    def test_an_interrupted_request_does_not_return_its_connection(self):
        async def scenario(pool):
            stream = pool.stream("測試。", VOICE).__aiter__()
            await stream.__anext__()
            await stream.aclose()
            idle_after_interrupt = pool.idle_count
            closed = await asyncio.to_thread(self.server.disconnected.wait, 2)
            return idle_after_interrupt, closed, await _speak(pool)

        idle_after_interrupt, closed, size = self.run_pool(scenario)
        self.assertEqual(idle_after_interrupt, 0)
        self.assertTrue(closed, "the interrupted connection must be closed, not pooled")
        self.assertEqual(size, len(PAYLOAD))

    def test_an_idle_spare_is_replaced_before_it_expires(self):
        async def scenario(pool):
            pool.ensure_warm()
            await asyncio.sleep(0.9)
            fresh_idle = pool.idle_count
            size = await _speak(pool)
            return pool.opened, fresh_idle, size

        opened, fresh_idle, size = self.run_pool(scenario, max_age=0.3)
        self.assertGreaterEqual(opened, 3, "the spare must be refreshed while idle")
        self.assertGreaterEqual(fresh_idle, 1)
        self.assertEqual(size, len(PAYLOAD))

    def test_close_releases_idle_connections(self):
        async def scenario(pool):
            await _speak(pool)
            return pool.idle_count

        self.assertEqual(self.run_pool(scenario), 1)
        self.assertTrue(self.server.disconnected.wait(2))


class EdgeTTSConnectionReuseTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeEdgeServer()
        self.addCleanup(self.server.stop)

    def make_tts(self, *, reuse):
        from src.tts.engines.edge import EdgeTTS

        frames = []
        parent = SimpleNamespace(put_audio_frame=lambda frame, eventpoint: frames.append(eventpoint))
        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(
                ref_file=VOICE,
                edge_persistent_worker=True,
                edge_prefetch=True,
                edge_connection_reuse=reuse,
            ),
        )
        tts = EdgeTTS(config, parent)
        self.addCleanup(tts.close_worker)
        return tts, frames

    def test_replies_reuse_one_edge_connection(self):
        tts, frames = self.make_tts(reuse=True)
        with patch(
            "src.tts.engines.edge.EdgeConnectionPool",
            side_effect=lambda: EdgeConnectionPool(url_factory=self.server.url),
        ), patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=AssertionError("the pool path must not open per-request connections"),
        ):
            tts.txt_to_audio(("第一句。", {}))
            tts.txt_to_audio(("第二句。", {}))

        self.assertTrue(frames)
        self.assertEqual(self.server.connections, 1)
        self.assertEqual(self.server.requests, 2)

    def test_closing_the_worker_closes_the_pool(self):
        tts, _frames = self.make_tts(reuse=True)
        with patch(
            "src.tts.engines.edge.EdgeConnectionPool",
            side_effect=lambda: EdgeConnectionPool(url_factory=self.server.url),
        ):
            tts.txt_to_audio(("一句話。", {}))
            tts.close_worker()

        self.assertTrue(self.server.disconnected.wait(2))

    def test_reuse_disabled_keeps_edge_tts_connection_per_request(self):
        tts, frames = self.make_tts(reuse=False)

        class Communicate:
            async def stream(self):
                yield {"type": "audio", "data": PAYLOAD}

        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: Communicate(),
        ) as communicate:
            tts.txt_to_audio(("一句話。", {}))

        self.assertTrue(frames)
        communicate.assert_called_once()
        self.assertEqual(self.server.connections, 0)


if __name__ == "__main__":
    unittest.main()
