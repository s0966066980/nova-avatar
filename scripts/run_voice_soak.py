#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Run a content-free real WebRTC voice soak against a local backend.

The fixture utterances and decoded audio live only in memory. The only durable
output is aggregate scalar telemetry suitable for the Phase 6 gate.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter, deque
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence

import aiohttp
import av
import edge_tts
import numpy as np
from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
    MediaStreamTrack,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.server.reply_streaming.soak import build_soak_report, sample_rss_mb


SAMPLE_RATE = 16000
FRAME_SAMPLES = 320
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
FIXTURE_REQUESTS = (
    "請用一句話簡短介紹臺灣。",
    "請用大約一百字說明規律運動的好處。",
    "請用逗號和冒號組成自然的回答，內容保持簡潔。",
    "請用沒有標點的短句回答今天如何維持專注。",
)

PROFILE_PRESETS: dict[str, dict[str, str]] = {
    "jetson-orin-prerecorded": {
        "presentation": "prerecorded",
        "gpu": "NVIDIA Jetson AGX Orin 64GB",
        "llm": "llama.cpp (Gemma-4-E2B)",
        "asr": "faster-whisper small",
        "tts": "Edge TTS",
        "avatar": "Prerecorded",
    },
    "orin-prerecorded": {
        "presentation": "prerecorded",
        "gpu": "NVIDIA Jetson AGX Orin 64GB",
        "llm": "llama.cpp (Gemma-4-E2B)",
        "asr": "faster-whisper small",
        "tts": "Edge TTS",
        "avatar": "Prerecorded",
    },
    "rtx4090-realtime": {
        "presentation": "realtime",
        "gpu": "NVIDIA GeForce RTX 4090",
        "llm": "llama.cpp",
        "asr": "faster-whisper",
        "tts": "Edge TTS",
        "avatar": "MuseTalk",
    },
}


def resolve_environment(args, health: Mapping | None = None) -> dict[str, str]:
    """Build non-hardcoded environment metadata from CLI flags, profile presets, and /health."""
    profile = getattr(args, "profile", None)
    preset = PROFILE_PRESETS.get(profile or "", {})
    presentation = (
        getattr(args, "presentation", None)
        or preset.get("presentation")
        or "realtime"
    )
    default_avatar = "Prerecorded" if presentation == "prerecorded" else "MuseTalk"
    env: dict[str, str] = {
        "presentation": presentation,
        "gpu": getattr(args, "gpu", None) or preset.get("gpu") or "NVIDIA GeForce RTX 4090",
        "llm": getattr(args, "llm", None) or preset.get("llm") or "llama.cpp",
        "asr": getattr(args, "asr", None) or preset.get("asr") or "faster-whisper",
        "tts": getattr(args, "tts", None) or preset.get("tts") or "Edge TTS",
        "avatar": getattr(args, "avatar", None) or preset.get("avatar") or default_avatar,
        "transport": "WebRTC",
    }
    if profile:
        env["profile"] = profile
    if isinstance(health, Mapping):
        avatar_info = health.get("avatar")
        if isinstance(avatar_info, Mapping):
            if avatar_info.get("avatar_id"):
                env["avatar_id"] = str(avatar_info["avatar_id"])
            if avatar_info.get("type") and not getattr(args, "avatar", None) and presentation != "prerecorded":
                env["avatar"] = str(avatar_info["type"])
        vad_info = health.get("vad")
        if isinstance(vad_info, Mapping) and vad_info.get("type"):
            env["vad"] = str(vad_info["type"])
    return env


class PushAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._frames: deque[np.ndarray] = deque()
        self._timestamp = 0
        self._started_at: float | None = None

    def push(self, samples: np.ndarray) -> None:
        pcm = np.asarray(samples, dtype=np.int16).reshape(-1)
        padded = int(np.ceil(pcm.size / FRAME_SAMPLES)) * FRAME_SAMPLES
        if padded > pcm.size:
            pcm = np.pad(pcm, (0, padded - pcm.size))
        for offset in range(0, pcm.size, FRAME_SAMPLES):
            self._frames.append(pcm[offset : offset + FRAME_SAMPLES].copy())

    async def recv(self):
        now = time.monotonic()
        if self._started_at is None:
            self._started_at = now
        else:
            deadline = self._started_at + self._timestamp / SAMPLE_RATE
            if deadline > now:
                await asyncio.sleep(deadline - now)
        samples = (
            self._frames.popleft()
            if self._frames
            else np.zeros(FRAME_SAMPLES, dtype=np.int16)
        )
        frame = av.AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.planes[0].update(samples.tobytes())
        frame.sample_rate = SAMPLE_RATE
        frame.pts = self._timestamp
        frame.time_base = Fraction(1, SAMPLE_RATE)
        self._timestamp += FRAME_SAMPLES
        return frame


