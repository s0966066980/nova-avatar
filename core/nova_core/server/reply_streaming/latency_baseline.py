# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Content-free first-audio latency statistics for the real WebRTC harness.

Fixture utterances are synthetic text owned by this project; their audio is
synthesized in memory by the harness and never stored (ADR 0004). Reports
carry fixture IDs and scalar timings only.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np

from src.vad.audio import voiced_end_sample  # noqa: F401  (harness re-export)

from .metrics import AUDIBLE_PEAK, STAGE_NAMES
from .soak import percentile

CATEGORIES = ("general", "rag", "handoff")
LANGUAGES = ("zh-TW", "en-US")
HANDOFF_DIRECTIONS = ("to_specialist", "to_main")

# Spec targets, judged on perceived first-audio latency (CONTEXT.md).
TARGETS = {
    "general": {"phase1": {"p50": 1.2, "p95": 2.5}, "phase2": {"p50": 1.0, "p95": 1.5}},
    "rag": {"phase1": {"p50": 1.6, "p95": 3.0}},
    "handoff": {"phase1": {"p50": 1.6, "p95": 3.0}},
}

# Client-observed perceived latency minus the server estimate (VAD silence
# wait + first-audio latency). The remainder is uplink/downlink transport and
# where VAD places the end of speech. Outside this window the first active
# reply frame was not this turn's reply (e.g. a greeting still playing).
ALIGNMENT_WINDOW_SECONDS = (-0.3, 0.6)

ACTIVE_PEAK_THRESHOLD = AUDIBLE_PEAK  # int16 peak; decoded Opus silence stays below it

# Server clock marks are compared with the harness clock only when they read
# as one clock: the endpoint can follow the voice end by the speech tail,
# silence wait and transport, never precede it or lag by seconds.
SHARED_CLOCK_WINDOW_SECONDS = (0.0, 5.0)

# Client offset = these parts, in order along the turn.
OFFSET_PARTS = ("vad_speech_tail", "vad_processing", "uplink", "audible_onset", "downlink")

DEFINITIONS = {
    "perceived_first_audio_seconds": (
        "感知首音延遲：錄音中人聲實際結束 → 伺服器送出該輪第一個可聽（峰值 > 64）回覆音訊幀；"
        "以同主機共用的單調時鐘比對（perceived_basis=server_send）。伺服器未提供時鐘標記時"
        "退回用戶端收到時間（client_receive）。僅計入對齊的輪次"),
    "client_received_first_audio_seconds": (
        "錄音中人聲實際結束 → 量測工具（aiortc）收到第一個可聽回覆音訊幀；"
        "含工具自身的接收抖動緩衝與解碼，舞台瀏覽器不同"),
    "offset_split": (
        "client_offset 拆解：vad_speech_tail（人聲低於 -40 dBFS 後 VAD 仍判為語音）"
        "＋vad_processing（收到完成端點的上行幀 → 判定說完）＋uplink（工具送出 → 伺服器收到，"
        "含伺服器 aiortc 抖動緩衝）＋audible_onset（伺服器送出首個非零幀 → 首個可聽幀，"
        "TTS 起音前導）＋downlink（伺服器送出 → 工具收到，量測工具專屬）"),
    "server_perceived_first_audio_seconds": "伺服器估算：vad_endpoint + first_audio_seconds",
    "first_audio_seconds": "首音延遲：VAD 判定說完 → 伺服器送出第一個非靜音 WebRTC 回覆音訊幀",
    "prompt_first_audio_seconds": "伺服器接受 Prompt（辨識結果進入回覆流程）→ 第一個非靜音回覆音訊幀",
    "specialist_first_audio_seconds": "交接輪次：接手角色回覆的首音延遲（伺服器接受交接問題起算）",
    "stage_seconds": (
        "依序鏈：asr → pre_answer（含 retrieval；routing 與其並行）→ first_fragment"
        "（含 model_info、llm_first_token）→ avatar_to_webrtc_commit"
        "（含 routing_hold、tts_first_pcm、musetalk_first_batch、webrtc_audio_enqueue）"),
    "alignment": "server_residual = first_audio − 依序鏈；client_offset = 感知 − 伺服器估算",
}


