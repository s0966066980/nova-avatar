# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Training jobs: pre-flight checks, the stage pipeline, cancel, log and restart recovery.

Everything outside the process is fake: the children (training, export, Whisper, the
sherpa-onnx check), Edge, the GPU probe and the stage-session count. No network, no
model, no GPU, no server.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from src.config.loader import dict_to_config
from src.server import tts_training_jobs as jobs
from src.server.tts_training_jobs import (
    JobLog,
    StartRequest,
    TrainingError,
    TrainingJobManager,
    TrainingParams,
    TrainingPaths,
    TrainingSettings,
)
from src.tts.training import edge_teacher
from src.tts.training.asr import TranscriberError
from src.tts.training.corpus import REVIEW_CONFIRMED
from src.tts.training.edge_acknowledgement import MSA_CLAUSE, record_acknowledgement
from src.tts.training.gpu_probe import VramReading
from src.tts.training.usage import SOURCE_EDGE_TEST_TEACHER
from src.tts.voice_models import REQUIRED_FILES, list_voice_models
from tests.training_fakes import FakeProcess, FakeSpawner, argument, tone_wav
from tests.training_fakes import ENOUGH_VRAM_MIB, Rig, edge_synthesis, rig  # noqa: F401


def request(**overrides) -> StartRequest:
    values = {"corpus": "voice", "name": "我的聲音"}
    return StartRequest(**{**values, **overrides})


def finish(r: Rig, **overrides) -> dict:
    r.manager.start(request(**overrides))
    r.manager.join(20)
    return r.manager.status()


def check_of(preflight, check_id: str):
    return next(c for c in preflight.checks if c.id == check_id)


def wait_for(predicate, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached in time")


def stage_status(r: Rig, stage_id: str) -> str:
    snap = r.manager.status()
    return next(s["status"] for s in snap["stages"] if s["id"] == stage_id)


# --------------------------------------------------------------------------- pre-flight


def test_everything_in_order_can_start_and_each_check_has_a_reason(tmp_path):
    preflight = rig(tmp_path).manager.evaluate_preflight("voice", "我的聲音")
    assert preflight.can_start
    assert [c.id for c in preflight.checks] == [
        "admin", "stage_connections", "free_vram", "environment", "other_job", "transcription", "corpus", "corpus_size",
        "model_name",
    ]
    assert all(c.reason and c.label for c in preflight.checks)
    as_dict = preflight.to_dict()
    assert as_dict["can_start"] is True and as_dict["checks"][2]["detail"] == {"free_gb": 9.6, "threshold_gb": 8.0}


def test_a_stage_connection_blocks_with_the_count(tmp_path):
    preflight = rig(tmp_path, sessions=2).manager.evaluate_preflight("voice", "x")
    check = check_of(preflight, "stage_connections")
    assert (check.status, check.detail) == ("fail", {"count": 2})
    assert "2" in check.reason and not preflight.can_start


@pytest.mark.parametrize(
    ("free_mib", "passes"),
    # The boundary itself is gpu_guard's rule (test_training_gpu); this checks the wiring.
    [(3000, False), (24000, True)],
)
def test_free_vram_is_compared_with_the_threshold(tmp_path, free_mib, passes):
    check = check_of(rig(tmp_path, vram=VramReading(free_mib)).manager.evaluate_preflight("voice", "x"), "free_vram")
    assert (check.status == "pass") is passes
    assert "8 GB" in check.reason


def test_the_vram_threshold_is_configurable(tmp_path):
    r = rig(tmp_path, vram=VramReading(6 * 1024), settings=TrainingSettings(min_free_vram_gb=4))
    assert check_of(r.manager.evaluate_preflight("voice", "x"), "free_vram").status == "pass"


def test_a_missing_training_environment_is_listed(tmp_path):
    r = rig(tmp_path, with_env=False)
    check = check_of(r.manager.evaluate_preflight("voice", "x"), "environment")
    assert check.status == "fail" and "setup-matcha-train.sh" in check.reason
    assert any("matcha-train" in item for item in check.detail["missing"])
    assert any("pytorch_model_sherpa.bin" in item for item in check.detail["missing"])


def test_an_edge_corpus_needs_the_recorded_acknowledgement(tmp_path):
    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[])
    check = check_of(r.manager.evaluate_preflight("voice", "x"), "edge_acknowledgement")
    assert check.status == "fail" and MSA_CLAUSE.reference in check.reason
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    check = check_of(r.manager.evaluate_preflight("voice", "x"), "edge_acknowledgement")
    assert check.status == "pass" and check.detail["acknowledged_at"]


def test_an_uploaded_corpus_has_no_edge_check(tmp_path):
    ids = [c.id for c in rig(tmp_path).manager.evaluate_preflight("voice", "x").checks]
    assert "edge_acknowledgement" not in ids


def test_an_edge_corpus_without_lines_is_checked_again_after_synthesis(tmp_path):
    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[])
    check = check_of(r.manager.evaluate_preflight("voice", "x"), "corpus")
    assert check.status == "pass" and "合成後" in check.reason


@pytest.mark.parametrize(
    ("texts", "confirm", "expected"),
    [
        (["我有三個蘋果"], False, "待確認"),
        (["我有$50"], True, "數字"),
        ([], True, "沒有已確認"),
    ],
)
def test_a_corpus_that_is_not_fully_confirmed_blocks(tmp_path, texts, confirm, expected):
    r = rig(tmp_path, texts=[])
    for text in texts:
        line = r.store.add_line("voice", tone_wav(), ".wav", text)
        if confirm:
            r.store.set_review("voice", line.id, REVIEW_CONFIRMED)
    check = check_of(r.manager.evaluate_preflight("voice", "x"), "corpus")
    assert check.status == "fail" and expected in check.reason


