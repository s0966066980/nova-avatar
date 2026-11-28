# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""CPU Whisper check: the transcriber protocol and the worker, with fake children and a fake model."""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from nova_tts.training import whisper_worker
from nova_tts.training import asr
from nova_tts.training.asr import SubprocessTranscriber, TranscriberCancelled, TranscriberError
from training_fakes import FakeProcess, FakeSpawner

pytestmark = pytest.mark.speech


def worker(replies: dict[str, str] | None = None, *, crash_after: int | None = None, noise: bool = False):
    """A fake whisper worker: ready line, then one reply per request."""
    replies = replies or {}
    served = []

    def on_line(text: str):
        request = json.loads(text)
        served.append(request["path"])
        if crash_after is not None and len(served) > crash_after:
            process._finish(1)
            return []
        out = [json.dumps({"text": replies.get(Path(request["path"]).name, "")}, ensure_ascii=False)]
        return ["loading noise"] + out if noise else out

    process = FakeProcess([json.dumps({"ready": True})], returncode=None, on_line=on_line)
    process.served = served
    return process


def test_transcriber_runs_the_worker_on_the_cpu_with_the_app_interpreter(tmp_path):
    process = worker({"a.wav": "你好"})
    spawner = FakeSpawner(lambda *_: process)
    with SubprocessTranscriber("base", spawn=spawner, root=tmp_path, environ={"CUDA_VISIBLE_DEVICES": "0", "X": "1"}) as transcribe:
        assert transcribe(Path("/corpus/a.wav")) == "你好"
    command = spawner.commands[0]
    assert command[0] == sys.executable
    assert command[1:] == ["-m", "nova_tts.training.whisper_worker", "--model", "base"]
    assert spawner.envs[0]["CUDA_VISIBLE_DEVICES"] == "" and spawner.envs[0]["X"] == "1"
    assert spawner.cwds[0] == tmp_path
    assert process.signals == ["TERM"]  # released when the context ends


def test_transcriber_ignores_library_noise_between_replies():
    process = worker({"a.wav": "好"}, noise=True)
    with SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process)) as transcribe:
        assert transcribe(Path("a.wav")) == "好"
        assert transcribe(Path("a.wav")) == "好"


def test_a_worker_that_dies_mid_run_is_an_error_not_an_empty_text():
    process = worker(crash_after=1)
    with SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process)) as transcribe:
        transcribe(Path("a.wav"))
        with pytest.raises(TranscriberError, match="意外結束"):
            transcribe(Path("b.wav"))


def test_a_worker_that_never_becomes_ready_reports_what_it_printed():
    process = FakeProcess(["Traceback: no module named faster_whisper"], returncode=1)
    with pytest.raises(TranscriberError, match="no module named faster_whisper"):
        SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process)).__enter__()
    assert process.signals == ["TERM"]


def test_a_worker_error_reply_is_raised():
    process = FakeProcess([json.dumps({"ready": True})], returncode=None, on_line=lambda _: [json.dumps({"error": "RuntimeError: bad file"})])
    with SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process)) as transcribe:
        with pytest.raises(TranscriberError, match="bad file"):
            transcribe(Path("a.wav"))


def test_an_unknown_model_size_is_refused():
    with pytest.raises(ValueError, match="Whisper model"):
        SubprocessTranscriber("gigantic")


# --- timeouts and cancel -------------------------------------------------------


@pytest.fixture
def fast_polling(monkeypatch):
    monkeypatch.setattr(asr, "POLL_SECONDS", 0.01)


def silent_worker():
    """Ready at once, then never answers a request."""
    return FakeProcess([json.dumps({"ready": True})], returncode=None, on_line=lambda _: [])


def test_an_utterance_that_gets_no_answer_times_out_and_the_child_is_killed(fast_polling):
    process = silent_worker()
    with SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process), utterance_timeout=0.1) as transcribe:
        started = time.monotonic()
        with pytest.raises(TranscriberError, match="逾時"):
            transcribe(Path("a.wav"))
        assert time.monotonic() - started < 5
    assert "KILL" in process.signals  # a stuck recognition must not hold the CPU or the GPU


