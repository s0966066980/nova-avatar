#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Benchmark Streaming Mode vs Legacy Mode for Voice Turns.

Measures:
1. Time to First Audio (TTFT)
2. Total Turn Duration
3. Inter-fragment Pauses and Continuity
4. Stale Drops and Playback Stall Failures
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.server.voice_session import VoiceTurnSession
from src.server.reply_streaming.fragmenter import SemanticFragmenter


class BenchmarkAvatar:
    def __init__(self):
        self.messages: list[tuple[str, dict]] = []
        self.audio_frames: list[tuple[np.ndarray, dict]] = []
        self.media_guard = None
        self.on_stale_drop = None
        self.on_fragment_queued = None
        self.stale_drop_counts: dict[str, int] = {}

    def configure_media_fence(self, *, media_guard, on_stale_drop, on_fragment_queued=None, **_unused):
        self.media_guard = media_guard
        self.on_stale_drop = on_stale_drop
        self.on_fragment_queued = on_fragment_queued

    def put_msg_txt(self, text, data=None):
        eventpoint = dict(data or {})
        self.messages.append((text, eventpoint))
        if self.on_fragment_queued is not None and eventpoint.get("turn_id"):
            self.on_fragment_queued(text, eventpoint)

    def record_stale_drop(self, stage: str, reason: str = "stale"):
        key = f"{stage}:{reason}"
        self.stale_drop_counts[key] = self.stale_drop_counts.get(key, 0) + 1
        if self.on_stale_drop is not None:
            self.on_stale_drop(stage, reason)

    def accepts_media(self, eventpoint: dict, stage: str) -> bool:
        if self.media_guard is not None and eventpoint.get("turn_id"):
            return self.media_guard(eventpoint, stage)
        return True

    def flush_talk(self):
        self.messages.clear()
        self.audio_frames.clear()

    def is_speaking(self) -> bool:
        return False


class VirtualClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float):
        self.now += seconds


TEST_CASES = [
    {
        "name": "Case 1: 短句問答 (Short Answer)",
        "prompt": "你好，請自我介紹。",
        "sentences": [
            ("你好！我是你的AI虛擬助手，很高興為你服務。", 0.05),
        ],
        "token_delay_ms": 30,
    },
    {
        "name": "Case 2: 多句連續回答 (Multi-sentence standard)",
        "prompt": "請說明健康飲食的要點。",
        "sentences": [
            ("好的，健康飲食有三個重點。", 0.08),
            ("第一是均衡攝取各類營養素，不要偏食。", 0.08),
            ("第二是多喝水並減少高糖高鹽攝取。", 0.08),
            ("第三是保持規律的進食時間與適量運動。", 0.08),
        ],
        "token_delay_ms": 35,
    },
    {
        "name": "Case 3: 帶有網路/思考間隔的長句 (Sentence gap 1.2s - tests stall resilience)",
        "prompt": "請詳細分析串流模式。",
        "sentences": [
            ("串流模式能夠大幅縮短使用者的首音等待時間，帶來更即時的語音體驗。", 0.08),
            ("然而在網路抖動或模型思考間隔超過一秒時，舊架構容易誤判停頓而中斷對話。", 1.20),
            ("透過放寬間隔容限並保留上下文，數字人即可平滑講完所有句子。", 0.08),
        ],
        "token_delay_ms": 35,
    },
]