def test_a_missing_corpus_and_an_undeclared_source_block(tmp_path):
    r = rig(tmp_path)
    assert check_of(r.manager.evaluate_preflight(None, "x"), "corpus").status == "fail"
    assert check_of(r.manager.evaluate_preflight("nothing", "x"), "corpus").status == "fail"
    r.store.create("bare")
    assert "來源" in check_of(r.manager.evaluate_preflight("bare", "x"), "corpus").reason


def test_a_small_corpus_only_warns(tmp_path):
    preflight = rig(tmp_path).manager.evaluate_preflight("voice", "我的聲音")
    size = check_of(preflight, "corpus_size")
    assert size.status == "warn" and "15 分鐘" in size.reason
    assert preflight.can_start


def test_a_bad_model_name_fails_the_preflight(tmp_path):
    """The naming rules are check_model_name's (test_training_bundle); this checks the wiring."""
    check = check_of(rig(tmp_path).manager.evaluate_preflight("voice", ""), "model_name")
    assert check.status == "fail"


def test_the_model_name_must_be_unique_among_voice_models(tmp_path):
    r = rig(tmp_path)
    voices = r.paths.voice_root / "existing"
    voices.mkdir(parents=True)
    for name in REQUIRED_FILES:
        (voices / name).write_bytes(b"x")
    (voices / "voice.json").write_text(
        json.dumps({"name": "我的聲音", "usage": "Development only", "languages": ["zh-TW"], "source": "s"}), encoding="utf-8"
    )
    assert check_of(r.manager.evaluate_preflight("voice", "我的聲音"), "model_name").status == "fail"
    assert check_of(r.manager.evaluate_preflight("voice", "另一個"), "model_name").status == "pass"


def test_a_refused_start_creates_no_job_and_starts_no_process(tmp_path):
    r = rig(tmp_path, sessions=1, vram=VramReading(1024))
    with pytest.raises(TrainingError) as caught:
        r.manager.start(request())
    error = caught.value
    assert error.status == 409
    failing = {c.id for c in error.preflight.checks if c.status == "fail"}
    assert failing == {"stage_connections", "free_vram"}
    assert "舞台" in error.message and "顯存" in error.message
    assert r.spawner.commands == [] and r.manager.status() is None


# --------------------------------------------------------------------------- the pipeline


def test_an_uploaded_corpus_trains_and_appears_in_the_voice_list(tmp_path):
    r = rig(tmp_path)
    snapshot = finish(r)
    assert snapshot["status"] == "done", snapshot["error"]
    assert [s["id"] for s in snapshot["stages"]] == ["environment", "preparation", "quality", "training", "export"]
    assert {s["status"] for s in snapshot["stages"]} == {"done"} and snapshot["progress"] == 100

    (model,) = list_voice_models(r.paths.voice_root)
    assert model.id == snapshot["voice_id"] and model.id.startswith("trained-")
    assert (model.name, model.usage, model.languages) == ("我的聲音", "Research / Non-commercial", ("zh-TW", "en-US"))
    assert "self-recorded" in model.source
    assert [p.name for p in model.rule_fsts] == ["number-zh.fst"]


def test_a_development_source_gets_the_strictest_label(tmp_path):
    r = rig(tmp_path, source="development-unlicensed")
    finish(r)
    assert list_voice_models(r.paths.voice_root)[0].usage == "Development only"


def test_training_text_is_the_digit_expanded_confirmed_lines_only(tmp_path):
    r = rig(tmp_path, texts=["我有三個蘋果", "二零二六年", "2026年有電話", "我有電話"])
    pending = r.store.add_line("voice", tone_wav(), ".wav", "還沒確認")
    r.store.set_review("voice", pending.id, "excluded")
    finish(r)
    (rows,) = r.trained
    assert len(rows) == 4
    assert [row["phoneme_ids"] for row in rows][2] == [17, 18, 17, 19, 20, 12, 21, 22]
    assert not any(ch.isdigit() for row in rows for ch in row["text"])


@pytest.mark.parametrize("with_nvrtc", [True, False])
def test_children_run_from_the_training_venv_with_the_gpu_visible(tmp_path, monkeypatch, with_nvrtc):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    monkeypatch.setenv("PYTHONPATH", "/main/venv/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/system/cuda/lib")
    r = rig(tmp_path)
    nvrtc = r.paths.training_python.parent.parent / "lib/python3.10/site-packages/nvidia/cuda_nvrtc/lib"
    if with_nvrtc:
        nvrtc.mkdir(parents=True)
        (nvrtc / "libnvrtc.so.12").touch()
    finish(r)
    train, export = r.spawner.commands
    assert train[0] == str(r.paths.training_python) and export[0] == str(r.paths.training_python)
    assert Path(train[1]).name == "train_matcha.py" and Path(export[1]).name == "export_matcha_onnx.py"
    assert argument(train, "--base-ckpt") == str(r.paths.base_checkpoint)
    assert argument(export, "--base-assets") == str(r.paths.base_assets)
    assert r.spawner.envs[0]["CUDA_VISIBLE_DEVICES"] == "0"  # inherited, not blanked
    assert "PYTHONPATH" not in r.spawner.envs[0]  # the main venv's packages must not leak in
    assert r.spawner.envs[0]["PYTHONNOUSERSITE"] == "1"
    library_path = f"{nvrtc}:/system/cuda/lib" if with_nvrtc else "/system/cuda/lib"
    assert [env["LD_LIBRARY_PATH"] for env in r.spawner.envs] == [library_path, library_path]
    assert all(cwd == r.paths.root for cwd in r.spawner.cwds)