def test_after_a_timeout_the_transcriber_does_not_use_the_dead_child_again(fast_polling):
    process = silent_worker()
    with SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process), utterance_timeout=0.05) as transcribe:
        with pytest.raises(TranscriberError, match="逾時"):
            transcribe(Path("a.wav"))
        written = len(process.written)
        with pytest.raises(TranscriberError):
            transcribe(Path("b.wav"))
        assert len(process.written) == written


def test_the_timeout_counts_per_utterance_not_for_the_whole_run(fast_polling):
    process = worker({"a.wav": "好", "b.wav": "好"})
    with SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process), utterance_timeout=5.0) as transcribe:
        assert [transcribe(Path("a.wav")), transcribe(Path("b.wav"))] == ["好", "好"]
    assert "KILL" not in process.signals


def test_a_child_that_never_gets_ready_times_out(fast_polling):
    process = FakeProcess([], returncode=None)
    transcriber = SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process), startup_timeout=0.05)
    with pytest.raises(TranscriberError, match="逾時"):
        transcriber.__enter__()
    assert "KILL" in process.signals


def test_cancel_kills_the_child_without_waiting_for_the_utterance(fast_polling):
    process = silent_worker()
    cancel = threading.Event()
    transcriber = SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process), utterance_timeout=60, cancel=cancel)
    with transcriber as transcribe:
        threading.Timer(0.05, cancel.set).start()
        started = time.monotonic()
        with pytest.raises(TranscriberCancelled):
            transcribe(Path("a.wav"))
        assert time.monotonic() - started < 5
    assert "KILL" in process.signals


def test_a_cancel_before_the_first_utterance_sends_nothing(fast_polling):
    process = worker({"a.wav": "好"})
    cancel = threading.Event()
    with SubprocessTranscriber(spawn=FakeSpawner(lambda *_: process), cancel=cancel) as transcribe:
        cancel.set()
        with pytest.raises(TranscriberCancelled):
            transcribe(Path("a.wav"))
    assert process.served == []


# --- the worker itself, with a fake faster-whisper model -----------------------


class FakeModel:
    def __init__(self, detected: str, scores: dict[str, float] | None = None, text: str = "hello"):
        self.calls: list[str | None] = []
        self._detected, self._scores, self._text = detected, scores or {}, text

    def transcribe(self, path, language=None, **options):
        self.calls.append(language)
        info = SimpleNamespace(language=self._detected, all_language_probs=list(self._scores.items()))
        return iter([SimpleNamespace(text=self._text[:3]), SimpleNamespace(text=self._text[3:] + " ")]), info


def serve(model, requests: list[str]) -> list[dict]:
    out = io.StringIO()
    whisper_worker.serve(model, requests, out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_worker_announces_ready_then_answers_each_request():
    replies = serve(FakeModel("zh", text="你好嗎"), [json.dumps({"path": "a.wav"}), "", json.dumps({"path": "b.wav"})])
    assert replies == [{"ready": True}, {"text": "你好嗎"}, {"text": "你好嗎"}]


def test_worker_decodes_again_as_zh_or_en_when_detection_picks_another_language():
    model = FakeModel("ja", {"en": 0.2, "zh": 0.5, "ja": 0.9}, text="歡迎使用")
    replies = serve(model, [json.dumps({"path": "a.wav"})])
    assert replies[1] == {"text": "歡迎使用"}
    assert model.calls == [None, "zh"]


def test_worker_reports_a_failing_request_and_keeps_serving():
    class Broken(FakeModel):
        def transcribe(self, path, language=None, **options):
            if path == "bad.wav":
                raise RuntimeError("cannot decode")
            return super().transcribe(path, language, **options)

    replies = serve(Broken("en", text="ok!"), [json.dumps({"path": "bad.wav"}), "not json", json.dumps({"path": "a.wav"})])
    assert replies[1]["error"].startswith("RuntimeError: cannot decode")
    assert "error" in replies[2]  # the malformed request line
    assert replies[3] == {"text": "ok!"}
