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

from src.server.reply_streaming.soak import build_soak_report


SAMPLE_RATE = 16000
FRAME_SAMPLES = 320
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
FIXTURE_REQUESTS = (
    "請用一句話簡短介紹臺灣。",
    "請用大約一百字說明規律運動的好處。",
    "請用逗號和冒號組成自然的回答，內容保持簡潔。",
    "請用沒有標點的短句回答今天如何維持專注。",
)


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


class EventBroker:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._backlog: list[dict] = []
        self.cancelled_turns: set[str] = set()
        self.stale_events = 0

    def receive(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        turn_id = event.get("turn_id")
        if event.get("type") == "turn_cancelled" and turn_id:
            self.cancelled_turns.add(str(turn_id))
        elif event.get("type") == "assistant_fragment" and str(turn_id) in self.cancelled_turns:
            self.stale_events += 1
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

    async def run_turn(self, samples: np.ndarray, scenario: str) -> dict:
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


async def run(args) -> dict:
    fixtures = [
        await synthesize_fixture(text, args.fixture_voice)
        for text in FIXTURE_REQUESTS
    ]
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    metrics: list[dict] = []
    scenario_counts: Counter[str] = Counter()
    stale_events = 0

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as http:
        peer = SoakPeer(args.base_url, http)
        await peer.connect()
        try:
            for index in range(args.turns):
                if index and index % args.reconnect_every == 0:
                    stale_events += peer.events.stale_events
                    await peer.close()
                    peer = SoakPeer(args.base_url, http)
                    await peer.connect()

                if index % args.llm_interrupt_every == args.llm_interrupt_every - 1:
                    scenario = "llm_interrupt"
                elif index % args.interrupt_every == args.interrupt_every - 1:
                    scenario = "interrupt"
                else:
                    scenario = ("short", "long", "weak_punctuation", "no_punctuation")[
                        index % len(fixtures)
                    ]
                scenario_counts[scenario] += 1
                metric = await peer.run_turn(fixtures[index % len(fixtures)], scenario)
                metrics.append(metric)
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
        environment={
            "gpu": args.gpu,
            "llm": "llama.cpp",
            "tts": "Edge TTS",
            "avatar": "MuseTalk",
            "transport": "WebRTC",
        },
    )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://localhost:8010")
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--interrupt-every", type=int, default=10)
    parser.add_argument("--llm-interrupt-every", type=int, default=15)
    parser.add_argument("--reconnect-every", type=int, default=17)
    parser.add_argument("--fixture-voice", default="zh-TW-HsiaoChenNeural")
    parser.add_argument("--gpu", default="NVIDIA GeForce RTX 4090")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(run(args))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    if args.output is not None:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["slo_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
