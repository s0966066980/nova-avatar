# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Exercise startup and real synthesis against a local Edge protocol server."""
from __future__ import annotations

import asyncio
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import WSMsgType, web
from edge_tts import communicate

from src.server.app import _await_edge_tts_prewarm, _start_edge_tts_prewarm
from src.tts.engines import edge
from src.tts.edge_connection import EdgeConnectionPool
from tests.test_edge_tts_worker import _mp3_fixture


class FakeEdgeServer:
    def __init__(self):
        self.connections = 0
        self.requests = 0
        self.request_connections = []
        self.deny_new_connections = False
        self.close_after_request = False
        self.hold_end = False
        self.rate_limit = False
        self.handshakes = 0
        self.payload = _mp3_fixture()
        self.loop = asyncio.new_event_loop()
        self.ready = Event()
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            raise RuntimeError("Local Edge fixture did not start")

    def _run(self):
        asyncio.set_event_loop(self.loop)
        app = web.Application()
        app.router.add_get("/ws", self._handle)
        self.runner = web.AppRunner(app, access_log=None)
        self.loop.run_until_complete(self.runner.setup())
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        self.loop.run_until_complete(site.start())
        self.port = site._server.sockets[0].getsockname()[1]
        self.ready.set()
        self.loop.run_forever()
        self.loop.close()

    async def _handle(self, request):
        self.handshakes += 1
        if self.rate_limit:
            return web.Response(status=429, headers={"Retry-After": "5"})
        if self.deny_new_connections:
            return web.Response(status=503)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        connection_id = self.connections
        async for message in ws:
            if message.type == WSMsgType.TEXT and "Path:ssml" in message.data:
                self.requests += 1
                self.request_connections.append(connection_id)
                header = b"X-RequestId:test\r\nContent-Type:audio/mpeg\r\nPath:audio\r\n"
                frame = len(header).to_bytes(2, "big") + header + self.payload
                await ws.send_bytes(frame)
                if self.hold_end:
                    await ws.receive()
                    return ws
                await ws.send_str("X-RequestId:test\r\nPath:turn.end\r\n\r\n")
                if self.close_after_request:
                    await ws.close()
        return ws

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/ws?fixture=1"

    def stop(self):
        asyncio.run_coroutine_threadsafe(self.runner.cleanup(), self.loop).result(3)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)


class StartupConnectionTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeEdgeServer()
        self.addCleanup(self.server.stop)
        self.endpoint = patch.object(communicate, "WSS_URL", self.server.url)
        self.endpoint.start()
        self.addCleanup(self.endpoint.stop)
        self.addCleanup(lambda: getattr(edge, "shutdown_edge_tts", lambda: None)())
        self.config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(
                type="edgetts", ref_file="zh-TW-HsiaoChenNeural",
                edge_connection_reuse=True,
            ),
        )

    def synthesize(self):
        frames, failures = [], []
        parent = SimpleNamespace(
            put_audio_frame=lambda samples, _event: frames.append(samples),
            notify_fragment_synthesis_failed=lambda _event, reason: failures.append(reason),
        )
        tts = edge.EdgeTTS(self.config, parent)
        self.addCleanup(tts.close_worker)
        tts.txt_to_audio(("第一位訪客的回答。", {"turn_id": "first", "generation": 1}))
        return tts, frames, failures

    def test_startup_audio_is_available_without_another_handshake(self):
        worker = _start_edge_tts_prewarm(self.config)
        self.assertTrue(_await_edge_tts_prewarm(worker))
        # Once startup succeeds, new connection setup becomes unavailable.
        # The first visitor must still receive decoded PCM on the warm socket.
        self.server.deny_new_connections = True
        _tts, frames, failures = self.synthesize()
        self.assertTrue(frames, "the first answer lost the connection opened at startup")
        self.assertEqual(failures, [])

    def test_a_session_closing_keeps_the_startup_socket_available_for_other_sessions(self):
        self.assertTrue(_await_edge_tts_prewarm(_start_edge_tts_prewarm(self.config)))
        self.server.deny_new_connections = True
        first, frames, failures = self.synthesize()
        self.assertTrue(frames)
        shared_loop = first.worker_loop
        first.close_worker()
        second, frames, failures = self.synthesize()
        self.assertTrue(frames)
        self.assertEqual(failures, [])
        self.assertIs(second.worker_loop, shared_loop)

    def test_invalid_audio_never_marks_startup_ready(self):
        self.server.payload = b"invalid mp3"
        with patch("src.server.app.EDGE_PREWARM_RETRY_SECONDS", 0):
            self.assertFalse(_await_edge_tts_prewarm(_start_edge_tts_prewarm(self.config)))
        self.assertEqual(self.server.requests, 3)

    def test_backend_shutdown_closes_the_shared_loop_and_sockets(self):
        self.assertTrue(_await_edge_tts_prewarm(_start_edge_tts_prewarm(self.config)))
        worker = edge._ensure_shared_worker()
        edge.shutdown_edge_tts()
        self.assertTrue(worker.loop.is_closed())
        self.assertTrue(worker.pool._session.closed)
        self.assertFalse(worker.thread.is_alive())


class ConnectionPoolTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeEdgeServer()
        self.addCleanup(self.server.stop)

    def run_pool(self, scenario, **kwargs):
        async def run():
            pool = EdgeConnectionPool(url_factory=lambda: self.server.url, **kwargs)
            try:
                await scenario(pool)
            finally:
                await pool.close()
        asyncio.run(run())

    async def speak(self, pool):
        data = bytearray()
        async for chunk in pool.stream("測試。", "zh-TW-HsiaoChenNeural"):
            data.extend(chunk["data"])
        self.assertEqual(bytes(data), self.server.payload)

    def test_sequential_replies_reuse_connections(self):
        async def scenario(pool):
            for _ in range(3):
                await self.speak(pool)
            self.assertEqual(self.server.requests, 3)
            self.assertLessEqual(self.server.connections, 2)
        self.run_pool(scenario)

    def test_a_reused_socket_closed_by_the_peer_is_replaced_before_audio(self):
        self.server.close_after_request = True
        async def scenario(pool):
            await self.speak(pool)
            await asyncio.sleep(0.02)
            await self.speak(pool)
            self.assertEqual(self.server.requests, 2)
            self.assertNotEqual(*self.server.request_connections)
        self.run_pool(scenario)

    def test_expired_socket_is_replaced(self):
        now = [0.0]
        async def scenario(pool):
            await self.speak(pool)
            now[0] = 100.0
            await self.speak(pool)
            self.assertNotEqual(*self.server.request_connections)
        self.run_pool(scenario, clock=lambda: now[0])

    def test_refresh_replaces_the_old_socket_when_the_idle_pool_is_full(self):
        now = [0.0]
        async def scenario(pool):
            await self.speak(pool)
            now[0] = 50.0
            for _ in range(100):
                if self.server.connections >= 2:
                    break
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.02)
            self.assertEqual(self.server.connections, 2)
            self.assertEqual(pool.idle_count, 1)
            self.assertEqual(pool._idle[0].opened_at, 50.0)
        self.run_pool(scenario, clock=lambda: now[0], max_idle=1)

    def test_cancelled_request_discards_its_socket(self):
        self.server.hold_end = True
        async def scenario(pool):
            stream = pool.stream("取消。", "zh-TW-HsiaoChenNeural")
            await stream.__anext__()
            await stream.aclose()
            self.assertEqual(pool.idle_count, 0)
            self.server.hold_end = False
            await self.speak(pool)
            self.assertNotEqual(*self.server.request_connections)
        self.run_pool(scenario)

    def test_missing_audio_is_an_error_and_socket_is_not_reused(self):
        self.server.payload = b""
        async def scenario(pool):
            with self.assertRaisesRegex(RuntimeError, "without audio"):
                await self.speak(pool)
            self.assertEqual(pool.idle_count, 0)
        self.run_pool(scenario)

    def test_background_connection_failures_back_off(self):
        async def scenario(pool):
            with patch.object(pool, "_open", new_callable=AsyncMock, side_effect=ConnectionError) as connect:
                pool.ensure_warm()
                await asyncio.sleep(0.02)
                self.assertEqual(connect.await_count, 1)
        self.run_pool(scenario)

    def test_rate_limit_cooldown_is_shared_with_new_requests_and_is_cancellable(self):
        self.server.rate_limit = True
        async def scenario(pool):
            from aiohttp import WSServerHandshakeError
            with self.assertRaises(WSServerHandshakeError):
                await self.speak(pool)
            # A new request during Retry-After waits without another handshake;
            # its caller can still cancel promptly during that wait.
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(self.speak(pool), timeout=0.03)
            self.assertEqual(self.server.handshakes, 1)
        self.run_pool(scenario)

    def test_concurrent_requests_can_prune_multiple_expired_sockets(self):
        async def scenario(pool):
            release = asyncio.Event()
            async def close():
                await release.wait()
            sockets = [SimpleNamespace(closed=False, close=AsyncMock(side_effect=close)) for _ in range(2)]
            pool._idle = [SimpleNamespace(ws=socket, opened_at=0.0) for socket in sockets]
            first = asyncio.create_task(pool._prune_expired())
            await asyncio.sleep(0)
            second = asyncio.create_task(pool._prune_expired())
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)
            self.assertEqual(pool.idle_count, 0)
            for socket in sockets:
                socket.close.assert_awaited_once()
        self.run_pool(scenario, clock=lambda: 100.0)


if __name__ == "__main__":
    unittest.main()
