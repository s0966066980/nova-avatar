# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Automatic transcription of a corpus: background job, progress, cancel, model release."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from nova_tts.training.corpus import CorpusError, CorpusStore
from nova_tts.training.gpu_guard import DeviceChoice
from nova_tts.training.transcription import (
    ALLOWED_MODELS,
    DEFAULT_MODEL,
    FasterWhisperTranscriber,
    TranscriptionJobs,
)

WAV = b"RIFF fixture wav bytes"
WAIT = 10.0


class FakeTranscriber:
    """Returns ``"text of <file stem>"``; can block, fail on chosen files and records its life."""

    def __init__(self, *, fail_on=(), blank_on=(), gate: threading.Event | None = None):
        self.fail_on, self.blank_on, self.gate = set(fail_on), set(blank_on), gate
        self.seen: list[str] = []
        self.thread: int | None = None
        self.closed = False
        self.entered = threading.Event()

    def transcribe(self, path: Path) -> str:
        self.thread = threading.get_ident()
        self.seen.append(path.name)
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(WAIT)
        if path.stem in self.fail_on:
            raise RuntimeError("decoder exploded")
        if path.stem in self.blank_on:
            return "  "
        return f"text of {path.stem}"

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def store(tmp_path: Path) -> CorpusStore:
    store = CorpusStore(tmp_path / "training")
    store.create("voice", source="self-recorded")
    return store


def add(store: CorpusStore, n: int, **kwargs) -> list[str]:
    return [store.add_line("voice", WAV, ".wav", original_name=f"t{i}.wav", **kwargs).id for i in range(n)]


GPU_OK = DeviceChoice("cuda")


def jobs_with(store: CorpusStore, transcriber: FakeTranscriber, choice: DeviceChoice = GPU_OK):
    made: list[str] = []

    def factory(model: str, device: str):
        made.append(model)
        return transcriber

    return TranscriptionJobs(store, factory, lambda: choice), made


# ------------------------------------------------------------------ the job


def test_a_job_fills_missing_transcripts_off_the_calling_thread_and_releases_the_model(store):
    ids = add(store, 3)
    fake = FakeTranscriber()
    jobs, made = jobs_with(store, fake)

    started = jobs.start("voice")
    assert started.state == "running" and started.total == 3
    assert jobs.wait(WAIT)

    status = jobs.status("voice")
    assert (status.state, status.done, status.total, status.failed) == ("done", 3, 3, ())
    assert [line.text for line in store.get("voice").lines] == [f"text of {i}" for i in ids]
    assert all(line.review == "pending" for line in store.get("voice").lines)  # still to be reviewed
    assert fake.thread != threading.get_ident()
    assert fake.closed
    assert made == [DEFAULT_MODEL]


def test_only_lines_without_text_that_are_not_excluded_are_transcribed(store):
    typed, blank, dropped = add(store, 1, text="已有逐字稿")[0], add(store, 1)[0], add(store, 1)[0]
    store.set_review("voice", dropped, "excluded")
    fake = FakeTranscriber()
    jobs, _ = jobs_with(store, fake)

    jobs.start("voice")
    assert jobs.wait(WAIT)

    texts = {line.id: line.text for line in store.get("voice").lines}
    assert texts[typed] == "已有逐字稿"
    assert texts[blank] != "" and texts[dropped] == ""
    assert len(fake.seen) == 1


def test_specific_lines_can_be_requested(store):
    first, second, _third = add(store, 3)
    fake = FakeTranscriber()
    jobs, _ = jobs_with(store, fake)

    assert jobs.start("voice", [second]).total == 1
    assert jobs.wait(WAIT)

    assert [line.text for line in store.get("voice").lines] == ["", "text of 000002", ""]
    assert first != second


def test_nothing_to_do_is_a_clear_error_and_starts_no_model(store):
    add(store, 1, text="已有逐字稿")
    fake = FakeTranscriber()
    jobs, made = jobs_with(store, fake)

    with pytest.raises(CorpusError) as excinfo:
        jobs.start("voice")

    assert excinfo.value.status == 409
    assert "沒有" in excinfo.value.message
    assert made == []


def test_unknown_lines_are_a_404(store):
    add(store, 1)
    jobs, _ = jobs_with(store, FakeTranscriber())

    with pytest.raises(CorpusError) as excinfo:
        jobs.start("voice", ["999999"])

    assert excinfo.value.status == 404


