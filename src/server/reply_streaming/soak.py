# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Content-free aggregation for the real reply-streaming soak."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .metrics import STAGE_NAMES


def sample_rss_mb(pid: int | None = None) -> float | None:
    """Read current resident memory (VmRSS) in MiB from Linux procfs."""
    target = str(pid) if pid is not None else "self"
    status_path = Path(f"/proc/{target}/status")
    try:
        content = status_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    kib = float(parts[1])
                except ValueError:
                    return None
                return round(kib / 1024.0, 3)
    return None


def summarize_memory_trend(samples_mb: Iterable[float]) -> dict | None:
    """Summarize RSS trend and linear growth rate without any content payloads."""
    values = [float(v) for v in samples_mb if v is not None and math.isfinite(float(v))]
    if not values:
        return None
    n = len(values)
    if n == 1:
        slope = 0.0
    else:
        mean_x = (n - 1) / 2.0
        mean_y = sum(values) / n
        denom = sum((i - mean_x) ** 2 for i in range(n))
        slope = (
            sum((i - mean_x) * (val - mean_y) for i, val in enumerate(values)) / denom
            if denom > 0
            else 0.0
        )
    return {
        "sample_count": n,
        "initial_mb": round(values[0], 3),
        "final_mb": round(values[-1], 3),
        "peak_mb": round(max(values), 3),
        "delta_mb": round(values[-1] - values[0], 3),
        "slope_mb_per_sample": round(slope, 6),
    }


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


def _summarize_recovery(recovery_results: Sequence[Mapping]) -> dict:
    total = len(recovery_results)
    passed = sum(1 for item in recovery_results if bool(item.get("passed")))
    reconnect_count = sum(
        1 for item in recovery_results if item.get("type") == "reconnect"
    )
    rejection_count = sum(
        1
        for item in recovery_results
        if item.get("type") == "speech_gate_rejection"
    )
    return {
        "total_probes": total,
        "passed_probes": passed,
        "failed_probes": total - passed,
        "reconnect_count": reconnect_count,
        "rejection_probe_count": rejection_count,
        "all_passed": passed == total,
    }


def build_soak_report(
    turns: list[Mapping],
    *,
    scenario_counts: Mapping[str, int],
    stale_events: int,
    environment: Mapping[str, str],
    max_first_audio_p50: float = 1.2,
    max_first_audio_p95: float = 2.5,
    memory_samples_mb: Sequence[float] | None = None,
    max_rss_growth_mb: float = 256.0,
    recovery_results: Sequence[Mapping] | None = None,
) -> dict:
    """Aggregate scalar telemetry without accepting transcript/audio fields."""
    if max_first_audio_p50 <= 0 or max_first_audio_p95 <= 0:
        raise ValueError("first audio latency budgets must be positive")
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
            "target_p50_at_most": float(max_first_audio_p50),
            "target_p95_at_most": float(max_first_audio_p95),
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
        "first_audio_p50": _at_most(
            metrics["first_audio_seconds"]["p50"], float(max_first_audio_p50)
        ),
        "first_audio_p95": _at_most(
            metrics["first_audio_seconds"]["p95"], float(max_first_audio_p95)
        ),
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
    report = {
        "schema_version": 1,
        "mode": "real_reply_streaming_soak",
        "turns": len(turns),
        "environment": dict(environment),
        "scenario_counts": dict(scenario_counts),
        "metrics": metrics,
        "stale_drop_count": stale_drops,
        "stale_output_events": int(stale_events),
        "checks": checks,
    }
    if recovery_results is not None:
        recovery_summary = _summarize_recovery(recovery_results)
        report["recovery"] = recovery_summary
        checks["recovery_passed"] = recovery_summary["all_passed"]
    if memory_samples_mb is not None:
        memory_trend = summarize_memory_trend(memory_samples_mb)
        if memory_trend is not None:
            memory_trend["target_growth_at_most_mb"] = float(max_rss_growth_mb)
            report["memory_trend"] = memory_trend
            checks["memory_leak_guard"] = (
                memory_trend["delta_mb"] <= float(max_rss_growth_mb)
            )
    report["slo_pass"] = all(checks.values())
    return report


def _at_most(value: float | None, target: float) -> bool:
    return value is not None and value <= target
