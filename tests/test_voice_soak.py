# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Deterministic tests for the 50-turn prerecorded soak harness and recovery probes."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

import numpy as np

from scripts.run_voice_soak import (
    EventBroker,
    SoakPeer,
    parse_args,
    resolve_environment,
    run as run_soak,
)
from src.server.reply_streaming.soak import (
    build_soak_report,
    sample_rss_mb,
    summarize_memory_trend,
)


def _sample_turn(index: int, *, first_audio: float = 0.9) -> dict:
    return {
        "turn_id": f"turn-{index}",
        "first_audio_seconds": first_audio,
        "interrupt_stop_seconds": 0.12 if index % 10 == 9 else None,
        "listening_resume_seconds": 0.35 if index % 10 == 9 else None,
        "max_media_debt_seconds": 1.1,
        "max_abs_av_offset_seconds": 0.03,
        "stale_drops": {},
        "stage_seconds": {
            "vad_endpoint": 0.05,
            "asr": 0.18,
            "llm_first_token": 0.22,
            "tts_first_pcm": 0.35,
            "webrtc_audio_commit": 0.04,
        },
    }


class VoiceSoakProfileAndGatingTests(unittest.TestCase):
    def test_cli_accepts_prerecorded_profile_and_configurable_thresholds(self):
        args = parse_args(
            [
                "--presentation",
                "prerecorded",
                "--profile",
                "jetson-orin-prerecorded",
                "--max-first-audio-p50",
                "1.8",
                "--max-first-audio-p95",
                "3.2",
                "--output",
                "logs/orin-prerecorded-soak.json",
            ]
        )

        env = resolve_environment(
            args,
            health={
                "avatar": {"type": "musetalk", "avatar_id": "musetalk_1"},
                "vad": {"enabled": True, "type": "silero"},
            },
        )

        self.assertEqual(args.presentation, "prerecorded")
        self.assertEqual(args.profile, "jetson-orin-prerecorded")
        self.assertEqual(args.max_first_audio_p50, 1.8)
        self.assertEqual(args.max_first_audio_p95, 3.2)
        self.assertEqual(str(args.output), "logs/orin-prerecorded-soak.json")
        self.assertEqual(env["presentation"], "prerecorded")
        self.assertEqual(env["profile"], "jetson-orin-prerecorded")
        self.assertIn("Orin", env["gpu"])
        self.assertEqual(env["avatar"], "Prerecorded")
        self.assertEqual(env["avatar_id"], "musetalk_1")
        self.assertEqual(env["vad"], "silero")

    def test_build_soak_report_gates_50_turns_against_custom_first_audio_slos(self):
        turns = [_sample_turn(i, first_audio=1.6 if i < 40 else 2.8) for i in range(50)]

        passing = build_soak_report(
            turns,
            scenario_counts={"short": 45, "interrupt": 5},
            stale_events=0,
            environment={"presentation": "prerecorded", "profile": "jetson-orin-prerecorded"},
            max_first_audio_p50=1.8,
            max_first_audio_p95=3.2,
        )
        failing = build_soak_report(
            turns,
            scenario_counts={"short": 45, "interrupt": 5},
            stale_events=0,
            environment={"presentation": "prerecorded", "profile": "jetson-orin-prerecorded"},
            max_first_audio_p50=1.2,
            max_first_audio_p95=2.5,
        )

        self.assertTrue(passing["slo_pass"])
        self.assertTrue(passing["checks"]["first_audio_p50"])
        self.assertTrue(passing["checks"]["first_audio_p95"])
        self.assertEqual(passing["metrics"]["first_audio_seconds"]["target_p50_at_most"], 1.8)
        self.assertEqual(passing["metrics"]["first_audio_seconds"]["target_p95_at_most"], 3.2)

        self.assertFalse(failing["slo_pass"])
        self.assertFalse(failing["checks"]["first_audio_p50"])
        self.assertFalse(failing["checks"]["first_audio_p95"])
        self.assertNotIn("transcript", json.dumps(passing))


class BargeInAndStaleOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_barge_in_interrupt_sends_interrupt_and_collects_metrics(self):
        class FakeChannel:
            def __init__(self, broker: EventBroker) -> None:
                self.sent: list[dict] = []
                self._broker = broker

            def send(self, raw: str) -> None:
                payload = json.loads(raw)
                self.sent.append(payload)
                if payload.get("type") == "interrupt":
                    self._broker.receive(
                        json.dumps({"type": "turn_cancelled", "turn_id": "t-1"})
                    )
                    self._broker.receive(
                        json.dumps(
                            {
                                "type": "turn_metrics",
                                "turn_id": "t-1",
                                "metrics": _sample_turn(9, first_audio=0.8),
                            }
                        )
                    )
                    self._broker.receive(
                        json.dumps({"type": "state", "state": "listening"})
                    )

        peer = SoakPeer.__new__(SoakPeer)
        peer.events = EventBroker()
        peer.audio = type("Audio", (), {"push": lambda _self, _samples: None})()
        peer.channel = FakeChannel(peer.events)

        peer.events.receive(json.dumps({"type": "user_transcript", "turn_id": "t-1"}))
        peer.events.receive(json.dumps({"type": "speaking_start", "turn_id": "t-1"}))

        metrics = await peer.run_turn(np.ones(320, dtype=np.int16), "interrupt")

        self.assertEqual(peer.channel.sent, [{"type": "interrupt"}])
        self.assertEqual(metrics["turn_id"], "turn-9")
        self.assertEqual(peer.events.stale_events, 0)

    def test_event_broker_detects_all_stale_output_types_after_turn_cancelled(self):
        broker = EventBroker()
        broker.receive(json.dumps({"type": "turn_cancelled", "turn_id": "turn-7"}))
        # Lifecycle telemetry after cancel must not count as stale output
        broker.receive(json.dumps({"type": "state", "state": "tail_guard", "turn_id": "turn-7"}))
        broker.receive(json.dumps({"type": "turn_metrics", "turn_id": "turn-7", "metrics": {}}))
        self.assertEqual(broker.stale_events, 0)

        # Any output event for a cancelled turn is stale output
        broker.receive(json.dumps({"type": "assistant_fragment", "turn_id": "turn-7"}))
        broker.receive(json.dumps({"type": "assistant_response_delta", "turn_id": "turn-7"}))
        broker.receive(json.dumps({"type": "speaking_start", "turn_id": "turn-7"}))
        broker.receive(json.dumps({"type": "assistant_board", "turn_id": "turn-7"}))
        self.assertEqual(broker.stale_events, 4)

        report = build_soak_report(
            [_sample_turn(i) for i in range(50)],
            scenario_counts={"short": 45, "interrupt": 5},
            stale_events=broker.stale_events,
            environment={"presentation": "prerecorded"},
        )
        self.assertFalse(report["checks"]["stale_output"])
        self.assertFalse(report["slo_pass"])
        self.assertEqual(report["stale_output_events"], 4)


