"""HTTP-level regression tests for the lightweight health endpoint."""

import unittest
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from nova_llm.adapter import InProcessLlmService
from nova_core.server.routes.health import health_check
from nova_core.server.state import state


class HealthRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoint_returns_readiness_json(self):
        """The endpoint must respond without depending on model or WebRTC work."""
        previous = (state.server_ready, state.model_ready, state.config)
        state.server_ready = True
        state.model_ready = True
        state.config = SimpleNamespace(
            model=SimpleNamespace(type="musetalk", avatar_id="demo"),
            vad=SimpleNamespace(enabled=True, type="silero"),
        )
        app = web.Application()
        app.router.add_get("/health", health_check)
        server = TestServer(app)
        client = TestClient(server)

        try:
            await client.start_server()
            response = await client.get("/health")
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(
                await response.json(),
                {
                    "code": 0,
                    "ready": True,
                    "model_ready": True,
                    "avatar": {"type": "musetalk", "avatar_id": "demo"},
                    "vad": {"enabled": True, "type": "silero"},
                },
            )
        finally:
            await client.close()
            state.server_ready, state.model_ready, state.config = previous


class HealthLlmGpuWarningTests(unittest.TestCase):
    """Public /health carries one boolean for the GPU warning, never layer or VRAM detail."""

    def _payload(self, provider, offload):
        import asyncio
        import json
        from unittest.mock import patch

        previous = (state.server_ready, state.config, state.llm)
        state.server_ready = True
        state.llm = InProcessLlmService()
        state.config = SimpleNamespace(
            model=SimpleNamespace(type="musetalk", avatar_id="demo"),
            vad=SimpleNamespace(enabled=False, type="silero"),
            llm=SimpleNamespace(provider=provider),
        )
        try:
            with patch("nova_llm.llamacpp.gpu_offload_status", return_value=offload):
                return json.loads(asyncio.run(health_check(None)).text)
        finally:
            state.server_ready, state.config, state.llm = previous

    def test_partial_offload_is_flagged_without_detail(self):
        payload = self._payload("llamacpp", {
            "full": False, "gpu_layers": 31, "total_layers": 32, "error": "顯存不足 pid 4242",
        })
        self.assertIs(payload["llm_full_gpu"], False)
        self.assertNotIn("31", json_text(payload))
        self.assertNotIn("4242", json_text(payload))

    def test_full_gpu_is_reported(self):
        payload = self._payload("llamacpp", {
            "full": True, "gpu_layers": 32, "total_layers": 32, "error": "",
        })
        self.assertIs(payload["llm_full_gpu"], True)

    def test_field_absent_when_unknown_or_not_local(self):
        self.assertNotIn("llm_full_gpu", self._payload("llamacpp", None))
        self.assertNotIn("llm_full_gpu", self._payload("ollama", {"full": False}))


def json_text(payload):
    import json

    return json.dumps(payload, ensure_ascii=False)


