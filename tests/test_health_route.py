"""HTTP-level regression tests for the lightweight health endpoint."""

import unittest
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.server.routes.health import health_check
from src.server import routes
from src.server.server import create_app
from src.server.state import state


class HealthRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoint_returns_readiness_json(self):
        """The endpoint must respond without depending on model or WebRTC work."""
        previous = (state.server_ready, state.model_ready, state.config)
        state.server_ready = True
        state.model_ready = True
        state.config = SimpleNamespace(
            model=SimpleNamespace(type="ernerf", avatar_id="demo"),
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
                    "avatar": {"type": "ernerf", "avatar_id": "demo"},
                    "vad": {"enabled": True, "type": "silero"},
                },
            )
        finally:
            await client.close()
            state.server_ready, state.model_ready, state.config = previous


class ServerRouteRegistrationTests(unittest.TestCase):
    def test_speech_path_picker_is_exported_and_registered(self):
        """Creating the app must not fail when registering the path picker."""
        self.assertTrue(callable(routes.pick_speech_path))

        app = create_app()
        registered = {
            (route.method, route.resource.canonical)
            for route in app.router.routes()
        }

        self.assertIn(("POST", "/api/speech/path-picker"), registered)
        self.assertIn(("GET", "/api/voice-tests"), registered)
        self.assertIn(("POST", "/api/voice-tests/run"), registered)
        self.assertIn(("DELETE", "/api/voice-tests"), registered)
