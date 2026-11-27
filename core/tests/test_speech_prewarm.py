# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core composes VAD and recognizer prewarm; the STT layer only knows its recognizer."""
from types import SimpleNamespace

from nova_core.server import speech_prewarm


class FakeVad:
    frame_samples = 320

    def __init__(self):
        self.closed = False

    def ensure_ready(self):
        return None

    def speech_prob(self, _frame):
        return 0.0

    def close(self):
        self.closed = True


def config(vad_enabled=True):
    return SimpleNamespace(vad=SimpleNamespace(enabled=vad_enabled))


def test_nothing_to_prime_when_the_vad_is_off(monkeypatch):
    monkeypatch.setattr(speech_prewarm, "prewarm_asr", lambda _c: (_ for _ in ()).throw(AssertionError))

    assert speech_prewarm.prewarm_speech_input(config(False)) is True


def test_primes_the_vad_then_the_recognizer_and_closes_the_vad(monkeypatch):
    vad, calls = FakeVad(), []
    monkeypatch.setattr(speech_prewarm, "create_vad_from_config", lambda *_: vad)
    monkeypatch.setattr(speech_prewarm, "prewarm_asr", lambda _c: calls.append("asr"))

    assert speech_prewarm.prewarm_speech_input(config()) is True
    assert calls == ["asr"] and vad.closed


def test_a_recognizer_failure_reports_false_and_still_closes_the_vad(monkeypatch):
    vad = FakeVad()
    monkeypatch.setattr(speech_prewarm, "create_vad_from_config", lambda *_: vad)
    monkeypatch.setattr(speech_prewarm, "prewarm_asr", lambda _c: (_ for _ in ()).throw(RuntimeError("x")))

    assert speech_prewarm.prewarm_speech_input(config()) is False
    assert vad.closed
