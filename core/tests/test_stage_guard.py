# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's half of the training gate: GPU work never starts while a stage is connected.

The free-VRAM half of the guard belongs to the TTS layer (``test_training_gpu``); the
stage half reads the core's session registry and is decided first.
"""

from __future__ import annotations

from types import SimpleNamespace

from nova_contracts.tts import TrainingActivity, TrainingCheck, TrainingPreflight
from nova_core.server.stage_guard import (
    count_stage_connections,
    stage_connection_check,
    stage_offer_refusal,
    transcription_cpu_reason,
    with_core_checks,
)


def test_stage_connections_are_counted_from_the_session_registry(monkeypatch):
    from nova_core.server.state import state

    monkeypatch.setattr(state, "avatar_streams", {1: object(), 2: None})  # 2 is still connecting
    assert count_stage_connections() == 2


def test_stage_connection_check_names_the_count():
    assert stage_connection_check(0).status == "pass"
    blocked = stage_connection_check(3)
    assert (blocked.id, blocked.label) == ("stage_connections", "舞台連線")
    assert (blocked.status, blocked.detail) == ("fail", {"count": 3})
    assert blocked.reason == "有 3 個舞台正在連線，請先關閉再重新檢查"


def test_the_core_checks_come_first_and_decide_can_start_with_the_layers():
    vram = TrainingCheck(id="free_vram", label="剩餘顯存", status="pass", reason="夠")
    layer = TrainingPreflight(can_start=True, checks=(vram,))

    passing = with_core_checks(layer, stage_connection_check(0))
    blocked = with_core_checks(layer, stage_connection_check(1))

    assert [c.id for c in passing.checks] == ["admin", "stage_connections", "free_vram"] and passing.can_start
    assert not blocked.can_start


def test_a_connected_stage_means_cpu_for_a_transcription():
    assert transcription_cpu_reason(1) == "有舞台連線"
    assert transcription_cpu_reason(0) is None


def test_only_a_stage_offer_is_refused_and_only_while_training_runs():
    busy = SimpleNamespace(training_activity=lambda: TrainingActivity(active=True))
    idle = SimpleNamespace(training_activity=lambda: TrainingActivity(active=False))

    assert stage_offer_refusal("stage", busy).status == 409
    assert stage_offer_refusal("console", busy) is None
    assert stage_offer_refusal("stage", idle) is None
    assert stage_offer_refusal("stage", None) is None
