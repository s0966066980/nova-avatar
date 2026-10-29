#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Measure perceived first-audio latency over a real stage WebRTC session.

Fixture utterances (general, RAG and handoff; zh-TW and en-US) are synthesized
in memory and streamed in real time as the stage microphone. The harness
records when the recording's voice actually ends and when the first audible
reply audio frame arrives, then joins that with the server's content-free
``turn_metrics``. Only scalar timings and fixture IDs are written (ADR 0004).

The harness and the backend share ``time.monotonic`` on the stage host, so the
server's ``clock_marks`` split the client offset into the VAD speech tail, VAD
work, uplink, audible onset and downlink. Perceived latency ends when the
server sends the first audible frame; the downlink (aiortc jitter buffer and
decode in this harness) is reported separately because a browser differs.

Run only from the stage host: ``POST /offer`` with ``client_role=stage`` is a
loopback-only route (ADR 0021). Close the kiosk stage page first; the backend
allows one stage session while roles are enabled.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import time
from pathlib import Path

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_voice_soak import SoakPeer, synthesize_fixture
from src.server.reply_streaming.latency_baseline import (
    FIXTURES,
    LatencyFixture,
    build_latency_report,
    build_turn_record,
    fixtures_from_json,
    is_active_audio,
    turn_plan,
    voiced_end_sample,
)

FIXTURE_VOICES = {"zh-TW": "zh-TW-HsiaoChenNeural", "en-US": "en-US-JennyNeural"}


