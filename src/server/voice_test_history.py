# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Persistent, opt-in records for console-triggered voice pipeline tests."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Optional
from uuid import uuid4


SCHEMA_VERSION = 2
DEFAULT_HISTORY_LIMIT = 200
DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parents[2] / "logs" / "voice-test-history.json"
)
VOICE_TEST_THRESHOLDS = {
    "first_audio_seconds": 2.5,
    "max_abs_av_offset_seconds": 0.08,
    "max_media_debt_seconds": 2.0,
    "stale_drops_total": 0,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _drop_total(metrics: dict[str, Any], *, reason: str | None = None) -> int:
    drops = metrics.get("stale_drops") or {}
    return sum(
        int(value or 0)
        for key, value in drops.items()
        if (key == "webrtc_video:late_video") == (reason == "late_video")
    )


def evaluate_voice_test(
    terminal_reason: str,
    metrics: dict[str, Any],
    assistant_response: str,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Apply the existing single-turn SLO gates to one live console run."""
    first_audio = metrics.get("first_audio_seconds")
    av_offset = metrics.get("max_abs_av_offset_seconds")
    media_debt = metrics.get("max_media_debt_seconds")
    # `late_video` is deliberate video backpressure: the oldest unplayed
    # video frame is replaced to keep audio as the timing master. It is a
    # quality signal, but not an old generation escaping the cancellation
    # fence, so it must not fail the stale-output safety gate.
    stale_total = _drop_total(metrics)
    late_video_total = _drop_total(metrics, reason="late_video")
    checks = {
        "terminal_completed": {
            "label": "輪次完整完成",
            "value": terminal_reason,
            "operator": "=",
            "threshold": "completed",
            "applicable": True,
            "passed": terminal_reason == "completed",
        },
        "played_response": {
            "label": "實際播放回覆",
            "value": bool(assistant_response.strip()),
            "operator": "=",
            "threshold": True,
            "applicable": True,
            "passed": bool(assistant_response.strip()),
        },
        "first_audio_seconds": {
            "label": "首音延遲",
            "value": first_audio,
            "operator": "<=",
            "threshold": VOICE_TEST_THRESHOLDS["first_audio_seconds"],
            "unit": "s",
            "applicable": True,
            "passed": first_audio is not None
            and float(first_audio) <= VOICE_TEST_THRESHOLDS["first_audio_seconds"],
        },
        "max_abs_av_offset_seconds": {
            "label": "最大 A/V 偏差",
            "value": av_offset,
            "operator": "<=",
            "threshold": VOICE_TEST_THRESHOLDS["max_abs_av_offset_seconds"],
            "unit": "s",
            "applicable": True,
            "passed": av_offset is not None
            and float(av_offset)
            <= VOICE_TEST_THRESHOLDS["max_abs_av_offset_seconds"],
        },
        "max_media_debt_seconds": {
            "label": "最大媒體債務",
            "value": media_debt,
            "operator": "<=",
            "threshold": VOICE_TEST_THRESHOLDS["max_media_debt_seconds"],
            "unit": "s",
            "applicable": True,
            "passed": media_debt is not None
            and float(media_debt)
            <= VOICE_TEST_THRESHOLDS["max_media_debt_seconds"],
        },
        "stale_drops_total": {
            "label": "過期輸出",
            "value": stale_total,
            "operator": "=",
            "threshold": VOICE_TEST_THRESHOLDS["stale_drops_total"],
            "applicable": True,
            "passed": stale_total == VOICE_TEST_THRESHOLDS["stale_drops_total"],
        },
        "late_video_drops_total": {
            "label": "視訊背壓丟幀",
            "value": late_video_total,
            "operator": "info",
            "threshold": "0 preferred",
            "applicable": False,
            "passed": None,
        },
        "interrupt_stop_seconds": {
            "label": "插話停止",
            "value": metrics.get("interrupt_stop_seconds"),
            "operator": "<=",
            "threshold": 0.2,
            "unit": "s",
            "applicable": False,
            "passed": None,
        },
        "listening_resume_seconds": {
            "label": "恢復收音",
            "value": metrics.get("listening_resume_seconds"),
            "operator": "<=",
            "threshold": 0.5,
            "unit": "s",
            "applicable": False,
            "passed": None,
        },
    }
    passed = all(
        check["passed"] is True
        for check in checks.values()
        if check["applicable"]
    )
    return checks, passed


class VoiceTestHistory:
    """Keep a bounded JSON history and match terminal metrics by turn ID."""

    def __init__(
        self,
        path: Optional[os.PathLike[str] | str] = None,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        configured = os.environ.get("NOVA_AVATAR_VOICE_TEST_HISTORY")
        self.path = Path(path or configured or DEFAULT_HISTORY_PATH)
        self.limit = max(1, int(limit))
        self._lock = RLock()
        self._records: list[dict[str, Any]] = []
        self._pending: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = payload.get("results", [])
            if not isinstance(records, list):
                return
            self._records = [item for item in records if isinstance(item, dict)][
                : self.limit
            ]
        except (OSError, ValueError, TypeError):
            self._records = []
            return

        changed = False
        for record in self._records:
            if record.get("status") == "running":
                record["status"] = "interrupted"
                record["passed"] = False
                record["terminal_reason"] = "server_restarted"
                record["completed_at"] = _utc_now()
                changed = True
            elif record.get("status") in {"passed", "failed"}:
                checks, passed = evaluate_voice_test(
                    str(record.get("terminal_reason") or "unknown"),
                    dict(record.get("metrics") or {}),
                    str(record.get("assistant_response") or ""),
                )
                if record.get("checks") != checks or record.get("passed") != passed:
                    record["checks"] = checks
                    record["passed"] = passed
                    record["status"] = "passed" if passed else "failed"
                    changed = True
        if changed:
            self._write_locked()

    def _write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.{uuid4().hex}.tmp")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "results": self._records[: self.limit],
        }
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def begin(
        self,
        *,
        turn_id: str,
        prompt: str,
        session_id: int,
        environment: dict[str, Any],
        label: str = "",
    ) -> dict[str, Any]:
        record = {
            "id": uuid4().hex,
            "turn_id": turn_id,
            "session_id": int(session_id),
            "label": str(label or "").strip(),
            "prompt": str(prompt).strip(),
            "assistant_response": "",
            "environment": deepcopy(environment),
            "pipeline_mode": str(environment.get("reply_mode") or ""),
            "status": "running",
            "passed": None,
            "terminal_reason": None,
            "metrics": {},
            "checks": {},
            "started_at": _utc_now(),
            "completed_at": None,
        }
        with self._lock:
            self._records.insert(0, record)
            self._records = self._records[: self.limit]
            self._pending[turn_id] = record["id"]
            self._write_locked()
            return deepcopy(record)

    def complete(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        turn_id = str(payload.get("turn_id") or "")
        with self._lock:
            record_id = self._pending.pop(turn_id, None)
            if record_id is None:
                return None
            record = next(
                (item for item in self._records if item.get("id") == record_id),
                None,
            )
            if record is None:
                return None
            metrics = deepcopy(payload.get("metrics") or {})
            response = str(payload.get("assistant_response") or "")
            terminal_reason = str(payload.get("terminal_reason") or "unknown")
            checks, passed = evaluate_voice_test(
                terminal_reason,
                metrics,
                response,
            )
            record.update(
                {
                    "assistant_response": response,
                    "pipeline_mode": str(
                        payload.get("pipeline_mode") or record["pipeline_mode"]
                    ),
                    "status": "passed" if passed else "failed",
                    "passed": passed,
                    "terminal_reason": terminal_reason,
                    "metrics": metrics,
                    "checks": checks,
                    "completed_at": _utc_now(),
                }
            )
            self._write_locked()
            return deepcopy(record)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            bounded = max(1, min(int(limit), self.limit))
            return deepcopy(self._records[:bounded])

    def clear(self) -> int:
        with self._lock:
            count = len(self._records)
            self._records = []
            self._pending = {}
            self._write_locked()
            return count

    @property
    def has_running(self) -> bool:
        with self._lock:
            return bool(self._pending)