def test_the_export_uses_the_lexicon_the_corpus_was_tokenised_with(tmp_path):
    r = rig(tmp_path)
    finish(r)
    assert argument(r.state["export_command"], "--lexicon").endswith("lexicon.txt")
    assert "export_command" in r.state


def test_the_bundle_is_checked_before_it_is_installed(tmp_path):
    r = rig(tmp_path)
    finish(r)
    (checked,) = r.state["verified"]
    assert set(REQUIRED_FILES) <= set(checked)
    assert list_voice_models(r.paths.voice_root)  # installed only after the check passed


def test_a_bundle_that_cannot_be_loaded_is_never_listed(tmp_path):
    r = rig(tmp_path, verify_error=jobs.JobFailed("匯出的聲線模型無法被 sherpa-onnx 載入"))
    snapshot = finish(r)
    assert snapshot["status"] == "failed" and "sherpa-onnx" in snapshot["error"]
    assert list_voice_models(r.paths.voice_root) == []
    assert not r.paths.voice_root.exists() or list(r.paths.voice_root.iterdir()) == []


def test_the_whisper_check_runs_with_the_configured_model_and_is_not_skipped(tmp_path):
    r = rig(tmp_path, settings=TrainingSettings(whisper_model="tiny"))
    finish(r)
    assert r.state["transcriber_models"] == ["tiny"]


def test_lines_whose_audio_does_not_match_the_text_are_excluded_and_logged(tmp_path):
    r = rig(tmp_path, transcript={"000001": "完全不一樣的內容啊啊啊"})  # line 1 is heard as something else
    snapshot = finish(r)
    assert snapshot["status"] == "done"
    (rows,) = r.trained
    assert len(rows) == 2
    reviews = {line.id: line.review for line in r.store.get("voice").lines}
    assert reviews["000001"] == "excluded" and reviews["000002"] == "confirmed"
    assert any("000001" in line for line in r.manager.read_log(0, 1000)["lines"])


def test_a_whisper_failure_fails_the_job_instead_of_skipping_the_check(tmp_path):
    r = rig(tmp_path, transcriber_error=TranscriberError("辨識程序意外結束"))
    snapshot = finish(r)
    assert snapshot["status"] == "failed" and "辨識程序意外結束" in snapshot["error"]
    assert [s["status"] for s in snapshot["stages"]][-2:] == ["pending", "pending"]
    assert r.spawner.commands == []  # nothing trained


def test_if_every_line_is_excluded_the_job_stops_before_training(tmp_path):
    r = rig(tmp_path, transcript={"000001": "不同", "000002": "不同", "000003": "不同"})
    snapshot = finish(r)
    assert snapshot["status"] == "failed" and "已確認" in snapshot["error"]
    assert r.spawner.commands == []


def test_the_corpus_is_checked_again_after_the_edge_synthesis(tmp_path):
    def leaves_a_pending_line(store, slug, sentences, **kwargs):
        store.add_line(slug, tone_wav(), ".wav", "還沒校對")
        return edge_teacher.SynthesisReport(1, 1, 1, 0, 0, 0, False, False, ())

    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=leaves_a_pending_line)
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    snapshot = finish(r, preset="quick-test", voice="zh-TW-HsiaoYuNeural")
    assert snapshot["status"] == "failed" and "待確認" in snapshot["error"]
    assert r.spawner.commands == []


def test_an_edge_corpus_is_synthesised_first_and_labelled_development_only(tmp_path):
    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=edge_synthesis())
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    snapshot = finish(r, preset="quick-test", voice="zh-TW-HsiaoYuNeural")
    assert snapshot["status"] == "done", snapshot["error"]
    assert [s["id"] for s in snapshot["stages"]] == ["environment", "synthesis", "quality", "training", "export"]
    assert list_voice_models(r.paths.voice_root)[0].usage == "Development only"


def test_edge_synthesis_gets_the_preset_the_voice_and_the_cancel_event(tmp_path):
    calls = []

    def recording(store, slug, sentences, **kwargs):
        calls.append((list(sentences), kwargs["voice"], kwargs["cancel"]))
        return edge_synthesis()(store, slug, sentences, **kwargs)

    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=recording)
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    finish(r, preset="quick-test", voice="zh-TW-YunJheNeural")
    sentences, voice, cancel = calls[0]
    assert len(sentences) > 100 and voice == "zh-TW-YunJheNeural" and isinstance(cancel, threading.Event)


def test_an_edge_text_list_replaces_the_preset(tmp_path):
    calls = []

    def recording(store, slug, sentences, **kwargs):
        calls.append(list(sentences))
        return edge_synthesis()(store, slug, sentences, **kwargs)

    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=recording)
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    finish(r, sentences="第一句\n第二句\n第一句\n")
    assert calls == [["第一句", "第二句"]]


