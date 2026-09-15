# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Regression tests for console-triggered voice validation history."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.server.routes.voice_tests import run_voice_test
from src.server.state import state
from src.server.voice_test_history import VoiceTestHistory, evaluate_voice_test


def passing_metrics() -> dict:
    return {
        "turn_id": "turn-1",
        "first_audio_seconds": 1.4,
        "interrupt_stop_seconds": None,
        "listening_resume_seconds": None,
        "max_media_debt_seconds": 0.3,
        "max_abs_av_offset_seconds": 0.05,
        "stale_drops": {},
        "stage_seconds": {"llm_first_token": 0.2, "tts_first_pcm": 0.4},
    }


class VoiceTestEvaluationTests(unittest.TestCase):
    def test_existing_single_turn_gates_pass_and_multi_turn_gates_are_na(self):
        checks, passed = evaluate_voice_test("completed", passing_metrics(), "回答")

        self.assertTrue(passed)
        self.assertTrue(checks["first_audio_seconds"]["passed"])
        self.assertFalse(checks["interrupt_stop_seconds"]["applicable"])
        self.assertIsNone(checks["listening_resume_seconds"]["passed"])

    def test_missing_audio_or_stale_output_fails(self):
        metrics = passing_metrics()
        metrics["first_audio_seconds"] = None
        metrics["stale_drops"] = {"tts:cancelled": 1}

        checks, passed = evaluate_voice_test("completed", metrics, "回答")

        self.assertFalse(passed)
        self.assertFalse(checks["first_audio_seconds"]["passed"])
        self.assertFalse(checks["stale_drops_total"]["passed"])


class VoiceTestHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "voice-tests.json"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_run_is_persisted_then_completed_by_turn_id(self):
        history = VoiceTestHistory(self.path)
        started = history.begin(
            turn_id="turn-1",
            prompt="請自我介紹",
            session_id=123456,
            environment={"avatar": "musetalk", "reply_mode": "streaming"},
        )

        self.assertEqual(started["status"], "running")
        completed = history.complete(
            {
                "turn_id": "turn-1",
                "terminal_reason": "completed",
                "pipeline_mode": "streaming",
                "assistant_response": "你好，我是 Nova Avatar。",
                "metrics": passing_metrics(),
            }
        )

        self.assertTrue(completed["passed"])
        self.assertEqual(completed["status"], "passed")
        self.assertEqual(completed["assistant_response"], "你好，我是 Nova Avatar。")
        reloaded = VoiceTestHistory(self.path).list()
        self.assertEqual(reloaded[0]["prompt"], "請自我介紹")
        self.assertEqual(reloaded[0]["metrics"]["first_audio_seconds"], 1.4)

    def test_normal_conversation_metrics_are_not_persisted(self):
        history = VoiceTestHistory(self.path)
        self.assertIsNone(
            history.complete(
                {
                    "turn_id": "not-a-test",
                    "terminal_reason": "completed",
                    "assistant_response": "private conversation",
                    "metrics": passing_metrics(),
                }
            )
        )
        self.assertEqual(history.list(), [])

    def test_running_record_becomes_interrupted_after_restart(self):
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "results": [
                        {
                            "id": "record-1",
                            "turn_id": "turn-1",
                            "status": "running",
                            "passed": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        record = VoiceTestHistory(self.path).list()[0]

        self.assertEqual(record["status"], "interrupted")
        self.assertEqual(record["terminal_reason"], "server_restarted")
        self.assertFalse(record["passed"])

    def test_clear_returns_removed_count(self):
        history = VoiceTestHistory(self.path)
        history.begin(
            turn_id="turn-1",
            prompt="測試",
            session_id=1,
            environment={},
        )

        self.assertEqual(history.clear(), 1)
        self.assertEqual(history.list(), [])

    def test_running_state_is_exposed_for_safe_clear_guard(self):
        history = VoiceTestHistory(self.path)
        history.begin(
            turn_id="turn-1",
            prompt="測試",
            session_id=1,
            environment={},
        )
        self.assertTrue(history.has_running)

        history.complete(
            {
                "turn_id": "turn-1",
                "terminal_reason": "completed",
                "assistant_response": "回答",
                "metrics": passing_metrics(),
            }
        )
        self.assertFalse(history.has_running)


class _FakeVoiceSession:
    event_sink_ready = True

    async def start_text_turn(self, prompt, *, interrupt):
        self.prompt = prompt
        self.interrupt = interrupt
        return {
            "turn_id": "turn-route",
            "reply_mode": "streaming",
            "delivery": "events",
        }


class VoiceTestRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_registers_prompt_and_environment_without_interrupting(self):
        previous = (
            state.config,
            state.voice_test_history,
            state.voice_sessions,
            state.avatar_streams,
        )
        tempdir = tempfile.TemporaryDirectory()
        voice_session = _FakeVoiceSession()
        state.config = SimpleNamespace(
            model=SimpleNamespace(type="musetalk", avatar_id="avatar1"),
            llm=SimpleNamespace(provider="llamacpp", model="nova.gguf"),
            asr=SimpleNamespace(type="funasr"),
            tts=SimpleNamespace(type="edgetts"),
        )
        state.voice_test_history = VoiceTestHistory(
            Path(tempdir.name) / "history.json"
        )
        state.voice_sessions = {123456: voice_session}
        state.avatar_streams = {123456: object()}
        app = web.Application()
        app.router.add_post("/api/voice-tests/run", run_voice_test)
        client = TestClient(TestServer(app))

        try:
            await client.start_server()
            response = await client.post(
                "/api/voice-tests/run",
                json={
                    "sessionid": 123456,
                    "prompt": "請完整回答",
                    "label": "路由測試",
                },
            )
            payload = await response.json()

            self.assertEqual(response.status, 202)
            self.assertEqual(payload["turn_id"], "turn-route")
            self.assertEqual(payload["record"]["prompt"], "請完整回答")
            self.assertEqual(payload["record"]["environment"]["avatar"], "musetalk")
            self.assertEqual(payload["record"]["environment"]["llm"], "llamacpp")
            self.assertFalse(voice_session.interrupt)
        finally:
            await client.close()
            tempdir.cleanup()
            (
                state.config,
                state.voice_test_history,
                state.voice_sessions,
                state.avatar_streams,
            ) = previous
