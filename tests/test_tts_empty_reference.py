# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""An empty reference (allowed by check_reference, left by migration) must not break the engine."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from src.tts.engines.indextts2 import IndexTTS2
from src.tts.engines.sovits import SovitsTTS
from src.tts.engines.xtts import XTTS


def _config():
    return SimpleNamespace(audio=SimpleNamespace(fps=50), tts=SimpleNamespace(
        ref_file="", ref_text="", tts_server="http://127.0.0.1:9880"))


class Parent:
    def put_audio_frame(self, *_args, **_kwargs):
        pass


def _refuse_network(*_args, **_kwargs):
    raise AssertionError("no request may be sent without a reference")


def test_sovits_leaves_an_empty_reference_to_the_server_default(monkeypatch):
    sent = []

    class Response:
        status_code = 400
        text = "ref_audio_path is required"

        def iter_content(self, chunk_size=None):
            return iter(())

    def post(url, json, **_):
        sent.append(json)
        return Response()

    monkeypatch.setattr("src.tts.engines.sovits.requests.post", post)
    with pytest.raises(RuntimeError, match="沒有產生音訊"):
        SovitsTTS(_config(), Parent()).txt_to_audio(("你好", {}))
    assert sent[0]["ref_audio_path"] == ""


def test_xtts_without_a_reference_still_builds_and_fails_per_utterance(monkeypatch):
    monkeypatch.setattr("src.tts.engines.xtts.requests.post", _refuse_network)
    tts = XTTS(_config(), Parent())
    with pytest.raises(RuntimeError, match="參考音訊"):
        tts.txt_to_audio(("你好", {}))


def test_indextts2_without_a_reference_builds_and_never_uploads_a_path(monkeypatch):
    uploaded = []
    fake = ModuleType("gradio_client")
    fake.Client = lambda *a, **k: SimpleNamespace(submit=_refuse_network)  # type: ignore[attr-defined]
    fake.handle_file = uploaded.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gradio_client", fake)
    tts = IndexTTS2(_config(), Parent())
    assert tts.indextts2_generate("你好") is None
    assert uploaded == []