def test_a_failing_file_is_reported_and_the_rest_continue(store):
    add(store, 3)
    fake = FakeTranscriber(fail_on={"000002"}, blank_on={"000003"})
    jobs, _ = jobs_with(store, fake)

    jobs.start("voice")
    assert jobs.wait(WAIT)

    status = jobs.status("voice")
    assert status.state == "done" and status.done == 1
    assert [item.line_id for item in status.failed] == ["000002", "000003"]
    assert all(item.message for item in status.failed)
    assert [line.text for line in store.get("voice").lines] == ["text of 000001", "", ""]


def test_a_model_that_cannot_load_fails_the_job_with_its_reason(store):
    add(store, 1)

    def factory(model: str, device: str):
        raise OSError("model not cached")

    jobs = TranscriptionJobs(store, factory, lambda: GPU_OK)
    jobs.start("voice")
    assert jobs.wait(WAIT)

    status = jobs.status("voice")
    assert status.state == "failed"
    assert "model not cached" in status.message or "模型" in status.message
    assert status.done == 0


def test_only_one_job_runs_at_a_time(store):
    add(store, 2)
    gate = threading.Event()
    fake = FakeTranscriber(gate=gate)
    jobs, _ = jobs_with(store, fake)

    jobs.start("voice")
    assert fake.entered.wait(WAIT)
    with pytest.raises(CorpusError) as excinfo:
        jobs.start("voice")
    assert excinfo.value.status == 409
    gate.set()
    assert jobs.wait(WAIT)


def test_progress_is_visible_while_running_and_only_for_its_corpus(store):
    store.create("other", source="self-recorded")
    add(store, 2)
    gate = threading.Event()
    fake = FakeTranscriber(gate=gate)
    jobs, _ = jobs_with(store, fake)

    jobs.start("voice")
    assert fake.entered.wait(WAIT)

    running = jobs.status("voice")
    assert (running.state, running.total, running.done) == ("running", 2, 0)
    assert jobs.status("other").state == "idle"
    gate.set()
    assert jobs.wait(WAIT)
    assert jobs.status("voice").done == 2


def test_cancel_stops_after_the_current_file_and_still_releases_the_model(store):
    add(store, 3)
    gate = threading.Event()
    fake = FakeTranscriber(gate=gate)
    jobs, _ = jobs_with(store, fake)

    jobs.start("voice")
    assert fake.entered.wait(WAIT)
    assert jobs.cancel("voice").cancel_requested
    gate.set()
    assert jobs.wait(WAIT)

    status = jobs.status("voice")
    assert status.state == "cancelled" and status.done == 1
    assert len(fake.seen) == 1
    assert fake.closed
    assert [line.text for line in store.get("voice").lines] == ["text of 000001", "", ""]


def test_stop_cancels_a_running_job_and_waits_for_the_worker(store):
    add(store, 3)
    gate = threading.Event()
    fake = FakeTranscriber(gate=gate)
    jobs, _ = jobs_with(store, fake)
    jobs.start("voice")
    assert fake.entered.wait(WAIT)
    threading.Timer(0.05, gate.set).start()

    jobs.stop()

    assert jobs.status("voice").state == "cancelled"
    assert fake.closed


def test_cancel_without_a_running_job_is_a_conflict(store):
    add(store, 1)
    jobs, _ = jobs_with(store, FakeTranscriber())

    with pytest.raises(CorpusError) as excinfo:
        jobs.cancel("voice")

    assert excinfo.value.status == 409


def test_a_new_job_can_start_after_the_last_one_finished(store):
    add(store, 1)
    jobs, _ = jobs_with(store, FakeTranscriber())
    jobs.start("voice")
    assert jobs.wait(WAIT)
    add(store, 1)

    assert jobs.start("voice").state == "running"
    assert jobs.wait(WAIT)
    assert jobs.status("voice").total == 1


def test_a_transcript_typed_while_the_job_ran_is_not_overwritten(store):
    first, _second = add(store, 2)
    gate = threading.Event()
    fake = FakeTranscriber(gate=gate)
    jobs, _ = jobs_with(store, fake)

    jobs.start("voice")
    assert fake.entered.wait(WAIT)
    store.set_text("voice", first, "管理者自己打的")
    gate.set()
    assert jobs.wait(WAIT)

    assert store.get("voice").lines[0].text == "管理者自己打的"
    assert jobs.status("voice").skipped == 1