@dataclass(frozen=True)
class LatencyFixture:
    fixture_id: str
    category: str
    language: str
    text: str
    handoff: Optional[str] = None


def _fixtures(category: str, rows: Sequence[tuple]) -> tuple[LatencyFixture, ...]:
    return tuple(LatencyFixture(row[0], category, row[1], row[2], *row[3:]) for row in rows)


FIXTURES: tuple[LatencyFixture, ...] = (
    *_fixtures("general", (
        ("general-zh-01", "zh-TW", "請用一句話簡短介紹臺灣。"),
        ("general-zh-02", "zh-TW", "規律運動有什麼好處？"),
        ("general-zh-03", "zh-TW", "早餐吃什麼比較健康？"),
        ("general-zh-04", "zh-TW", "怎麼樣才能睡得比較好？"),
        ("general-zh-05", "zh-TW", "你可以幫我做什麼？"),
        ("general-zh-06", "zh-TW", "推薦一個適合週末的休閒活動。"),
        ("general-en-01", "en-US", "What can you help me with today?"),
        ("general-en-02", "en-US", "Give me one tip for staying focused."),
        ("general-en-03", "en-US", "Why is drinking water important?"),
        ("general-en-04", "en-US", "Tell me a fun fact about Taiwan."),
        ("general-en-05", "en-US", "How should I prepare for a job interview?"),
    )),
    # Knowledge-base questions. Retrieval runs on every turn of a RAG-enabled
    # role; replace these with --fixtures when the site's knowledge base
    # covers other topics so the category exercises matched retrievals.
    *_fixtures("rag", (
        ("rag-zh-01", "zh-TW", "Nova Avatar 是什麼？"),
        ("rag-zh-02", "zh-TW", "這裡的服務時間是幾點到幾點？"),
        ("rag-zh-03", "zh-TW", "請問要怎麼預約參觀？"),
        ("rag-zh-04", "zh-TW", "這裡有提供哪些服務項目？"),
        ("rag-zh-05", "zh-TW", "請問聯絡電話是多少？"),
        ("rag-zh-06", "zh-TW", "停車場在哪裡？"),
        ("rag-en-01", "en-US", "What is Nova Avatar?"),
        ("rag-en-02", "en-US", "What are your opening hours?"),
        ("rag-en-03", "en-US", "How do I book a visit?"),
        ("rag-en-04", "en-US", "Which services do you offer here?"),
        ("rag-en-05", "en-US", "Where can I park?"),
    )),
    # Each weather question hands off to the specialist; the next non-weather
    # question returns to the main role, so every utterance is a handoff turn.
    *_fixtures("handoff", (
        ("handoff-zh-01", "zh-TW", "明天臺北市會下雨嗎？", "to_specialist"),
        ("handoff-zh-02", "zh-TW", "請介紹一下你們的服務。", "to_main"),
        ("handoff-zh-03", "zh-TW", "高雄市這週末天氣如何？", "to_specialist"),
        ("handoff-zh-04", "zh-TW", "推薦一本好書給我。", "to_main"),
        ("handoff-zh-05", "zh-TW", "臺中市明天氣溫幾度？", "to_specialist"),
        ("handoff-zh-06", "zh-TW", "怎麼樣才能放鬆心情？", "to_main"),
        ("handoff-en-01", "en-US", "Will it rain in Taipei tomorrow?", "to_specialist"),
        ("handoff-en-02", "en-US", "What can you help me with?", "to_main"),
        ("handoff-en-03", "en-US", "What is the weather forecast for Tainan this weekend?", "to_specialist"),
        ("handoff-en-04", "en-US", "Tell me a fun fact about Taiwan.", "to_main"),
    )),
)