@pytest.mark.parametrize(
    "extra",
    [{}, {"preset": "gigantic"}, {"preset": "quick-test", "voice": "en-US-JennyNeural"}, {"sentences": "\n\n"}],
)
def test_an_edge_job_needs_a_valid_preset_or_text_list_and_voice(tmp_path, extra):
    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[])
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    with pytest.raises(TrainingError) as caught:
        r.manager.start(request(**extra))
    assert caught.value.status == 400
    assert r.manager.status() is None


def test_a_text_list_with_unresolved_digits_is_refused_before_anything_is_synthesised(tmp_path):
    calls = []

    def recording(store, slug, sentences, **kwargs):
        calls.append(list(sentences))
        return edge_synthesis()(store, slug, sentences, **kwargs)

    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=recording)
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    with pytest.raises(TrainingError) as caught:
        r.manager.start(request(sentences="第一句\n價錢是$50\n\n溫度 25°C\n"))
    error = caught.value
    assert error.status == 409
    assert [(u["index"], u["text"], u["reason"]) for u in error.extra["unresolved"]] == [
        (2, "$50", "currency"),
        (3, "25°C", "degree"),
    ]
    assert "第 2 句" in error.message and "$50" in error.message and "第 3 句" in error.message
    assert calls == [] and r.manager.status() is None and r.spawner.commands == []
    assert r.store.get("voice").lines == ()


def test_a_preset_is_never_refused_for_digits(tmp_path):
    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=edge_synthesis())
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    assert finish(r, preset="standard")["status"] == "done"


def test_edge_synthesis_that_aborts_keeps_the_lines_and_fails_with_a_reason(tmp_path):
    def blocked(store, slug, sentences, **kwargs):
        line = store.add_line(slug, tone_wav(), ".wav", "已合成")
        store.set_review(slug, line.id, REVIEW_CONFIRMED)
        return edge_teacher.SynthesisReport(10, 1, 0, 0, 3, 0, False, True, ())

    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=blocked)
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    snapshot = finish(r, preset="quick-test")
    assert snapshot["status"] == "failed" and "Edge" in snapshot["error"] and "保留" in snapshot["error"]
    assert len(r.store.get("voice").lines) == 1


def test_a_training_failure_fails_the_job_and_writes_nothing(tmp_path):
    r = rig(tmp_path, train_code=1, train_lines=["Traceback: CUDA out of memory"])
    snapshot = finish(r)
    assert snapshot["status"] == "failed" and "結束碼 1" in snapshot["error"]
    assert snapshot["stages"][3]["status"] == "failed"
    assert list_voice_models(r.paths.voice_root) == []
    assert any("CUDA out of memory" in line for line in r.manager.read_log(0, 1000)["lines"])


def test_progress_and_metrics_come_from_the_training_output(tmp_path):
    release = threading.Event()
    r = rig(tmp_path, train_release=release, vram=VramReading(ENOUGH_VRAM_MIB))
    r.manager.start(request())
    wait_for(lambda: r.manager.status()["metrics"].get("step") == 4)
    training = next(s for s in r.manager.status()["stages"] if s["id"] == "training")
    assert training["status"] == "running" and training["detail"] == "步數 4/4，損失 5.5" and training["progress"] == 1.0
    assert 50 < r.manager.status()["progress"] < 100
    release.set()
    r.manager.join(20)
    snapshot = r.manager.status()
    assert snapshot["status"] == "done" and snapshot["metrics"]["training_seconds"] >= 0


def test_free_vram_during_training_is_sampled_for_calibration(tmp_path):
    release = threading.Event()
    readings = iter([VramReading(ENOUGH_VRAM_MIB)] + [VramReading(5000)] * 50)
    r = rig(tmp_path, train_release=release)
    r.manager._vram_probe = lambda: next(readings)
    r.manager.params = TrainingParams(batch_size=2, epochs=1, num_workers=0, vram_sample_seconds=0.01)
    r.manager.start(request())
    wait_for(lambda: r.manager.status()["metrics"].get("min_free_vram_mib") is not None)
    release.set()
    r.manager.join(20)
    assert r.manager.status()["metrics"]["min_free_vram_mib"] <= 5000


def test_only_one_job_at_a_time(tmp_path):
    release = threading.Event()
    r = rig(tmp_path, train_release=release)
    r.manager.start(request())
    wait_for(lambda: stage_status(r, "training") == "running")
    with pytest.raises(TrainingError) as caught:
        r.manager.start(request(name="另一個"))
    assert caught.value.status == 409
    assert check_of(caught.value.preflight, "other_job").status == "fail"
    release.set()
    r.manager.join(20)
    assert r.manager.status()["status"] == "done"
    assert r.manager.evaluate_preflight("voice", "再一個").can_start  # free again


# --------------------------------------------------------------------------- cancel


def test_cancel_stops_training_with_sigterm_and_keeps_the_corpus(tmp_path):
    r = rig(tmp_path, train_code=None)
    r.manager.start(request())
    wait_for(lambda: stage_status(r, "training") == "running" and r.spawner.processes)
    snapshot = r.manager.cancel()
    assert snapshot["status"] == "cancelling" and "取消" in snapshot["message"]
    r.manager.join(20)
    final = r.manager.status()
    assert final["status"] == "cancelled" and final["stages"][3]["status"] == "cancelled"
    assert r.spawner.processes[0].signals == ["TERM"]
    assert list_voice_models(r.paths.voice_root) == []
    assert len(r.store.get("voice").lines) == 3 and r.store.get("voice").counts.confirmed == 3
    workdir = r.paths.root.parent / "corpora" / "voice" / "jobs" / final["id"]
    assert [p.name for p in workdir.iterdir()] == ["log.txt"]  # training progress is not kept