class RejectedSpeechTurnTests(unittest.IsolatedAsyncioTestCase):
    def _make_peer(self) -> SoakPeer:
        peer = SoakPeer.__new__(SoakPeer)
        peer.events = EventBroker()
        peer.audio = type("Audio", (), {"push": lambda _self, _samples: None})()
        peer.channel = type("Channel", (), {"send": lambda _self, _msg: None})()
        return peer

    async def test_explicit_speech_input_rejected_recovers_without_waiting_for_transcript(self):
        peer = self._make_peer()
        peer.events.receive(
            json.dumps(
                {
                    "type": "speech_input_rejected",
                    "speech_input_rejection_reason": "audio_too_quiet",
                    "turn_id": "rej-1",
                }
            )
        )
        peer.events.receive(json.dumps({"type": "state", "state": "listening"}))

        result = await asyncio.wait_for(
            peer.run_rejected_turn(np.ones(320, dtype=np.int16), "low_volume", timeout=0.5),
            timeout=1.0,
        )

        self.assertTrue(result["rejected"])
        self.assertEqual(result["reason"], "audio_too_quiet")
        self.assertTrue(result["recovered_to_listening"])

    async def test_empty_asr_stt_to_listening_recovers_without_user_transcript(self):
        peer = self._make_peer()
        peer.events.receive(json.dumps({"type": "state", "state": "stt", "turn_id": "rej-2"}))
        peer.events.receive(json.dumps({"type": "state", "state": "listening"}))

        result = await asyncio.wait_for(
            peer.run_rejected_turn(np.ones(320, dtype=np.int16), "empty_asr", timeout=0.5),
            timeout=1.0,
        )

        self.assertTrue(result["rejected"])
        self.assertEqual(result["reason"], "empty_asr_gate_release")
        self.assertTrue(result["recovered_to_listening"])

    async def test_unexpected_transcript_marks_gate_rejection_as_failed(self):
        peer = self._make_peer()
        peer.events.receive(json.dumps({"type": "user_transcript", "turn_id": "oops-1"}))
        peer.events.receive(
            json.dumps(
                {
                    "type": "turn_metrics",
                    "turn_id": "oops-1",
                    "metrics": _sample_turn(1),
                }
            )
        )
        peer.events.receive(json.dumps({"type": "state", "state": "listening"}))

        result = await asyncio.wait_for(
            peer.run_rejected_turn(np.ones(320, dtype=np.int16), "low_volume", timeout=0.5),
            timeout=1.0,
        )

        self.assertFalse(result["rejected"])
        self.assertEqual(result["reason"], "unexpected_user_transcript")
        self.assertTrue(result["recovered_to_listening"])


class ReconnectAndEndToEndSoakTests(unittest.IsolatedAsyncioTestCase):
    async def test_50_turn_soak_runs_all_scenarios_and_verifies_reconnect_recovery(self):
        created_peers: list = []
        turn_counter = {"count": 0}

        class FakeSoakPeer:
            def __init__(self, base_url: str, http) -> None:
                self.base_url = base_url
                self.http = http
                self.events = EventBroker()
                self.connected = False
                self.closed = False
                self.scenarios_seen: list[str] = []
                self.rejected_seen: list[str] = []
                created_peers.append(self)

            async def connect(self) -> None:
                self.connected = True
                self.events.receive(json.dumps({"type": "state", "state": "listening"}))

            async def run_rejected_turn(self, _samples, scenario: str = "low_volume") -> dict:
                self.rejected_seen.append(scenario)
                return {
                    "scenario": scenario,
                    "rejected": True,
                    "reason": "audio_too_quiet" if scenario == "low_volume" else "empty_transcript",
                    "recovered_to_listening": True,
                }

            async def run_turn(self, _samples, scenario: str) -> dict:
                self.scenarios_seen.append(scenario)
                idx = turn_counter["count"]
                turn_counter["count"] += 1
                return _sample_turn(idx, first_audio=0.95)

            async def close(self) -> None:
                self.closed = True

        async def fake_synth(_text: str, _voice: str) -> np.ndarray:
            return np.ones(320, dtype=np.int16)

        async def fake_health(_base_url: str, _http) -> dict:
            return {
                "ready": True,
                "avatar": {"type": "musetalk", "avatar_id": "musetalk_1"},
                "vad": {"enabled": True, "type": "silero"},
            }

        args = parse_args(
            [
                "--turns",
                "50",
                "--presentation",
                "prerecorded",
                "--profile",
                "jetson-orin-prerecorded",
                "--rapid-every",
                "12",
                "--reject-every",
                "16",
                "--reconnect-every",
                "17",
                "--max-first-audio-p50",
                "1.5",
                "--max-first-audio-p95",
                "2.8",
            ]
        )

        with (
            patch("scripts.run_voice_soak.SoakPeer", FakeSoakPeer),
            patch("scripts.run_voice_soak.synthesize_fixture", side_effect=fake_synth),
            patch("scripts.run_voice_soak.fetch_health", side_effect=fake_health),
        ):
            report = await run_soak(args)

        self.assertTrue(report["slo_pass"])
        self.assertEqual(report["turns"], 50)
        self.assertEqual(report["stale_output_events"], 0)
        self.assertEqual(report["environment"]["presentation"], "prerecorded")
        self.assertIn("rapid_consecutive", report["scenario_counts"])
        self.assertIn("interrupt", report["scenario_counts"])
        self.assertIn("llm_interrupt", report["scenario_counts"])
        self.assertIn("low_volume", report["scenario_counts"])
        self.assertIn("empty_asr", report["scenario_counts"])
        self.assertGreaterEqual(len(created_peers), 3)
        self.assertTrue(all(peer.closed for peer in created_peers))
        self.assertTrue(report["checks"]["recovery_passed"])
        self.assertEqual(report["recovery"]["reconnect_count"], 2)
        self.assertEqual(report["recovery"]["rejection_probe_count"], 3)
        self.assertEqual(report["recovery"]["failed_probes"], 0)

    def test_failed_recovery_probe_fails_soak_slo(self):
        report = build_soak_report(
            [_sample_turn(i) for i in range(50)],
            scenario_counts={"short": 50},
            stale_events=0,
            environment={"presentation": "prerecorded"},
            recovery_results=[
                {"type": "speech_gate_rejection", "passed": False, "reason": "unexpected_user_transcript"},
                {"type": "reconnect", "passed": True},
            ],
        )

        self.assertFalse(report["checks"]["recovery_passed"])
        self.assertFalse(report["slo_pass"])
        self.assertEqual(report["recovery"]["failed_probes"], 1)


