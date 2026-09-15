#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Run deterministic legacy voice-turn replays and emit content-free SLO JSON."""
from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.server.voice_session import VoiceTurnSession


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeAvatar:
    def __init__(self) -> None:
        self.fragments = 0

    def put_msg_txt(self, _text, data=None) -> None:
        del data
        self.fragments += 1

    def flush_talk(self) -> None:
        self.fragments = 0

    def is_speaking(self) -> bool:
        return False


class FakeSegmenter:
    def __init__(self) -> None:
        self.is_speaking = False
        self._pending = True

    def reset(self) -> None:
        self.is_speaking = False

    def process(self, _pcm):
        if not self._pending:
            return []
        self._pending = False
        return [
            SimpleNamespace(
                audio=np.ones(1600, dtype=np.int16),
                sample_rate=16000,
            )
        ]

    def flush(self):
        return []


class FakeSTT:
    def transcribe(self, _audio) -> dict:
        return {"text": "fixture", "language": "fixture"}


def _fake_llm(
    _text,
    avatar,
    *,
    stream_to_avatar=True,
    datainfo=None,
    chunk_guard=None,
) -> str:
    if stream_to_avatar and (chunk_guard is None or chunk_guard(0)):
        avatar.put_msg_txt("fixture", data=datainfo)
    return "fixture"


async def replay_turn(
    *,
    session_id: int,
    first_audio_seconds: float,
    interrupt_stop_seconds: float,
    listening_resume_seconds: float,
    media_debt_seconds: float,
    av_offset_seconds: float,
) -> dict:
    clock = FakeClock()
    config = SimpleNamespace(
        asr=SimpleNamespace(type="fake", model_size="fake", language="fixture"),
        vad=SimpleNamespace(),
    )
    session = VoiceTurnSession(session_id, config, FakeAvatar(), clock=clock)
    session._segmenter = FakeSegmenter()
    session._asr = FakeSTT()
    session.attach_event_sink(lambda _event: None)

    with patch("src.server.voice_session.llm_response", side_effect=_fake_llm):
        await session.feed_pcm(np.ones(512, dtype=np.int16))
        await session._turn_task

    clock.advance(first_audio_seconds)
    session.on_output_audio(True)
    session.observe_media_timing(
        media_debt_seconds=media_debt_seconds,
        av_offset_seconds=av_offset_seconds,
    )

    guard_started = asyncio.Event()
    release_guard = asyncio.Event()

    async def controlled_tail_guard(_seconds: float) -> None:
        guard_started.set()
        await release_guard.wait()

    with patch("src.server.voice_session.asyncio.sleep", new=controlled_tail_guard):
        interrupt_task = asyncio.create_task(session.interrupt())
        await guard_started.wait()
        clock.advance(interrupt_stop_seconds)
        session.on_output_audio(False)
        clock.advance(listening_resume_seconds - interrupt_stop_seconds)
        release_guard.set()
        await interrupt_task

    snapshot = session.metrics_snapshot()
    await session.close()
    return snapshot


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return round(ordered[rank - 1], 6)


def build_report(snapshots: list[dict]) -> dict:
    first_audio = [item["first_audio_seconds"] for item in snapshots]
    interrupt_stop = [item["interrupt_stop_seconds"] for item in snapshots]
    listening_resume = [item["listening_resume_seconds"] for item in snapshots]
    media_debt = [item["max_media_debt_seconds"] for item in snapshots]
    av_offset = [item["max_abs_av_offset_seconds"] for item in snapshots]

    metrics = {
        "av_offset_seconds": {
            "p95": percentile(av_offset, 0.95),
            "target_p95_at_most": 0.08,
        },
        "first_audio_seconds": {
            "p50": percentile(first_audio, 0.50),
            "p95": percentile(first_audio, 0.95),
            "target_p50_at_most": 1.2,
            "target_p95_at_most": 2.5,
        },
        "interrupt_stop_seconds": {
            "p95": percentile(interrupt_stop, 0.95),
            "target_p95_at_most": 0.2,
        },
        "listening_resume_seconds": {
            "p95": percentile(listening_resume, 0.95),
            "target_p95_at_most": 0.5,
        },
        "media_debt_seconds": {
            "maximum": round(max(media_debt), 6),
            "target_below": 2.0,
        },
    }
    checks = {
        "av_offset": metrics["av_offset_seconds"]["p95"] <= 0.08,
        "first_audio_p50": metrics["first_audio_seconds"]["p50"] <= 1.2,
        "first_audio_p95": metrics["first_audio_seconds"]["p95"] <= 2.5,
        "interrupt_stop": metrics["interrupt_stop_seconds"]["p95"] <= 0.2,
        "listening_resume": metrics["listening_resume_seconds"]["p95"] <= 0.5,
        "media_debt": metrics["media_debt_seconds"]["maximum"] < 2.0,
        "stale_output": all(not item["stale_drops"] for item in snapshots),
    }
    return {
        "checks": checks,
        "metrics": metrics,
        "mode": "deterministic_fake_legacy",
        "schema_version": 1,
        "slo_pass": all(checks.values()),
        "turns": len(snapshots),
    }


async def main() -> None:
    cases = zip(
        (0.8, 0.9, 1.0, 1.4, 2.4),
        (0.08, 0.10, 0.12, 0.16, 0.19),
        (0.30, 0.32, 0.35, 0.40, 0.48),
        (0.08, 0.12, 0.16, 0.20, 0.24),
        (0.02, 0.03, 0.04, 0.06, 0.08),
    )
    snapshots = []
    for session_id, values in enumerate(cases, start=1):
        snapshots.append(
            await replay_turn(
                session_id=session_id,
                first_audio_seconds=values[0],
                interrupt_stop_seconds=values[1],
                listening_resume_seconds=values[2],
                media_debt_seconds=values[3],
                av_offset_seconds=values[4],
            )
        )
    print(json.dumps(build_report(snapshots), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
