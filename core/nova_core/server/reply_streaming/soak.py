# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Content-free aggregation for the real reply-streaming soak."""
from __future__ import annotations

import math
from typing import Iterable, Mapping

from .metrics import STAGE_NAMES


def percentile(values: Iterable[float], percentile_value: float) -> float | None:
    samples = sorted(float(value) for value in values if value is not None)
    if not samples:
        return None
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    position = (len(samples) - 1) * percentile_value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(samples[lower], 6)
    weight = position - lower
    return round(samples[lower] * (1.0 - weight) + samples[upper] * weight, 6)


def build_soak_report(
    turns: list[Mapping],
    *,
    scenario_counts: Mapping[str, int],
    stale_events: int,
    environment: Mapping[str, str],
) -> dict:
    """Aggregate scalar telemetry without accepting transcript/audio fields."""
    first_audio = [item.get("first_audio_seconds") for item in turns]
    interrupt_stop = [
        item.get("interrupt_stop_seconds")
        for item in turns
        if item.get("interrupt_stop_seconds") is not None
    ]
    listening_resume = [
        item.get("listening_resume_seconds")
        for item in turns
        if item.get("listening_resume_seconds") is not None
    ]
    av_offsets = [item.get("max_abs_av_offset_seconds", 0.0) for item in turns]
    media_debts = [item.get("max_media_debt_seconds", 0.0) for item in turns]
    stale_drops = sum(
        int(count)
        for item in turns
        for count in dict(item.get("stale_drops") or {}).values()
    )
    stage_seconds = {
        stage: {
            "p50": percentile(
                (dict(item.get("stage_seconds") or {}).get(stage) for item in turns),
                50,
            ),
            "p95": percentile(
                (dict(item.get("stage_seconds") or {}).get(stage) for item in turns),
                95,
            ),
        }
        for stage in STAGE_NAMES
    }

    metrics = {
        "first_audio_seconds": {
            "p50": percentile(first_audio, 50),
            "p95": percentile(first_audio, 95),
            "target_p50_at_most": 1.2,
            "target_p95_at_most": 2.5,
        },
        "interrupt_stop_seconds": {
            "p95": percentile(interrupt_stop, 95),
            "target_p95_at_most": 0.2,
        },
        "listening_resume_seconds": {
            "p95": percentile(listening_resume, 95),
            "target_p95_at_most": 0.5,
        },
        "av_offset_seconds": {
            "p95": percentile(av_offsets, 95),
            "target_p95_at_most": 0.08,
        },
        "media_debt_seconds": {
            "maximum": max(media_debts, default=0.0),
            "target_at_most": 2.0,
        },
        "stage_seconds": stage_seconds,
    }
    checks = {
        "at_least_50_turns": len(turns) >= 50,
        "first_audio_p50": _at_most(metrics["first_audio_seconds"]["p50"], 1.2),
        "first_audio_p95": _at_most(metrics["first_audio_seconds"]["p95"], 2.5),
        "interrupt_stop": _at_most(
            metrics["interrupt_stop_seconds"]["p95"], 0.2
        ),
        "listening_resume": _at_most(
            metrics["listening_resume_seconds"]["p95"], 0.5
        ),
        "av_offset": _at_most(metrics["av_offset_seconds"]["p95"], 0.08),
        "media_debt": metrics["media_debt_seconds"]["maximum"] <= 2.0,
        "stale_output": stale_events == 0,
    }
    return {
        "schema_version": 1,
        "mode": "real_reply_streaming_soak",
        "turns": len(turns),
        "environment": dict(environment),
        "scenario_counts": dict(scenario_counts),
        "metrics": metrics,
        "stale_drop_count": stale_drops,
        "stale_output_events": int(stale_events),
        "checks": checks,
        "slo_pass": all(checks.values()),
    }


def _at_most(value: float | None, target: float) -> bool:
    return value is not None and value <= target