class LatencyPeer(SoakPeer):
    """A stage peer that times the first active reply frame after speech."""

    def __init__(self, *args, **kwargs) -> None:
        self.voice_ended_at: float | None = None
        self.first_reply_audio_at: float | None = None
        self.handoff_turns: set[str] = set()
        self.rag_status: dict[str, str] = {}
        self._transcript_turn: str | None = None
        super().__init__(*args, **kwargs)
        self.channel.on("message", self._observe)

    def voice_ended(self, at: float) -> None:
        self.voice_ended_at = at
        self.first_reply_audio_at = None

    def _observe(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        kind, turn_id = event.get("type"), event.get("turn_id")
        if kind == "user_transcript" and turn_id:
            self._transcript_turn = str(turn_id)
        elif kind == "role_state" and event.get("phase") == "announcement" and self._transcript_turn:
            self.handoff_turns.add(self._transcript_turn)
        elif kind == "rag_retrieval" and turn_id:
            self.rag_status.setdefault(str(turn_id), str(event.get("status")))

    async def _drain(self, track) -> None:
        try:
            while True:
                frame = await track.recv()
                if (track.kind == "audio" and self.voice_ended_at is not None
                        and self.first_reply_audio_at is None
                        and is_active_audio(frame.to_ndarray())):
                    now = time.monotonic()
                    if now >= self.voice_ended_at:
                        self.first_reply_audio_at = now
        except Exception:
            return


async def _wait(peer: LatencyPeer, predicate, timeout: float) -> dict:
    return await peer.events.wait_for(predicate, timeout=timeout)


async def measure_turn(peer: LatencyPeer, fixture: LatencyFixture, samples, voiced_end: int,
                       *, timeout: float) -> dict:
    peer.voice_ended_at = None
    peer.first_reply_audio_at = None
    peer.audio.push(samples, on_sample_sent=(voiced_end, peer.voice_ended))
    transcript = await _wait(peer, lambda e: e.get("type") == "user_transcript", timeout)
    turn_id = str(transcript["turn_id"])
    metric_event = await _wait(
        peer, lambda e: e.get("type") == "turn_metrics" and e.get("turn_id") == turn_id, timeout)
    voice_ended_at, first_reply_audio_at = peer.voice_ended_at, peer.first_reply_audio_at
    final_event = metric_event
    specialist = None
    handoff = turn_id in peer.handoff_turns
    if handoff:
        started = await _wait(peer, lambda e: e.get("type") == "role_handoff"
                              and e.get("source_turn_id") == turn_id, timeout)
        target = str(started["target_turn_id"])
        final_event = await _wait(
            peer, lambda e: e.get("type") == "turn_metrics" and e.get("turn_id") == target, timeout)
        specialist = dict(final_event.get("metrics") or {}).get("first_audio_seconds")
    after = int(final_event.get("seq") or 0)
    await _wait(peer, lambda e: e.get("type") == "state" and e.get("state") == "listening"
                and int(e.get("seq") or 0) > after, timeout)
    return build_turn_record(
        fixture, metric_event,
        voice_ended_at=voice_ended_at,
        first_reply_audio_at=first_reply_audio_at,
        handoff_observed=handoff,
        rag_status=peer.rag_status.get(turn_id),
        specialist_first_audio_seconds=specialist,
    )


async def run(args) -> dict:
    fixtures = (fixtures_from_json(args.fixtures.read_text(encoding="utf-8"))
                if args.fixtures else FIXTURES)
    plan = turn_plan(fixtures, rounds=args.rounds)
    audio = {}
    for fixture in fixtures:
        samples = await synthesize_fixture(fixture.text, FIXTURE_VOICES[fixture.language])
        audio[fixture.fixture_id] = (samples, voiced_end_sample(samples))
    warmup = [f for f in fixtures if f.category == "general"][: args.warmup]

    records: list[dict] = []
    connector = aiohttp.TCPConnector(ssl=False)
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as http:
        peer = LatencyPeer(args.base_url, http, client_role="stage")
        try:
            await peer.connect()
            for fixture in warmup:
                await measure_turn(peer, fixture, *audio[fixture.fixture_id],
                                   timeout=args.turn_timeout)
            for index, fixture in enumerate(plan, start=1):
                try:
                    record = await measure_turn(peer, fixture, *audio[fixture.fixture_id],
                                                timeout=args.turn_timeout)
                except asyncio.TimeoutError:
                    # The session state is unknown; start the next turn clean.
                    record = build_turn_record(fixture, None)
                    await peer.close()
                    await asyncio.sleep(1.0)
                    peer = LatencyPeer(args.base_url, http, client_role="stage")
                    await peer.connect()
                records.append(record)
                print(f"turn {index}/{len(plan)} {fixture.fixture_id} status={record['status']} "
                      f"perceived={record.get('perceived_first_audio_seconds')} "
                      f"({record.get('perceived_basis')}) "
                      f"first_audio={record.get('first_audio_seconds')} "
                      f"handoff={record.get('handoff_observed')} "
                      f"offset_split={record.get('offset_split')}", flush=True)
                await asyncio.sleep(args.pause)
        finally:
            await peer.close()

    return build_latency_report(records, environment={
        "measured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "gpu": args.gpu,
        "transport": "WebRTC (aiortc client, loopback)",
        "clock": "time.monotonic shared with the backend on this host",
        "client_role": "stage",
        "input": "synthetic Edge TTS fixtures, streamed in real time",
        "fixture_set": str(args.fixtures) if args.fixtures else "builtin",
        "rounds": str(args.rounds),
        "note": args.note,
    })


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="https://localhost:8010")
    parser.add_argument("--rounds", type=int, default=1, help="repeat the fixture plan")
    parser.add_argument("--warmup", type=int, default=1, help="unrecorded general turns first")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between turns")
    parser.add_argument("--turn-timeout", type=float, default=90.0)
    parser.add_argument("--fixtures", type=Path, help="site fixture JSON replacing the builtin set")
    parser.add_argument("--gpu", default="NVIDIA GeForce RTX 4090")
    parser.add_argument("--note", default="", help="configuration note stored in the report")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / ".scratch" / "first-audio-latency"
                        / f"baseline-{dt.date.today().isoformat()}.json")
    args = parser.parse_args(argv)
    if args.rounds < 1 or args.warmup < 0:
        parser.error("--rounds must be positive and --warmup nonnegative")
    return args


def main() -> int:
    args = parse_args()
    report = asyncio.run(run(args))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    for name, summary in report["categories"].items():
        print(f"{name}: n={summary['turns']} misaligned={summary['misaligned_turns']} "
              f"perceived={summary['perceived_first_audio_seconds']} "
              f"first_audio={summary['first_audio_seconds']} "
              f"prompt={summary['prompt_first_audio_seconds']} "
              f"client_received={summary['client_received_first_audio_seconds']} "
              f"offset_split={summary['offset_split']}", flush=True)
    print(f"report: {args.output}")
    return 0 if report["failed_turns"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