def fixtures_from_json(raw: str) -> tuple[LatencyFixture, ...]:
    """Parse a site fixture file: [{"id","category","language","text","handoff"?}]."""
    items = json.loads(raw)
    if not isinstance(items, list) or not items:
        raise ValueError("fixture file must be a non-empty JSON list")
    fixtures = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each fixture must be an object")
        fixture = LatencyFixture(
            fixture_id=str(item.get("id") or ""),
            category=str(item.get("category") or ""),
            language=str(item.get("language") or ""),
            text=str(item.get("text") or "").strip(),
            handoff=item.get("handoff"),
        )
        if not fixture.fixture_id or not fixture.text:
            raise ValueError("fixture id and text are required")
        if fixture.category not in CATEGORIES:
            raise ValueError(f"unknown fixture category: {fixture.category}")
        if fixture.language not in LANGUAGES:
            raise ValueError(f"unsupported fixture language: {fixture.language}")
        if (fixture.category == "handoff") != (fixture.handoff in HANDOFF_DIRECTIONS):
            raise ValueError(f"handoff direction mismatch: {fixture.fixture_id}")
        fixtures.append(fixture)
    if len({f.fixture_id for f in fixtures}) != len(fixtures):
        raise ValueError("fixture ids must be unique")
    _handoff_pairs([f for f in fixtures if f.category == "handoff"])
    return tuple(fixtures)


def _handoff_pairs(handoffs: Sequence[LatencyFixture]) -> list[list[LatencyFixture]]:
    if len(handoffs) % 2:
        raise ValueError("handoff fixtures must come in to_specialist/to_main pairs")
    pairs = [list(handoffs[i:i + 2]) for i in range(0, len(handoffs), 2)]
    for forward, back in pairs:
        if (forward.handoff, back.handoff) != HANDOFF_DIRECTIONS:
            raise ValueError("handoff fixtures must come in to_specialist/to_main pairs")
    return pairs


def turn_plan(fixtures: Sequence[LatencyFixture], *, rounds: int = 1) -> list[LatencyFixture]:
    """Interleave categories round-robin; handoff pairs stay back to back."""
    if rounds < 1:
        raise ValueError("rounds must be positive")
    groups = {
        "general": [[f] for f in fixtures if f.category == "general"],
        "rag": [[f] for f in fixtures if f.category == "rag"],
        "handoff": _handoff_pairs([f for f in fixtures if f.category == "handoff"]),
    }
    one_round: list[LatencyFixture] = []
    for index in range(max(len(items) for items in groups.values())):
        for category in CATEGORIES:
            if index < len(groups[category]):
                one_round.extend(groups[category][index])
    return one_round * rounds


def is_active_audio(samples: np.ndarray, *, peak: int = ACTIVE_PEAK_THRESHOLD) -> bool:
    """Whether a received int16 reply frame is audible (same threshold as the server)."""
    pcm = np.asarray(samples)
    return bool(pcm.size) and int(np.max(np.abs(pcm.astype(np.int32)))) > peak


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 6)


def align_turn(record: Mapping, *, client_received_first_audio_seconds: Optional[float]) -> dict:
    """Check that server stages and the client observation describe one reply."""
    stages = dict(record.get("stage_seconds") or {})
    first_audio = record.get("first_audio_seconds")
    required = (stages.get("pre_answer"), stages.get("avatar_to_webrtc_commit"))
    chain = None
    if None not in required:
        chain = sum(float(stages.get(name) or 0.0) for name in
                    ("asr", "pre_answer", "first_fragment", "avatar_to_webrtc_commit"))
    residual = None if chain is None or first_audio is None else first_audio - chain
    vad = stages.get("vad_endpoint")
    server_perceived = None if vad is None or first_audio is None else vad + first_audio
    offset = (None if server_perceived is None or client_received_first_audio_seconds is None
              else client_received_first_audio_seconds - server_perceived)
    low, high = ALIGNMENT_WINDOW_SECONDS
    return {
        "chain_seconds": _round(chain),
        "server_residual_seconds": _round(residual),
        "server_perceived_first_audio_seconds": _round(server_perceived),
        "client_offset_seconds": _round(offset),
        "aligned": offset is not None and low <= offset <= high,
    }