def test_only_listed_models_can_be_requested(store):
    add(store, 1)
    jobs, made = jobs_with(store, FakeTranscriber())

    with pytest.raises(CorpusError):
        jobs.start("voice", model="../../etc/passwd")
    with pytest.raises(CorpusError):
        jobs.start("voice", model="/home/me/model")

    assert "large-v3" in ALLOWED_MODELS and DEFAULT_MODEL in ALLOWED_MODELS
    assert made == []
    jobs.start("voice", model="small")
    assert jobs.wait(WAIT)
    assert made == ["small"]


# ------------------------------------------------------------------ the device


class RecordingChooser:
    """A fake guard decision that counts how often it is asked and can change its mind."""

    def __init__(self, *choices: DeviceChoice):
        self.choices = list(choices)
        self.calls = 0

    def __call__(self) -> DeviceChoice:
        self.calls += 1
        return self.choices[min(self.calls, len(self.choices)) - 1]


def test_the_status_reports_the_device_and_why_the_cpu_was_chosen(store):
    add(store, 1)
    made: list[tuple[str, str]] = []

    def factory(model: str, device: str):
        made.append((model, device))
        return FakeTranscriber()

    jobs = TranscriptionJobs(store, factory, lambda: DeviceChoice("cpu", "有舞台連線"))

    started = jobs.start("voice")
    assert (started.device, started.fallback_reason) == ("cpu", "有舞台連線")
    assert jobs.wait(WAIT)

    finished = jobs.status("voice")
    assert (finished.state, finished.device, finished.fallback_reason) == ("done", "cpu", "有舞台連線")
    assert made == [("medium", "cpu")]


def test_an_allowed_gpu_runs_on_cuda_without_a_reason(store):
    add(store, 1)
    jobs, _ = jobs_with(store, FakeTranscriber(), DeviceChoice("cuda"))

    started = jobs.start("voice")
    assert (started.device, started.fallback_reason) == ("cuda", None)
    assert jobs.wait(WAIT)
    assert (jobs.status("voice").device, jobs.status("voice").fallback_reason) == ("cuda", None)


def test_a_busy_gpu_still_transcribes_on_the_cpu_instead_of_refusing(store):
    ids = add(store, 2)
    jobs, _ = jobs_with(store, FakeTranscriber(), DeviceChoice("cpu", "剩餘顯存不足"))

    jobs.start("voice")
    assert jobs.wait(WAIT)

    assert jobs.status("voice").state == "done"
    assert [line.text for line in store.get("voice").lines] == [f"text of {i}" for i in ids]


def test_the_device_is_decided_once_at_start_and_a_running_job_does_not_migrate(store):
    add(store, 2)
    gate = threading.Event()
    fake = FakeTranscriber(gate=gate)
    chooser = RecordingChooser(DeviceChoice("cuda"), DeviceChoice("cpu", "有舞台連線"))
    devices: list[str] = []

    def factory(model: str, device: str):
        devices.append(device)
        return fake

    jobs = TranscriptionJobs(store, factory, chooser)
    jobs.start("voice")
    assert fake.entered.wait(WAIT)
    # The stage connects while the job runs: nothing is asked again and the job stays on the GPU.
    assert jobs.status("voice").device == "cuda"
    gate.set()
    assert jobs.wait(WAIT)

    assert chooser.calls == 1
    assert devices == ["cuda"]
    assert (jobs.status("voice").device, jobs.status("voice").fallback_reason) == ("cuda", None)


def test_a_gpu_that_fails_while_running_is_shown_as_the_cpu_with_a_reason(store):
    add(store, 2)

    class FallingBack(FakeTranscriber):
        device = "cuda"

        def transcribe(self, path: Path) -> str:
            self.device = "cpu"  # what FasterWhisperTranscriber does when CUDA fails on its first batch
            return super().transcribe(path)

    jobs, _ = jobs_with(store, FallingBack(), DeviceChoice("cuda"))
    jobs.start("voice")
    assert jobs.wait(WAIT)

    status = jobs.status("voice")
    assert (status.state, status.device) == ("done", "cpu")
    assert status.fallback_reason == "GPU 執行失敗，已改用 CPU"


def test_an_idle_status_has_no_device(store):
    jobs, _ = jobs_with(store, FakeTranscriber())
    status = jobs.status("voice")
    assert (status.state, status.device, status.fallback_reason) == ("idle", None, None)