def test_cancel_during_edge_synthesis_stops_without_training(tmp_path):
    started = threading.Event()

    def waits_for_cancel(store, slug, sentences, *, cancel, **kwargs):
        started.set()
        assert cancel.wait(10)
        return edge_teacher.SynthesisReport(len(sentences), 0, 0, 0, 0, 0, True, False, ())

    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=waits_for_cancel)
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    r.manager.start(request(preset="quick-test"))
    assert started.wait(10)
    r.manager.cancel()
    r.manager.join(20)
    assert r.manager.status()["status"] == "cancelled" and r.spawner.commands == []


def test_cancel_with_nothing_running_does_nothing(tmp_path):
    r = rig(tmp_path)
    assert r.manager.cancel() is None
    finish(r)
    assert r.manager.cancel() is None


# --------------------------------------------------------------------------- the log


def test_the_log_is_read_by_offset_and_kept_in_the_corpus_folder(tmp_path):
    r = rig(tmp_path)
    snapshot = finish(r)
    page = r.manager.read_log(0, 1000)
    assert page["job_id"] == snapshot["id"] and page["start"] == 0 and page["next"] == page["total"] == snapshot["log_lines"]
    assert any("step=4/4" in line for line in page["lines"])
    tail = r.manager.read_log(page["total"] - 2)
    assert tail["lines"] == page["lines"][-2:] and tail["next"] == page["total"]
    assert r.manager.read_log(page["total"])["lines"] == []
    log_file = tmp_path / "corpora" / "voice" / "jobs" / snapshot["id"] / "log.txt"
    assert log_file.read_text(encoding="utf-8").splitlines() == page["lines"]


def test_the_log_in_memory_is_bounded_but_numbered_absolutely(tmp_path):
    log = JobLog(tmp_path / "log.txt", capacity=3)
    for number in range(10):
        log.append(f"line {number}")
    page = log.read(0)
    assert page == {"start": 7, "lines": ["line 7", "line 8", "line 9"], "next": 10, "total": 10}
    assert log.read(8)["lines"] == ["line 8", "line 9"]
    assert log.read(99) == {"start": 10, "lines": [], "next": 10, "total": 10}
    log.close()
    assert len((tmp_path / "log.txt").read_text().splitlines()) == 10  # the file keeps everything


def test_without_a_job_the_log_is_empty(tmp_path):
    assert rig(tmp_path).manager.read_log() == {"job_id": None, "start": 0, "lines": [], "next": 0, "total": 0}


# --------------------------------------------------------------------------- restart


def test_a_job_that_was_running_when_the_server_stopped_is_marked_failed(tmp_path):
    release = threading.Event()
    first = rig(tmp_path, train_release=release)
    first.manager.start(request())
    wait_for(lambda: stage_status(first, "training") == "running")
    state_file = next((tmp_path / "corpora" / ".jobs").glob("job-*.json"))
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["status"] == "running" and saved["stage"] == "training"
    saved["pid"] = 4242
    state_file.write_text(json.dumps(saved), encoding="utf-8")
    release.set()
    first.manager.join(20)

    state_file.write_text(json.dumps({**saved, "status": "running", "finished_at": None}), encoding="utf-8")
    restarted = rig(tmp_path / "again")
    restarted.manager._jobs_dir = tmp_path / "corpora" / ".jobs"
    restarted.manager.recover()
    status = restarted.manager.status()
    assert status["status"] == "failed" and status["error"] == jobs.INTERRUPTED_MESSAGE
    assert status["stages"][3]["status"] == "failed" and status["finished_at"]
    assert restarted.state["orphans"] == [4242]
    assert json.loads(state_file.read_text(encoding="utf-8"))["status"] == "failed"
    assert restarted.manager.evaluate_preflight("voice", "x").checks[4].status == "pass"  # not "busy"


def test_finished_job_state_survives_a_restart_as_the_latest_status(tmp_path):
    r = rig(tmp_path)
    snapshot = finish(r)
    again = rig(tmp_path / "again")
    again.manager._jobs_dir = tmp_path / "corpora" / ".jobs"
    again.manager.recover()
    latest = again.manager.status()
    assert latest["id"] == snapshot["id"] and latest["status"] == "done"
    assert again.state["orphans"] == []


def test_after_a_restart_the_log_of_the_last_job_is_read_from_its_file(tmp_path):
    r = rig(tmp_path)
    snapshot = finish(r)
    expected = r.manager.read_log(0, 1000)["lines"]
    again = rig(tmp_path / "again")
    again.manager._jobs_dir = tmp_path / "corpora" / ".jobs"
    again.manager.store = r.store
    again.manager.recover()
    page = again.manager.read_log(2, 3)
    assert page["job_id"] == snapshot["id"] and page["lines"] == expected[2:5]
    assert page["start"] == 2 and page["next"] == 5 and page["total"] == len(expected)


def test_cancelling_during_the_bundle_check_installs_nothing(tmp_path):
    r = rig(tmp_path)

    def cancelling_check(bundle, cancel):
        r.manager.cancel()

    r.manager._verify_bundle = cancelling_check
    snapshot = finish(r)
    assert snapshot["status"] == "cancelled"
    assert list_voice_models(r.paths.voice_root) == []