STALE_OUTPUT_EVENT_TYPES = frozenset(
    {
        "assistant_fragment",
        "assistant_response",
        "assistant_response_start",
        "assistant_response_delta",
        "assistant_response_done",
        "assistant_board",
        "board_item",
        "speaking_start",
    }
)


class EventBroker:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._backlog: list[dict] = []
        self.cancelled_turns: set[str] = set()
        self.stale_events = 0
        self.rejected_events: list[dict] = []

    def receive(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        event_type = event.get("type")
        turn_id = event.get("turn_id")
        if event_type == "turn_cancelled" and turn_id:
            self.cancelled_turns.add(str(turn_id))
        elif event_type in STALE_OUTPUT_EVENT_TYPES and turn_id and str(turn_id) in self.cancelled_turns:
            self.stale_events += 1
        elif event_type == "speech_input_rejected":
            self.rejected_events.append(
                {
                    "reason": str(
                        event.get("reason")
                        or event.get("speech_input_rejection_reason")
                        or "rejected"
                    ),
                    "turn_id": str(turn_id) if turn_id else None,
                }
            )
        self._queue.put_nowait(event)

    async def wait_for(self, predicate, *, timeout: float = 90.0) -> dict:
        for index, event in enumerate(self._backlog):
            if predicate(event):
                return self._backlog.pop(index)

        async def consume():
            while True:
                event = await self._queue.get()
                if predicate(event):
                    return event
                self._backlog.append(event)

        return await asyncio.wait_for(consume(), timeout=timeout)


REJECTED_SCENARIOS = frozenset({"low_volume", "empty_asr", "rejected_speech"})


def make_low_volume_fixture(
    duration_seconds: float = 1.2,
    *,
    amplitude: int = 12,
) -> np.ndarray:
    """Create a deterministic low-amplitude audio fixture for gate rejection tests."""
    sample_count = max(FRAME_SAMPLES, int(round(duration_seconds * SAMPLE_RATE)))
    t = np.arange(sample_count, dtype=np.float32) / SAMPLE_RATE
    tone = (np.sin(2.0 * np.pi * 220.0 * t) * float(amplitude)).astype(np.int16)
    return tone


class SoakPeer:
    def __init__(self, base_url: str, http: aiohttp.ClientSession) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.audio = PushAudioTrack()
        self.events = EventBroker()
        self.channel = self.pc.createDataChannel("voice-events", ordered=True)
        self.channel.on("message", self.events.receive)
        self._drainers: list[asyncio.Task] = []
        self.pc.addTrack(self.audio)
        self.pc.addTransceiver("video", direction="recvonly")

        @self.pc.on("track")
        def on_track(track):
            self._drainers.append(asyncio.create_task(self._drain(track)))

    async def connect(self) -> None:
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        async with self.http.post(
            f"{self.base_url}/offer",
            json={
                "sdp": self.pc.localDescription.sdp,
                "type": self.pc.localDescription.type,
                "client_role": "stage",
            },
        ) as response:
            response.raise_for_status()
            answer = await response.json()
        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )
        await self.events.wait_for(
            lambda event: event.get("type") == "state"
            and event.get("state") == "listening",
            timeout=120.0,
        )

    async def run_rejected_turn(
        self,
        samples: np.ndarray,
        scenario: str = "low_volume",
        *,
        timeout: float = 4.0,
    ) -> dict:
        """Send low-volume/empty-ASR audio and verify recovery without hanging on user_transcript."""
        self.audio.push(samples)
        deadline = time.monotonic() + timeout
        saw_stt = False
        reason: str | None = None

        while True:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                event = await self.events.wait_for(
                    lambda ev: ev.get("type")
                    in {"speech_input_rejected", "user_transcript", "state"},
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                if not saw_stt and reason is None:
                    return {
                        "scenario": scenario,
                        "rejected": True,
                        "reason": "vad_below_threshold",
                        "recovered_to_listening": True,
                    }
                return {
                    "scenario": scenario,
                    "rejected": False,
                    "reason": "listening_recovery_timeout",
                    "recovered_to_listening": False,
                }

            ev_type = event.get("type")
            if ev_type == "user_transcript":
                turn_id = str(event.get("turn_id") or "")
                if turn_id:
                    await self.events.wait_for(
                        lambda ev: ev.get("type") == "turn_metrics"
                        and str(ev.get("turn_id") or "") == turn_id
                    )
                await self.events.wait_for(
                    lambda ev: ev.get("type") == "state"
                    and ev.get("state") == "listening"
                )
                return {
                    "scenario": scenario,
                    "rejected": False,
                    "reason": "unexpected_user_transcript",
                    "recovered_to_listening": True,
                }
            if ev_type == "speech_input_rejected":
                reason = str(
                    event.get("reason")
                    or event.get("speech_input_rejection_reason")
                    or "rejected"
                )
                continue
            if ev_type == "state":
                state_name = event.get("state")
                if state_name == "stt":
                    saw_stt = True
                elif state_name == "listening":
                    return {
                        "scenario": scenario,
                        "rejected": True,
                        "reason": reason
                        or (
                            "empty_asr_gate_release"
                            if saw_stt
                            else "pre_asr_gate_release"
                        ),
                        "recovered_to_listening": True,
                    }

    async def run_turn(self, samples: np.ndarray, scenario: str) -> dict:
        if scenario in REJECTED_SCENARIOS:
            return await self.run_rejected_turn(samples, scenario)
        self.audio.push(samples)
        transcript = await self.events.wait_for(
            lambda event: event.get("type") == "user_transcript"
        )
        turn_id = str(transcript["turn_id"])
        metric_event = None

        if scenario == "llm_interrupt":
            ready = await self.events.wait_for(
                lambda event: event.get("turn_id") == turn_id
                and (
                    (event.get("type") == "state" and event.get("state") == "llm")
                    or event.get("type") == "turn_metrics"
                )
            )
            if ready.get("type") == "turn_metrics":
                metric_event = ready
            else:
                self.channel.send(json.dumps({"type": "interrupt"}))
        elif scenario == "interrupt":
            ready = await self.events.wait_for(
                lambda event: event.get("turn_id") == turn_id
                and event.get("type") in {"speaking_start", "turn_metrics"}
            )
            if ready.get("type") == "turn_metrics":
                metric_event = ready
            else:
                self.channel.send(json.dumps({"type": "interrupt"}))

        if metric_event is None:
            metric_event = await self.events.wait_for(
                lambda event: event.get("type") == "turn_metrics"
                and event.get("turn_id") == turn_id
            )
        await self.events.wait_for(
            lambda event: event.get("type") == "state"
            and event.get("state") == "listening"
        )
        return dict(metric_event["metrics"])

    async def close(self) -> None:
        await self.pc.close()
        for task in self._drainers:
            task.cancel()
        await asyncio.gather(*self._drainers, return_exceptions=True)

    @staticmethod
    async def _drain(track) -> None:
        try:
            while True:
                await track.recv()
        except Exception:
            return


async def synthesize_fixture(text: str, voice: str) -> np.ndarray:
    encoded = bytearray()
    async for item in edge_tts.Communicate(text, voice).stream():
        if item.get("type") == "audio":
            encoded.extend(item["data"])
    if not encoded:
        raise RuntimeError("fixture synthesis produced no audio")

    output = []
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    with av.open(BytesIO(bytes(encoded)), format="mp3") as container:
        for decoded in container.decode(audio=0):
            for converted in resampler.resample(decoded):
                output.append(converted.to_ndarray().reshape(-1).astype(np.int16))
        for converted in resampler.resample(None):
            output.append(converted.to_ndarray().reshape(-1).astype(np.int16))
    speech = np.concatenate(output)
    return np.concatenate(
        (
            np.zeros(int(0.2 * SAMPLE_RATE), dtype=np.int16),
            speech,
            np.zeros(int(0.9 * SAMPLE_RATE), dtype=np.int16),
        )
    )


async def fetch_health(base_url: str, http: aiohttp.ClientSession) -> dict | None:
    """Best-effort fetch of backend /health metadata for environment reporting."""
    try:
        async with http.get(
            f"{base_url.rstrip('/')}/health",
            timeout=aiohttp.ClientTimeout(total=5.0),
        ) as response:
            if response.status != 200:
                return None
            payload = await response.json()
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


async def run(args) -> dict:
    fixtures = [
        await synthesize_fixture(text, args.fixture_voice)
        for text in FIXTURE_REQUESTS
    ]
    low_volume_fixture = make_low_volume_fixture()
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    metrics: list[dict] = []
    scenario_counts: Counter[str] = Counter()
    recovery_results: list[dict] = []
    memory_samples_mb: list[float] = []
    stale_events = 0

    def _record_rss() -> None:
        rss = sample_rss_mb(args.server_pid)
        if rss is not None:
            memory_samples_mb.append(rss)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as http:
        health = await fetch_health(args.base_url, http)
        environment = resolve_environment(args, health)
        _record_rss()
        peer = SoakPeer(args.base_url, http)
        await peer.connect()
        try:
            for index in range(args.turns):
                if (
                    index
                    and args.reconnect_every > 0
                    and index % args.reconnect_every == 0
                ):
                    stale_events += peer.events.stale_events
                    await peer.close()
                    peer = SoakPeer(args.base_url, http)
                    await peer.connect()
                    recovery_results.append(
                        {
                            "type": "reconnect",
                            "turn_index": index,
                            "passed": True,
                        }
                    )

                if index and args.reject_every > 0 and index % args.reject_every == 0:
                    probe_index = index // args.reject_every
                    probe_scenario = (
                        "low_volume" if probe_index % 2 == 1 else "empty_asr"
                    )
                    probe_audio = (
                        low_volume_fixture
                        if probe_scenario == "low_volume"
                        else make_low_volume_fixture(duration_seconds=0.8, amplitude=350)
                    )
                    scenario_counts[probe_scenario] += 1
                    probe_result = await peer.run_rejected_turn(
                        probe_audio,
                        probe_scenario,
                    )
                    recovery_results.append(
                        {
                            "type": "speech_gate_rejection",
                            "scenario": probe_scenario,
                            "turn_index": index,
                            "passed": bool(
                                probe_result.get("rejected")
                                and probe_result.get("recovered_to_listening")
                            ),
                            "reason": probe_result.get("reason"),
                        }
                    )

                if (
                    args.llm_interrupt_every > 0
                    and index % args.llm_interrupt_every == args.llm_interrupt_every - 1
                ):
                    scenario = "llm_interrupt"
                elif (
                    args.interrupt_every > 0
                    and index % args.interrupt_every == args.interrupt_every - 1
                ):
                    scenario = "interrupt"
                elif (
                    args.rapid_every > 0
                    and index % args.rapid_every == args.rapid_every - 1
                ):
                    scenario = "rapid_consecutive"
                else:
                    scenario = ("short", "long", "weak_punctuation", "no_punctuation")[
                        index % len(fixtures)
                    ]
                scenario_counts[scenario] += 1
                metric = await peer.run_turn(fixtures[index % len(fixtures)], scenario)
                metrics.append(metric)
                _record_rss()
                print(
                    f"soak progress {index + 1}/{args.turns} scenario={scenario} "
                    f"first_audio={metric.get('first_audio_seconds')} "
                    f"avatar_commit={metric.get('stage_seconds', {}).get('avatar_to_webrtc_commit')}",
                    flush=True,
                )
        finally:
            stale_events += peer.events.stale_events
            await peer.close()

    return build_soak_report(
        metrics,
        scenario_counts=scenario_counts,
        stale_events=stale_events,
        environment=environment,
        max_first_audio_p50=args.max_first_audio_p50,
        max_first_audio_p95=args.max_first_audio_p95,
        memory_samples_mb=memory_samples_mb,
        max_rss_growth_mb=args.max_rss_growth_mb,
        recovery_results=recovery_results,
    )


def parse_args(argv: Sequence[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://localhost:8010")
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--interrupt-every", type=int, default=10)
    parser.add_argument("--llm-interrupt-every", type=int, default=15)
    parser.add_argument("--rapid-every", type=int, default=12)
    parser.add_argument("--reject-every", type=int, default=16)
    parser.add_argument("--reconnect-every", type=int, default=17)
    parser.add_argument("--fixture-voice", default="zh-TW-HsiaoChenNeural")
    parser.add_argument(
        "--presentation",
        choices=("prerecorded", "realtime"),
        default=None,
    )
    parser.add_argument("--profile", default=None)
    parser.add_argument("--gpu", default=None)
    parser.add_argument("--llm", default=None)
    parser.add_argument("--tts", default=None)
    parser.add_argument("--asr", default=None)
    parser.add_argument("--avatar", default=None)
    parser.add_argument("--max-first-audio-p50", type=float, default=1.2)
    parser.add_argument("--max-first-audio-p95", type=float, default=2.5)
    parser.add_argument("--max-rss-growth-mb", type=float, default=256.0)
    parser.add_argument("--server-pid", type=int, default=None)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(run(args))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["slo_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