class MemoryTrendAndLeakGuardTests(unittest.TestCase):
    def test_sample_rss_mb_reads_proc_status_and_handles_missing_pid(self):
        current_rss = sample_rss_mb(os.getpid())
        self.assertIsNotNone(current_rss)
        self.assertGreater(current_rss, 0.0)
        self.assertIsNone(sample_rss_mb(99999999))

    def test_memory_trend_passes_bounded_rss_and_fails_on_leak(self):
        stable_samples = [1800.0 + (i % 4) * 2.5 for i in range(51)]
        leaking_samples = [1800.0 + i * 8.0 for i in range(51)]

        stable_trend = summarize_memory_trend(stable_samples)
        self.assertEqual(stable_trend["sample_count"], 51)
        self.assertEqual(stable_trend["initial_mb"], 1800.0)
        self.assertEqual(stable_trend["delta_mb"], 5.0)
        self.assertLess(stable_trend["slope_mb_per_sample"], 0.2)

        passing = build_soak_report(
            [_sample_turn(i) for i in range(50)],
            scenario_counts={"short": 50},
            stale_events=0,
            environment={"presentation": "prerecorded"},
            memory_samples_mb=stable_samples,
            max_rss_growth_mb=256.0,
        )
        failing = build_soak_report(
            [_sample_turn(i) for i in range(50)],
            scenario_counts={"short": 50},
            stale_events=0,
            environment={"presentation": "prerecorded"},
            memory_samples_mb=leaking_samples,
            max_rss_growth_mb=256.0,
        )

        self.assertTrue(passing["checks"]["memory_leak_guard"])
        self.assertTrue(passing["slo_pass"])
        self.assertEqual(passing["memory_trend"]["target_growth_at_most_mb"], 256.0)

        self.assertFalse(failing["checks"]["memory_leak_guard"])
        self.assertFalse(failing["slo_pass"])
        self.assertEqual(failing["memory_trend"]["delta_mb"], 400.0)
        self.assertGreater(failing["memory_trend"]["slope_mb_per_sample"], 7.9)

    def test_stage_timings_and_memory_trend_included_in_soak_report(self):
        report = build_soak_report(
            [_sample_turn(i, first_audio=1.0) for i in range(50)],
            scenario_counts={"short": 50},
            stale_events=0,
            environment={"presentation": "prerecorded", "profile": "jetson-orin-prerecorded"},
            memory_samples_mb=[1600.0, 1604.0, 1602.0],
        )

        self.assertIn("memory_trend", report)
        for stage in ("vad_endpoint", "asr", "llm_first_token", "tts_first_pcm", "webrtc_audio_commit"):
            self.assertIsNotNone(report["metrics"]["stage_seconds"][stage]["p50"])
            self.assertIsNotNone(report["metrics"]["stage_seconds"][stage]["p95"])