def _shared_marks(metrics: Mapping, voice_ended_at: Optional[float]) -> Optional[dict]:
    """Server clock marks, when they are readings of the harness clock."""
    marks = dict(metrics.get("clock_marks") or {})
    if voice_ended_at is None or None in (marks.get("speech_end"), marks.get("first_audible")):
        return None
    low, high = SHARED_CLOCK_WINDOW_SECONDS
    if not low <= marks["speech_end"] - voice_ended_at <= high:
        return None
    return marks


def split_client_offset(
    metrics: Mapping,
    *,
    voice_ended_at: Optional[float],
    first_reply_audio_at: Optional[float],
) -> dict:
    """Perceived latency and the parts of the client offset for one turn.

    ``voice_ended_at`` and ``first_reply_audio_at`` are harness readings of
    ``time.monotonic``; the server's ``clock_marks`` share that clock only on
    the same host.
    """
    stages = dict(metrics.get("stage_seconds") or {})
    received = (None if voice_ended_at is None or first_reply_audio_at is None
                else first_reply_audio_at - voice_ended_at)
    split = {
        "vad_speech_tail": stages.get("vad_speech_tail"),
        "vad_processing": stages.get("vad_processing"),
        "uplink": None,
        "audible_onset": stages.get("webrtc_audible_onset"),
        "downlink": None,
    }
    marks = _shared_marks(metrics, voice_ended_at)
    if marks is None:
        return {"client_received": _round(received), "perceived": _round(received),
                "basis": "client_receive", "split": split}
    vad, tail = stages.get("vad_endpoint"), split["vad_speech_tail"]
    if vad is not None and tail is not None:
        split["uplink"] = _round(marks["speech_end"] - voice_ended_at - vad - tail
                                 - float(split["vad_processing"] or 0.0))
    if first_reply_audio_at is not None:
        split["downlink"] = _round(first_reply_audio_at - marks["first_audible"])
    return {"client_received": _round(received),
            "perceived": _round(marks["first_audible"] - voice_ended_at),
            "basis": "server_send", "split": split}


def build_turn_record(
    fixture: LatencyFixture,
    metric_event: Optional[Mapping],
    *,
    voice_ended_at: Optional[float] = None,
    first_reply_audio_at: Optional[float] = None,
    handoff_observed: bool = False,
    rag_status: Optional[str] = None,
    specialist_first_audio_seconds: Optional[float] = None,
    status: Optional[str] = None,
) -> dict:
    """One content-free per-turn record from a ``turn_metrics`` event."""
    record = {
        "fixture_id": fixture.fixture_id,
        "category": fixture.category,
        "language": fixture.language,
        "handoff_expected": fixture.handoff,
        "status": status or "timeout",
    }
    if metric_event is None:
        return record
    metrics = dict(metric_event.get("metrics") or {})
    client = split_client_offset(metrics, voice_ended_at=voice_ended_at,
                                 first_reply_audio_at=first_reply_audio_at)
    record.update(
        status=status or "completed",
        terminal_reason=metric_event.get("terminal_reason"),
        handoff_observed=bool(handoff_observed),
        rag_status=rag_status,
        perceived_first_audio_seconds=client["perceived"],
        perceived_basis=client["basis"],
        client_received_first_audio_seconds=client["client_received"],
        offset_split=client["split"],
        first_audio_seconds=metrics.get("first_audio_seconds"),
        prompt_first_audio_seconds=metrics.get("prompt_first_audio_seconds"),
        specialist_first_audio_seconds=specialist_first_audio_seconds,
        stage_seconds={stage: dict(metrics.get("stage_seconds") or {}).get(stage)
                       for stage in STAGE_NAMES},
    )
    record["alignment"] = align_turn(
        record, client_received_first_audio_seconds=client["client_received"])
    return record