def test_a_job_with_nothing_to_do_does_not_ask_the_guard(store):
    chooser = RecordingChooser(DeviceChoice("cuda"))
    jobs = TranscriptionJobs(store, lambda model, device: FakeTranscriber(), chooser)
    with pytest.raises(CorpusError):
        jobs.start("voice")
    assert chooser.calls == 0


# ------------------------------------------------------------------ the faster-whisper adapter


class FakeWhisperModel:
    def __init__(self, text: str = "软件开发的几个重点", language: str = "zh", fail: Exception | None = None):
        self.text, self.language, self.fail = text, language, fail
        self.calls: list[dict] = []

    def transcribe(self, audio, **options):
        self.calls.append({"audio": audio, **options})
        if self.fail is not None:
            raise self.fail
        segments = [SimpleNamespace(text=self.text[:3]), SimpleNamespace(text=self.text[3:])]
        return iter(segments), SimpleNamespace(language=self.language)


def test_the_adapter_detects_the_language_and_returns_traditional_chinese(tmp_path):
    model = FakeWhisperModel()
    transcriber = FasterWhisperTranscriber("medium", model_factory=lambda size, device: model)

    text = transcriber.transcribe(tmp_path / "a.wav")

    assert text == "軟體開發的幾個重點"  # s2twp: Taiwan wording as well as script
    assert model.calls[0]["language"] is None  # auto-detect
    assert model.calls[0]["audio"] == str(tmp_path / "a.wav")


def test_english_passes_through_unchanged(tmp_path):
    model = FakeWhisperModel(text="Hello there, nice to meet you.", language="en")
    transcriber = FasterWhisperTranscriber("small", model_factory=lambda size, device: model)

    assert transcriber.transcribe(tmp_path / "a.wav") == "Hello there, nice to meet you."


def test_the_model_is_loaded_lazily_once_and_released_on_close(tmp_path):
    built: list[tuple[str, str]] = []
    model = FakeWhisperModel()

    def factory(size, device):
        built.append((size, device))
        return model

    transcriber = FasterWhisperTranscriber("small", device="cpu", model_factory=factory)
    assert built == []
    transcriber.transcribe(tmp_path / "a.wav")
    transcriber.transcribe(tmp_path / "b.wav")
    assert built == [("small", "cpu")]

    transcriber.close()
    assert transcriber.loaded is False
    transcriber.close()  # idempotent


def test_a_gpu_that_cannot_run_falls_back_to_cpu_once(tmp_path):
    built: list[str] = []

    def factory(size, device):
        built.append(device)
        if device == "cuda":
            return FakeWhisperModel(fail=RuntimeError("Library libcublas.so.12 is not found"))
        return FakeWhisperModel()

    transcriber = FasterWhisperTranscriber("small", device="cuda", model_factory=factory)

    assert transcriber.transcribe(tmp_path / "a.wav") == "軟體開發的幾個重點"
    assert built == ["cuda", "cpu"]
    transcriber.transcribe(tmp_path / "b.wav")
    assert built == ["cuda", "cpu"]


def test_a_cpu_failure_is_not_retried(tmp_path):
    transcriber = FasterWhisperTranscriber(
        "small", device="cpu", model_factory=lambda s, d: FakeWhisperModel(fail=RuntimeError("bad audio"))
    )

    with pytest.raises(RuntimeError, match="bad audio"):
        transcriber.transcribe(tmp_path / "a.wav")


def test_running_is_true_only_while_a_job_works(tmp_path):
    import threading

    from nova_tts.training.corpus import CorpusStore
    from nova_tts.training.gpu_guard import DeviceChoice
    from nova_tts.training.transcription import TranscriptionJobs

    store = CorpusStore(tmp_path / "training")
    store.create("mine", source="self-recorded")
    store.add_line("mine", b"RIFF fixture", ".wav")
    gate = threading.Event()

    class Waiting:
        def transcribe(self, path):
            assert gate.wait(10)
            return "文字"

        def close(self):
            pass

    jobs = TranscriptionJobs(store, lambda model, device: Waiting(), lambda: DeviceChoice("cpu", "x"))
    assert jobs.running() is False
    jobs.start("mine", None, "small")
    assert jobs.running() is True
    gate.set()
    assert jobs.wait(10)
    assert jobs.running() is False
