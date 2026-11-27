# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core, not the renderer, builds the TTS engine a session speaks with."""
from types import SimpleNamespace

from src.server import speech


def test_core_speech_factory_builds_the_configured_engine_for_the_sink(monkeypatch):
    built = []
    monkeypatch.setattr(
        speech, "create_tts_engine",
        lambda tts_type, config, sink: built.append((tts_type, config, sink)) or "engine",
    )
    config = SimpleNamespace(tts=SimpleNamespace(type="matcha"))
    sink = object()

    assert speech.tts_speech_factory(config, sink) == "engine"
    assert built == [("matcha", config, sink)]