async def run_benchmark_turn(
    case: dict,
    streaming: bool,
) -> dict:
    clock = VirtualClock(1000.0)
    config = SimpleNamespace(
        asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
        vad=SimpleNamespace(),
        reply_streaming=SimpleNamespace(
            enabled=streaming,
            inter_fragment_timeout_seconds=5.0,
        ),
    )
    avatar = BenchmarkAvatar()
    session = VoiceTurnSession(101, config, avatar, clock=clock)
    session._metrics_clock = clock
    events: list[dict] = []
    session.attach_event_sink(lambda raw: events.append(json.loads(raw)))

    sentences = case["sentences"]
    token_delay = case["token_delay_ms"] / 1000.0

    full_text = "".join(s[0] for s in sentences)
    first_audio_time = None
    turn_start_time = clock.now
    tts_synthesis_latency = 0.25
    played_fragments = 0

    # In streaming mode, TTS runs concurrently as fragments are emitted
    audio_timeline = []

    def mock_llm_response(text, avatar_stream, **kwargs):
        nonlocal first_audio_time
        is_streaming = kwargs.get("stream_to_avatar", False)
        datainfo = kwargs.get("datainfo") or {}

        if not is_streaming:
            total_llm_duration = sum(len(s[0]) * token_delay + s[1] for s in sentences)
            clock.advance(total_llm_duration)
            return full_text

        fragmenter = SemanticFragmenter()
        frag_seq = 0
        for sentence_text, inter_sentence_pause in sentences:
            if inter_sentence_pause > 0:
                clock.advance(inter_sentence_pause)
            for char in sentence_text:
                clock.advance(token_delay)
                frags = fragmenter.feed(char)
                for frag in frags:
                    frag_info = {**datainfo, "fragment_sequence": frag_seq}
                    session.register_fragment(frag, frag_info)
                    avatar_stream.put_msg_txt(frag, frag_info)
                    frag_seq += 1
                    # When first fragment is emitted, it begins TTS immediately!
                    frag_audio_ready_at = clock.now + tts_synthesis_latency
                    num_frames = max(5, int(len(frag) * 7.5))
                    audio_timeline.append((frag_audio_ready_at, frag_info, num_frames))
        for frag in fragmenter.flush():
            frag_info = {**datainfo, "fragment_sequence": frag_seq}
            session.register_fragment(frag, frag_info)
            avatar_stream.put_msg_txt(frag, frag_info)
            frag_seq += 1
            frag_audio_ready_at = clock.now + tts_synthesis_latency
            num_frames = max(5, int(len(frag) * 7.5))
            audio_timeline.append((frag_audio_ready_at, frag_info, num_frames))

        return full_text

    with patch("src.server.voice_session.llm_response", side_effect=mock_llm_response):
        started = await session.start_text_turn(case["prompt"], interrupt=False)
        turn_task = session._turn_task
        await turn_task

    if streaming:
        # Simulate playback according to arrival timeline
        current_time = clock.now
        # Play the scheduled fragments
        for ready_at, eventpoint, num_audio_frames in audio_timeline:
            # If current clock is ahead of ready_at, play immediately; otherwise advance
            if ready_at > clock.now:
                # Inter-fragment silence while waiting for TTS
                gap_frames = int((ready_at - clock.now) / 0.02)
                for _ in range(gap_frames):
                    clock.advance(0.02)
                    session.on_output_audio(False)
            if first_audio_time is None:
                first_audio_time = min(audio_timeline[0][0] - turn_start_time, clock.now - turn_start_time)
            session.on_output_audio(True)
            session.on_output_audio_frame(eventpoint, True)

            for _ in range(num_audio_frames):
                clock.advance(0.02)
                session.on_output_audio(True)

            session.on_output_audio_frame({**eventpoint, "fragment_end": True}, True)
            played_fragments += 1

            # Inter-fragment 100ms pause
            for _ in range(5):
                clock.advance(0.02)
                session.on_output_audio(False)
    else:
        # In legacy mode, TTS only starts AFTER full LLM generation completes
        first_audio_time = clock.now - turn_start_time + tts_synthesis_latency
        clock.advance(tts_synthesis_latency)
        num_audio_frames = max(10, int(len(full_text) * 7.5))
        eventpoint = {
            "turn_id": started["turn_id"],
            "generation": 0,
            "fragment_sequence": 0,
        }
        session.on_output_audio(True)
        session.on_output_audio_frame(eventpoint, True)

        for frame_idx in range(num_audio_frames):
            clock.advance(0.02)
            session.on_output_audio(True)

        session.on_output_audio_frame({**eventpoint, "fragment_end": True}, True)
        played_fragments = 1

    for _ in range(5):
        clock.advance(0.02)
        session.on_output_audio(False)

    await asyncio.sleep(0.35)
    total_turn_time = clock.now - turn_start_time

    metrics = session.metrics_snapshot() or {}
    stale_drops = metrics.get("stale_drops", {})
    total_stale_drops = sum(stale_drops.values())

    error_events = [e for e in events if e.get("type") == "state" and e.get("state") == "error"]
    cancelled_events = [e for e in events if e.get("type") == "turn_cancelled"]
    is_failed = len(error_events) > 0 or len(cancelled_events) > 0

    await session.close()

    return {
        "mode": "streaming" if streaming else "legacy",
        "first_audio_seconds": round(first_audio_time, 3) if first_audio_time else None,
        "total_turn_seconds": round(total_turn_time, 3),
        "played_fragments": played_fragments,
        "stale_drops": total_stale_drops,
        "stale_drop_details": stale_drops,
        "failed": is_failed,
        "failure_reason": error_events[0].get("error") if error_events else None,
    }


async def main():
    print("=" * 80)
    print("基準測試：串流模式 (Streaming) vs 舊有模式 (Legacy)")
    print("=" * 80)
    print()

    results = []

    for case in TEST_CASES:
        print(f"▶ 測試情境: {case['name']}")
        print(f"  提示詞: \"{case['prompt']}\"")
        text_preview = " / ".join(s[0] for s in case["sentences"])
        print(f"  生成內容: {text_preview}")

        res_stream = await run_benchmark_turn(case, streaming=True)
        res_legacy = await run_benchmark_turn(case, streaming=False)

        results.append({
            "case": case["name"],
            "streaming": res_stream,
            "legacy": res_legacy,
        })

        print(f"  [Streaming] 首音延遲 (TTFT): {res_stream['first_audio_seconds']}s | 總耗時: {res_stream['total_turn_seconds']}s | 掉包/丟幀: {res_stream['stale_drops']} | 失敗狀態: {res_stream['failed']}")
        print(f"  [Legacy]    首音延遲 (TTFT): {res_legacy['first_audio_seconds']}s | 總耗時: {res_legacy['total_turn_seconds']}s | 掉包/丟幀: {res_legacy['stale_drops']} | 失敗狀態: {res_legacy['failed']}")
        if res_stream['first_audio_seconds'] and res_legacy['first_audio_seconds']:
            speedup = (res_legacy['first_audio_seconds'] - res_stream['first_audio_seconds']) / res_legacy['first_audio_seconds'] * 100
            print(f"  => 串流首音加速幅度: {speedup:.1f}%")
        print()

    print("=" * 80)
    print("總結報表 (JSON):")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