def test_old_job_state_files_are_pruned(tmp_path):
    r = rig(tmp_path)
    jobs_dir = tmp_path / "corpora" / ".jobs"
    jobs_dir.mkdir(parents=True)
    for number in range(jobs.KEEP_JOB_FILES + 5):
        (jobs_dir / f"job-old-{number:02d}.json").write_text("{}", encoding="utf-8")
    finish(r)
    assert len(list(jobs_dir.glob("job-*.json"))) == jobs.KEEP_JOB_FILES


def test_an_orphan_is_only_signalled_when_its_command_line_names_the_training_tools(tmp_path):
    assert jobs.stop_orphan_training(2**30) is False  # no such process


# --------------------------------------------------------------------------- lifecycle: shutdown, startup, races


def running_rig(tmp_path, **kwargs) -> Rig:
    """A rig whose training child keeps running until it is signalled."""
    r = rig(tmp_path, train_code=None, **kwargs)
    r.manager.start(request())
    wait_for(lambda: stage_status(r, "training") == "running" and r.spawner.processes)
    return r


def test_shutdown_cancels_the_running_job_and_stops_its_child_so_the_gpu_is_freed(tmp_path):
    r = running_rig(tmp_path)

    r.manager.shutdown()

    assert r.manager.status()["status"] == "cancelled"
    assert r.spawner.processes[0].signals == ["TERM"]
    assert r.manager._thread is not None and not r.manager._thread.is_alive()


def test_shutdown_escalates_to_sigkill_for_a_child_that_ignores_sigterm(tmp_path):
    r = running_rig(tmp_path, train_ignores_term=True, settings=TrainingSettings(cancel_grace_seconds=0.05))

    r.manager.shutdown()

    assert r.spawner.processes[0].signals[:2] == ["TERM", "KILL"]
    assert r.manager.status()["status"] == "cancelled"


def test_shutdown_kills_the_child_directly_when_the_worker_cannot_finish_in_time(tmp_path):
    # A long grace period would keep the server waiting; after the limit the child is killed outright.
    r = running_rig(tmp_path, train_ignores_term=True, settings=TrainingSettings(cancel_grace_seconds=60))

    started = time.monotonic()
    r.manager.shutdown(timeout=0.3)

    assert time.monotonic() - started < 10
    assert "KILL" in r.spawner.processes[0].signals
    r.manager.join(20)
    assert r.manager.status()["status"] == "cancelled"


def test_shutdown_with_nothing_running_does_nothing(tmp_path):
    r = rig(tmp_path)
    r.manager.shutdown()
    finish(r)
    r.manager.shutdown()
    assert r.manager.status()["status"] == "done"


def test_shutdown_during_edge_synthesis_stops_it(tmp_path):
    started = threading.Event()

    def waits_for_cancel(store, slug, sentences, *, cancel, **kwargs):
        started.set()
        assert cancel.wait(10)
        return edge_teacher.SynthesisReport(len(sentences), 0, 0, 0, 0, 0, True, False, ())

    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=waits_for_cancel)
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    r.manager.start(request(preset="quick-test"))
    assert started.wait(10)

    r.manager.shutdown()

    assert r.manager.status()["status"] == "cancelled" and r.spawner.commands == []


def trained_commands(r: Rig) -> list[list[str]]:
    """Every child the job started except the Whisper worker."""
    return [command for command in r.spawner.commands if "whisper_worker" not in " ".join(command)]


def stuck_whisper(pid: int = 777) -> FakeProcess:
    """A Whisper child that is ready and then never answers."""
    return FakeProcess([json.dumps({"ready": True})], returncode=None, on_line=lambda _: [], pid=pid)


def test_the_whisper_child_pid_is_saved_in_the_job_state_and_cleared_afterwards(tmp_path):
    whisper = stuck_whisper(777)
    r = rig(tmp_path, whisper_process=whisper)
    r.manager.start(request())
    wait_for(lambda: whisper.written)  # the check is waiting for the first answer
    state_file = next((tmp_path / "corpora" / ".jobs").glob("job-*.json"))
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["stage"] == "quality" and saved["pid"] == 777

    r.manager.cancel()
    r.manager.join(20)

    assert json.loads(state_file.read_text(encoding="utf-8"))["pid"] is None


def test_cancel_kills_a_stuck_whisper_child_at_once(tmp_path):
    whisper = stuck_whisper()
    r = rig(tmp_path, whisper_process=whisper)
    r.manager.start(request())
    wait_for(lambda: whisper.written)

    started = time.monotonic()
    r.manager.cancel()
    r.manager.join(20)

    assert time.monotonic() - started < 10
    assert "KILL" in whisper.signals
    assert r.manager.status()["status"] == "cancelled"  # not "failed": the kill is the cancel's doing
    assert not trained_commands(r)  # training never started


def test_shutdown_kills_a_stuck_whisper_child(tmp_path):
    whisper = stuck_whisper()
    r = rig(tmp_path, whisper_process=whisper)
    r.manager.start(request())
    wait_for(lambda: whisper.written)

    r.manager.shutdown()

    assert "KILL" in whisper.signals and r.manager.status()["status"] == "cancelled"