_RECORD_KEYS = (
    "fixture_id", "category", "language", "status", "terminal_reason", "handoff_expected",
    "handoff_observed", "rag_status", "perceived_first_audio_seconds", "perceived_basis",
    "client_received_first_audio_seconds", "first_audio_seconds", "prompt_first_audio_seconds",
    "specialist_first_audio_seconds", "stage_seconds", "offset_split", "alignment",
)


def _p50_p95(values: Iterable[Optional[float]]) -> dict:
    samples = [value for value in values if value is not None]
    return {"p50": percentile(samples, 50), "p95": percentile(samples, 95)}


def _summarize(category: str, turns: list[Mapping], failed: int) -> dict:
    aligned = [turn for turn in turns if turn["alignment"]["aligned"]]
    perceived = _p50_p95(turn.get("perceived_first_audio_seconds") for turn in aligned)
    summary = {
        "turns": len(turns),
        "failed_turns": failed,
        "misaligned_turns": len(turns) - len(aligned),
        "perceived_first_audio_seconds": perceived,
        "perceived_basis": dict(Counter(turn["perceived_basis"] for turn in aligned
                                        if turn.get("perceived_basis"))),
        "client_received_first_audio_seconds": _p50_p95(
            turn.get("client_received_first_audio_seconds") for turn in aligned),
        "offset_split": {
            part: _p50_p95(dict(turn.get("offset_split") or {}).get(part) for turn in aligned)
            for part in OFFSET_PARTS
        },
        "server_perceived_first_audio_seconds": _p50_p95(
            turn["alignment"]["server_perceived_first_audio_seconds"] for turn in turns),
        "first_audio_seconds": _p50_p95(turn.get("first_audio_seconds") for turn in turns),
        "prompt_first_audio_seconds": _p50_p95(
            turn.get("prompt_first_audio_seconds") for turn in turns),
        "specialist_first_audio_seconds": _p50_p95(
            turn.get("specialist_first_audio_seconds") for turn in turns),
        "stage_seconds": {
            stage: _p50_p95(dict(turn.get("stage_seconds") or {}).get(stage) for turn in turns)
            for stage in STAGE_NAMES
        },
        "alignment": {
            "server_residual_seconds": _p50_p95(
                turn["alignment"]["server_residual_seconds"] for turn in turns),
            "client_offset_seconds": _p50_p95(
                turn["alignment"]["client_offset_seconds"] for turn in turns),
        },
        "handoff_observed_turns": sum(1 for turn in turns if turn.get("handoff_observed")),
        "rag_status": dict(Counter(turn["rag_status"] for turn in turns if turn.get("rag_status"))),
    }
    if category in TARGETS:
        summary["checks"] = {
            phase: (perceived["p50"] is not None and perceived["p95"] is not None
                    and perceived["p50"] <= target["p50"] and perceived["p95"] <= target["p95"])
            for phase, target in TARGETS[category].items()
        }
    return summary


def build_latency_report(turns: Sequence[Mapping], *, environment: Mapping[str, str]) -> dict:
    """Aggregate per-turn scalar records into P50/P95 per category."""
    completed = [turn for turn in turns if turn.get("status") == "completed"]
    failed = Counter(turn.get("category") for turn in turns if turn.get("status") != "completed")
    categories = {"all": _summarize("all", completed, sum(failed.values()))}
    for category in CATEGORIES:
        categories[category] = _summarize(
            category, [turn for turn in completed if turn.get("category") == category],
            failed[category],
        )
    return {
        "schema_version": 2,
        "mode": "first_audio_latency",
        "environment": dict(environment),
        "definitions": DEFINITIONS,
        "targets": TARGETS,
        "turns_total": len(turns),
        "failed_turns": sum(failed.values()),
        "categories": categories,
        "turn_records": [
            {key: turn[key] for key in _RECORD_KEYS if key in turn} for turn in turns
        ],
    }