def test_a_whisper_child_that_stops_answering_fails_the_job_with_the_reason(tmp_path):
    whisper = stuck_whisper()
    r = rig(tmp_path, whisper_process=whisper, settings=TrainingSettings(whisper_utterance_timeout_seconds=0.2))

    snapshot = finish(r)

    assert snapshot["status"] == "failed" and "逾時" in snapshot["error"]
    assert "KILL" in whisper.signals
    assert not trained_commands(r)  # no training on a corpus that was not checked


def test_recovery_runs_at_startup_not_on_the_first_request(tmp_path):
    jobs_dir = tmp_path / "corpora" / ".jobs"
    jobs_dir.mkdir(parents=True)
    saved = {"id": "job-old", "corpus": "voice", "status": "running", "stage": "training", "stages": [], "pid": 4242}
    (jobs_dir / "job-old.json").write_text(json.dumps(saved), encoding="utf-8")
    restarted = rig(tmp_path / "again")
    restarted.manager._jobs_dir = jobs_dir

    # Reading state must stay quick: nothing is stopped or rewritten until recover() runs.
    assert restarted.manager.status() is None
    restarted.manager.read_log()
    restarted.manager.evaluate_preflight("voice", "x")
    assert restarted.state["orphans"] == []
    assert json.loads((jobs_dir / "job-old.json").read_text(encoding="utf-8"))["status"] == "running"

    restarted.manager.recover()
    restarted.manager.recover()  # once is enough

    assert restarted.state["orphans"] == [4242]
    assert restarted.manager.status()["status"] == "failed"


def test_an_interrupted_job_that_was_cancelling_is_also_recovered(tmp_path):
    jobs_dir = tmp_path / "corpora" / ".jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "job-x.json").write_text(
        json.dumps({"id": "job-x", "corpus": "voice", "status": "cancelling", "stages": [], "pid": 99}), encoding="utf-8"
    )
    r = rig(tmp_path)
    r.manager._jobs_dir = jobs_dir

    r.manager.recover()

    assert r.state["orphans"] == [99] and r.manager.status()["status"] == "failed"


class FakeGroup:
    """A process group as ``stop_orphan_training`` sees it: signals in, liveness out."""

    def __init__(self, command: str, *, dies_on: str | None = "TERM") -> None:
        self.command = command
        self.alive = True
        self.sent: list[str] = []
        self._dies_on = dies_on
        self.now = 0.0

    def signal(self, pid: int, number) -> None:
        import signal as signal_module

        name = signal_module.Signals(number).name.removeprefix("SIG")
        self.sent.append(name)
        if name == self._dies_on:
            self.alive = False

    def exists(self, pid: int) -> bool:
        return self.alive

    def read_command(self, pid: int) -> str:
        return self.command

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def clock(self) -> float:
        return self.now


def stop(group: FakeGroup, **kwargs) -> bool:
    return jobs.stop_orphan_training(
        4242, signal_group=group.signal, group_exists=group.exists, read_command=group.read_command,
        sleep=group.sleep, clock=group.clock, **kwargs,
    )


def test_an_orphan_that_exits_on_sigterm_is_not_killed():
    group = FakeGroup("python tools/tts-distill/train_matcha.py", dies_on="TERM")
    assert stop(group) is True
    assert group.sent == ["TERM"]


def test_an_orphan_that_ignores_sigterm_is_killed_after_the_grace_period():
    group = FakeGroup("python tools/tts-distill/train_matcha.py", dies_on="KILL")
    assert stop(group, grace_seconds=2.0) is True
    assert group.sent == ["TERM", "KILL"]
    assert group.now >= 2.0  # it waited for the grace period before killing


def test_the_orphan_cleanup_waits_for_the_group_to_be_gone_but_not_for_ever():
    group = FakeGroup("python tools/tts-distill/train_matcha.py", dies_on=None)  # cannot be killed
    assert stop(group, grace_seconds=1.0, kill_wait_seconds=1.0) is True
    assert group.sent == ["TERM", "KILL"] and group.now < 30


def test_a_whisper_worker_left_behind_is_stopped_too():
    group = FakeGroup("/venv/bin/python -m src.tts.training.whisper_worker --model small", dies_on="TERM")
    assert stop(group) is True and group.sent == ["TERM"]


def test_a_reused_pid_of_an_unrelated_process_is_left_alone():
    group = FakeGroup("/usr/bin/firefox")
    assert stop(group) is False and group.sent == []


def test_cancel_does_not_overwrite_a_job_that_finished_meanwhile(tmp_path):
    r = rig(tmp_path)
    finish(r)
    job = r.manager._job
    assert job is not None

    class FinishesBeforeTheLock:
        """The worker ends the job in the gap between cancel's look at it and its lock."""

        def __init__(self) -> None:
            self._inner = threading.RLock()
            self._armed = True

        def __enter__(self):
            if self._armed:
                self._armed = False
                job.status = jobs.JOB_DONE
            self._inner.acquire()
            return self

        def __exit__(self, *exc):
            self._inner.release()

    job.status = jobs.JOB_RUNNING
    job.lock = FinishesBeforeTheLock()

    assert r.manager.cancel() is None
    assert job.status == jobs.JOB_DONE and not job.cancel.is_set()
    assert r.manager.evaluate_preflight("voice", "再一個").can_start  # not stuck on "another job running"


def test_start_does_not_hold_the_manager_lock_while_the_gpu_is_probed(tmp_path):
    probing, release = threading.Event(), threading.Event()
    r = rig(tmp_path)

    def slow_probe():
        probing.set()
        assert release.wait(20)
        return VramReading(ENOUGH_VRAM_MIB)

    r.manager._vram_probe = slow_probe
    starter = threading.Thread(target=lambda: r.manager.start(request()), daemon=True)
    starter.start()
    assert probing.wait(10)

    answered = threading.Event()

    def ask():
        r.manager.status()
        r.manager.cancel()
        r.manager.read_log()
        answered.set()

    threading.Thread(target=ask, daemon=True).start()
    try:
        assert answered.wait(2), "status/cancel blocked behind the nvidia-smi probe"
    finally:
        release.set()
        starter.join(20)
        r.manager.join(20)


def test_two_starts_at_the_same_time_run_one_job(tmp_path):
    barrier = threading.Barrier(2, timeout=10)
    release = threading.Event()
    r = rig(tmp_path, train_release=release)
    real_probe = r.manager._vram_probe

    def meeting_probe():
        barrier.wait()  # both starts have passed the other-job check before either creates a job
        return real_probe()

    r.manager._vram_probe = meeting_probe
    outcomes: list[str] = []

    def attempt(name):
        try:
            r.manager.start(request(name=name))
            outcomes.append("started")
        except TrainingError as exc:
            outcomes.append(f"refused {exc.status} {check_of(exc.preflight, 'other_job').status}")

    threads = [threading.Thread(target=attempt, args=(name,)) for name in ("甲", "乙")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    release.set()
    r.manager.join(20)
    assert sorted(outcomes) == ["refused 409 fail", "started"]


def test_an_automatic_transcription_in_progress_blocks_a_start_with_a_reason(tmp_path):
    r = rig(tmp_path)
    r.state["transcribing"] = True

    preflight = r.manager.evaluate_preflight("voice", "我的聲音")
    check = check_of(preflight, "transcription")

    assert check.status == "fail" and "逐字稿" in check.reason and not preflight.can_start
    with pytest.raises(TrainingError) as caught:
        r.manager.start(request())
    assert caught.value.status == 409 and check_of(caught.value.preflight, "transcription").status == "fail"
    assert r.manager.status() is None and r.spawner.commands == []


def test_without_a_transcription_the_check_passes_and_follows_the_other_job_check(tmp_path):
    r = rig(tmp_path)
    preflight = r.manager.evaluate_preflight("voice", "我的聲音")
    assert check_of(preflight, "transcription").status == "pass"
    ids = [c.id for c in preflight.checks]
    assert ids.index("transcription") == ids.index("other_job") + 1


# --------------------------------------------------------------------------- wiring and settings


def test_the_default_whisper_transcriber_is_a_cpu_child_with_the_configured_model(tmp_path):
    r = rig(tmp_path)
    manager = TrainingJobManager(store=r.store, paths=r.paths, spawn=r.spawner)
    transcriber = manager._transcriber_factory("small")
    assert type(transcriber).__name__ == "SubprocessTranscriber"
    assert transcriber._command[-2:] == ["--model", "small"] and transcriber._env["CUDA_VISIBLE_DEVICES"] == ""


def test_the_default_bundle_check_runs_sherpa_on_the_cpu_and_fails_the_job_when_it_cannot_load(tmp_path):
    def handler(command, env, cwd):
        assert command[1:3] == ["-m", "src.tts.training.verify_bundle"] and env["CUDA_VISIBLE_DEVICES"] == ""
        return FakeProcess(["RuntimeError: unexpected audio"], 1)

    r = rig(tmp_path)
    manager = TrainingJobManager(store=r.store, paths=r.paths, spawn=FakeSpawner(handler))
    with pytest.raises(jobs.JobFailed, match="unexpected audio"):
        manager._default_verify(tmp_path, threading.Event())
    ok = TrainingJobManager(store=r.store, paths=r.paths, spawn=FakeSpawner(lambda *_: FakeProcess(["OK 1.80"], 0)))
    ok._default_verify(tmp_path, threading.Event())


def test_default_paths_follow_the_setup_script_layout():
    paths = TrainingPaths.default()
    assert paths.training_python.parts[-5:] == (".local", "matcha-train", "venv", "bin", "python")
    assert paths.base_checkpoint.parts[-3:] == (".local", "matcha-base", "pytorch_model_sherpa.bin")
    assert paths.base_assets.parts[-3:] == ("models", "tts", "matcha-icefall-zh-en")
    assert (paths.tools_dir / "train_matcha.py").is_file() and (paths.tools_dir / "export_matcha_onnx.py").is_file()


def test_settings_come_from_the_matcha_section_of_the_configuration():
    assert jobs.settings_from_config(dict_to_config({})) == TrainingSettings(8.0, "small")
    configured = dict_to_config({"matcha": {"training_min_free_vram_gb": 6.5, "training_whisper_model": "base"}})
    assert jobs.settings_from_config(configured) == TrainingSettings(6.5, "base")
    assert jobs.settings_from_config(None) == TrainingSettings()


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ({"training_min_free_vram_gb": 0}, "training_min_free_vram_gb"),
        ({"training_min_free_vram_gb": -1}, "training_min_free_vram_gb"),
        ({"training_min_free_vram_gb": True}, "training_min_free_vram_gb"),
        ({"training_min_free_vram_gb": "8"}, "training_min_free_vram_gb"),
        ({"training_whisper_model": "gigantic"}, "training_whisper_model"),
    ],
)
def test_invalid_training_settings_are_refused_at_load(section, message):
    with pytest.raises(ValueError, match=message):
        dict_to_config({"matcha": section})
