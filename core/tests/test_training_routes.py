# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Training job routes: admin only, structured pre-flight reasons, no download of any kind.

The routes reach the TTS layer through ``state.tts``; here that is the layer's real
``InProcessVoiceTraining`` around a faked job manager, and a fake preview synthesizer.
The stage-connection half of the gate is the core's: tests connect stages by filling
``state.avatar_streams``.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from pathlib import Path

import pytest

from nova_contracts.tts import TrainingQuery, TtsEngineSettings, TtsError, VoiceModelPreview
from nova_core.server.access import ROUTE_ACCESS, Access
from nova_core.server.routes import tts_training
from nova_core.server.server import create_app
from nova_core.server.state import state
from nova_tts.training.jobs import TrainingJobManager
from nova_tts.training.service import InProcessVoiceTraining
from access_helpers import access_client, built_frontend, same_origin
from training_fakes import ENOUGH_VRAM_MIB, edge_synthesis, rig
from nova_tts.training.usage import SOURCE_EDGE_TEST_TEACHER
from nova_tts.training.edge_acknowledgement import MSA_CLAUSE, record_acknowledgement
from nova_tts.training.gpu_probe import VramReading

PREVIEW_SENTENCES = ("zh", "digits", "en")

BASE = "/api/tts/training"
PREVIEW = BASE + "/text-preview"
VOICE_PREVIEW = BASE + "/preview"
ROUTES = [
    ("GET", BASE),
    ("POST", BASE + "/start"),
    ("POST", BASE + "/cancel"),
    ("GET", BASE + "/log"),
    ("POST", PREVIEW),
    ("POST", VOICE_PREVIEW),
]


def async_test(function):
    """Run a coroutine test with ``asyncio.run`` (the suite has no pytest-asyncio)."""

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class TrainingService(InProcessVoiceTraining):
    """The TTS layer's training operations around ``manager``; previews go to ``previewer``."""

    def __init__(self, manager: TrainingJobManager, previewer=None) -> None:
        super().__init__(settings=TtsEngineSettings, corpus_store=manager.store, training_jobs=manager)
        self.previewer = previewer

    def preview_voice_model(self, request: VoiceModelPreview) -> bytes:
        return self.previewer(request.voice_id, request.sentence)


@pytest.fixture(autouse=True)
def no_stage(monkeypatch):
    """No stage is connected unless a test connects some (``connect_stages``)."""
    monkeypatch.setattr(state, "avatar_streams", {})
    monkeypatch.setattr(state, "tts", None, raising=False)


def connect_stages(count: int) -> None:
    state.avatar_streams.update({index: None for index in range(1, count + 1)})


def app_with(manager: TrainingJobManager, previewer=None):
    def factory(admin_env_path: Path):
        app = create_app(admin_env_path=admin_env_path, frontend_dir=built_frontend())
        state.tts = TrainingService(manager, previewer)
        return app

    return factory


async def wait_done(manager: TrainingJobManager) -> None:
    await asyncio.to_thread(manager.join, 20)


def test_every_training_route_is_admin_only():
    for route in ROUTES:
        assert ROUTE_ACCESS[route] is Access.ADMIN, route
    assert {key for key in ROUTE_ACCESS if key[1].startswith(BASE)} == set(ROUTES)


def test_no_route_downloads_or_exports_a_voice_model():
    app = create_app(admin_env_path=Path("/nonexistent/admin.env"), frontend_dir=built_frontend())
    routes = [(route.method, route.resource.canonical) for route in app.router.routes() if route.resource is not None]
    paths = {path for _, path in routes}
    assert not [p for p in paths if "export" in p or ("download" in p and "training" in p)]
    # A voice model can be removed (into the recycle bin) but never read back out.
    assert not [(m, p) for m, p in routes if "voice-models" in p and m != "DELETE"]
    assert not [p for p in paths if p.startswith(BASE) and p not in {r[1] for r in ROUTES}]


@async_test
async def test_status_lists_the_checks_with_reasons_and_no_job_yet(tmp_path):
    r = rig(tmp_path, vram=VramReading(6 * 1024))
    connect_stages(1)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.get(BASE, params={"corpus": "voice", "name": "我的聲音"})
        assert response.status == 200
        body = await response.json()
    data = body["data"]
    assert body["code"] == 0 and data["job"] is None
    assert data["preflight"]["can_start"] is False
    checks = {c["id"]: c for c in data["preflight"]["checks"]}
    assert checks["stage_connections"]["status"] == "fail" and checks["stage_connections"]["detail"] == {"count": 1}
    assert checks["free_vram"]["detail"] == {"free_gb": 6.0, "threshold_gb": 8.0}
    assert data["settings"] == {
        "min_free_vram_gb": 8.0,
        "whisper_model": "small",
        "edge_clause": {
            "reference": MSA_CLAUSE.reference,
            "effective": MSA_CLAUSE.effective,
            "text": MSA_CLAUSE.text,
        },
    }


@async_test
async def test_status_without_a_corpus_still_reports_the_global_checks(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        data = (await (await client.get(BASE)).json())["data"]
    ids = [c["id"] for c in data["preflight"]["checks"]]
    assert "free_vram" in ids and data["preflight"]["can_start"] is False


@async_test
async def test_a_refused_start_answers_409_with_the_structured_checks(tmp_path):
    r = rig(tmp_path)
    connect_stages(2)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": "voice", "name": "我的聲音"})
        body = await response.json()
    assert response.status == 409 and body["code"] == -1 and "舞台" in body["msg"]
    failed = [c["id"] for c in body["preflight"]["checks"] if c["status"] == "fail"]
    assert failed == ["stage_connections"]
    assert [c["id"] for c in body["preflight"]["checks"]][:3] == ["admin", "stage_connections", "free_vram"]
    assert r.spawner.commands == []


@async_test
async def test_a_layer_refusal_gets_the_core_checks_in_front(tmp_path):
    r = rig(tmp_path, vram=VramReading(1024))
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": "voice", "name": "我的聲音"})
        body = await response.json()
    assert response.status == 409 and "顯存" in body["msg"]
    checks = {c["id"]: c["status"] for c in body["preflight"]["checks"]}
    assert (checks["admin"], checks["stage_connections"], checks["free_vram"]) == ("pass", "pass", "fail")
    assert body["preflight"]["can_start"] is False


@async_test
async def test_a_stage_that_connects_while_the_layer_checks_cancels_the_new_job(tmp_path):
    r = rig(tmp_path, train_code=None)
    probe = r.manager._vram_probe

    def connect_while_checking():
        connect_stages(1)  # the slow pre-flight runs while a stage connects
        return probe()

    r.manager._vram_probe = connect_while_checking
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": "voice", "name": "我的聲音"})
        body = await response.json()
        await wait_done(r.manager)
    assert response.status == 409 and "舞台" in body["msg"]
    assert [c["id"] for c in body["preflight"]["checks"] if c["status"] == "fail"] == ["stage_connections"]
    assert r.manager.status()["status"] == "cancelled"


@async_test
async def test_start_runs_a_job_whose_state_and_log_the_routes_report(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": "voice", "name": "我的聲音"})
        started = (await response.json())["data"]
        assert response.status == 200 and started["status"] in ("running", "done") and started["corpus"] == "voice"
        await wait_done(r.manager)
        data = (await (await client.get(BASE)).json())["data"]
        assert data["job"]["status"] == "done" and data["job"]["voice_id"].startswith("trained-")
        log = (await (await client.get(BASE + "/log", params={"offset": 0})).json())["data"]
        assert log["job_id"] == data["job"]["id"] and log["start"] == 0 and any("step=4/4" in l for l in log["lines"])
        tail = (await (await client.get(BASE + "/log", params={"offset": log["next"]})).json())["data"]
        assert tail["lines"] == [] and tail["next"] == log["next"]


@pytest.mark.parametrize(
    "payload",
    [
        {}, {"corpus": "voice"}, {"name": "x"}, {"corpus": 5, "name": "x"}, {"corpus": "voice", "name": "x", "voice": 3},
        {"corpus": "voice", "name": "x", "preset": ["a"]}, {"corpus": "voice", "name": "x", "sentences": 1},
        [], "text",
    ],
)
@async_test
async def test_malformed_start_requests_are_400(tmp_path, payload):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", headers=same_origin(client), json=payload)
        assert response.status == 400 and (await response.json())["code"] == -1
    assert r.manager.status() is None


@async_test
async def test_text_preview_answers_each_sentence_with_its_spoken_form(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(PREVIEW, headers=same_origin(client), json={"sentences": "我有3個蘋果\n今天晴天\n"})
        body = await response.json()
    assert response.status == 200 and body["code"] == 0
    data = body["data"]
    assert data["ok"] is True and data["total"] == 2 and data["unresolved_count"] == 0
    assert data["sentences"] == [
        {"index": 1, "text": "我有3個蘋果", "spoken": "我有三個蘋果", "unresolved": []},
        {"index": 2, "text": "今天晴天", "spoken": "今天晴天", "unresolved": []},
    ]
    assert data["estimated_seconds"] == pytest.approx(round(data["estimated_seconds"], 1), abs=0.05)
    assert 1 < data["estimated_seconds"] < 10


@async_test
async def test_text_preview_marks_unresolved_fragments_and_is_not_ok(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(PREVIEW, headers=same_origin(client), json={"sentences": "你好\n價錢是$50"})
        data = (await response.json())["data"]
    assert response.status == 200 and data["ok"] is False and data["unresolved_count"] == 1
    assert data["sentences"][1]["unresolved"] == [{"text": "$50", "start": 3, "end": 6, "reason": "currency"}]
    assert data["sentences"][1]["spoken"] == "價錢是$50"


@async_test
async def test_text_preview_is_pure_and_needs_no_corpus_gpu_or_job(tmp_path):
    r = rig(tmp_path, vram=VramReading(0))
    connect_stages(3)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(PREVIEW, headers=same_origin(client), json={"sentences": "第一句\n$5"})
        assert response.status == 200
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    assert r.spawner.commands == [] and r.manager.status() is None


@pytest.mark.parametrize("payload", [{}, {"sentences": 5}, {"sentences": None}, [], "text"])
@async_test
async def test_malformed_text_preview_requests_are_400(tmp_path, payload):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(PREVIEW, headers=same_origin(client), json=payload)
        assert response.status == 400 and (await response.json())["code"] == -1


@async_test
async def test_text_preview_refuses_the_same_lists_as_start(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        empty = await client.post(PREVIEW, headers=same_origin(client), json={"sentences": "\n \n"})
        control = await client.post(PREVIEW, headers=same_origin(client), json={"sentences": "第一\x07句"})
        huge = await client.post(PREVIEW, headers=same_origin(client), json={"sentences": "字" * (1024 * 1024 + 1)})
        assert (empty.status, control.status, huge.status) == (400, 400, 413)
        for response in (empty, control, huge):
            assert (await response.json())["code"] == -1


@async_test
async def test_a_bad_json_body_to_text_preview_is_400(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(PREVIEW, data=b"{not json", headers={**same_origin(client), "Content-Type": "application/json"})
    assert response.status == 400


@async_test
async def test_start_answers_409_with_the_unresolved_fragments_of_an_edge_list(tmp_path):
    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[])
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    payload = {"corpus": "voice", "name": "我的聲音", "sentences": "第一句\n價錢是$50"}
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", headers=same_origin(client), json=payload)
        body = await response.json()
    assert response.status == 409 and body["code"] == -1 and "第 2 句" in body["msg"]
    assert body["unresolved"] == [{"index": 2, "text": "$50", "reason": "currency"}]
    assert r.manager.status() is None and r.spawner.commands == []


@async_test
async def test_a_list_the_preview_accepts_is_accepted_by_start(tmp_path):
    r = rig(tmp_path, source=SOURCE_EDGE_TEST_TEACHER, texts=[], synthesize=edge_synthesis())
    record_acknowledgement(r.store, "voice", MSA_CLAUSE.text)
    text = "我有3個蘋果\n2026年1月2日下雨"
    async with access_client(app_factory=app_with(r.manager)) as client:
        preview = (await (await client.post(PREVIEW, headers=same_origin(client), json={"sentences": text})).json())["data"]
        response = await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": "voice", "name": "我的聲音", "sentences": text})
        assert preview["ok"] is True and response.status == 200
        await wait_done(r.manager)


@async_test
async def test_a_corpus_field_is_an_id_never_a_path(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        for corpus in ("../../etc", "/etc/passwd", "voice/../voice"):
            response = await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": corpus, "name": "x"})
            body = await response.json()
            assert response.status in (400, 404, 409) and body["code"] == -1
    assert r.spawner.commands == []


@async_test
async def test_a_bad_json_body_is_400(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", data=b"{not json", headers={**same_origin(client), "Content-Type": "application/json"})
    assert response.status == 400


@async_test
async def test_cancel_stops_the_running_job(tmp_path):
    r = rig(tmp_path, train_code=None)
    async with access_client(app_factory=app_with(r.manager)) as client:
        assert (await client.post(BASE + "/cancel", headers=same_origin(client))).status == 200  # nothing running: harmless
        await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": "voice", "name": "我的聲音"})
        for _ in range(500):
            snapshot = (await (await client.get(BASE)).json())["data"]["job"]
            if snapshot["stage"] == "training" and r.spawner.processes:
                break
            await asyncio.sleep(0.01)
        body = await (await client.post(BASE + "/cancel", headers=same_origin(client))).json()
        assert body["data"]["status"] == "cancelling"
        await wait_done(r.manager)
        assert (await (await client.get(BASE)).json())["data"]["job"]["status"] == "cancelled"


@async_test
async def test_blocking_work_runs_off_the_event_loop(tmp_path):
    seen = []

    def slow_probe():
        seen.append(threading.current_thread() is threading.main_thread())
        return VramReading(ENOUGH_VRAM_MIB)

    r = rig(tmp_path)
    r.manager._vram_probe = slow_probe
    async with access_client(app_factory=app_with(r.manager)) as client:
        await client.get(BASE, params={"corpus": "voice", "name": "x"})
    assert seen == [False]


def test_the_layer_reads_its_settings_live(tmp_path):
    current = {"value": TtsEngineSettings(training_min_free_vram_gb=5)}
    training = InProcessVoiceTraining(settings=lambda: current["value"], corpus_store=rig(tmp_path).store)
    assert training.training_status(TrainingQuery()).settings.min_free_vram_gb == 5
    current["value"] = TtsEngineSettings(training_min_free_vram_gb=12, training_whisper_model="medium")
    settings = training.training_status(TrainingQuery()).settings
    assert (settings.min_free_vram_gb, settings.whisper_model) == (12, "medium")


# ------------------------------------------------------------------ preset voice preview (ticket 14)

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt fake audio"


class FakePreviewer:
    """Stands in for the synthesizer: records its calls, answers or raises what the test sets."""

    def __init__(self, result: bytes | Exception = WAV):
        self.result = result
        self.calls: list[tuple[object, object]] = []

    def __call__(self, voice_id, sentence):
        self.calls.append((voice_id, sentence))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@async_test
async def test_a_preset_sentence_is_answered_with_a_wav_that_is_not_a_download(tmp_path):
    previewer = FakePreviewer()
    async with access_client(app_factory=app_with(rig(tmp_path).manager, previewer)) as client:
        response = await client.post(VOICE_PREVIEW, headers=same_origin(client), json={"voice_id": "trained-1", "sentence": "digits"})
        body = await response.read()
    assert response.status == 200 and body == WAV
    assert response.headers["Content-Type"] == "audio/wav"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Disposition" not in response.headers
    assert previewer.calls == [("trained-1", "digits")]


@pytest.mark.parametrize("code", list(PREVIEW_SENTENCES))
@async_test
async def test_every_server_defined_code_reaches_the_synthesizer(tmp_path, code):
    previewer = FakePreviewer()
    async with access_client(app_factory=app_with(rig(tmp_path).manager, previewer)) as client:
        response = await client.post(VOICE_PREVIEW, headers=same_origin(client), json={"voice_id": "v", "sentence": code})
        assert response.status == 200
    assert previewer.calls == [("v", code)]


@pytest.mark.parametrize(
    "payload",
    [
        {}, {"voice_id": "v"}, {"sentence": "zh"}, {"voice_id": 5, "sentence": "zh"}, {"voice_id": "", "sentence": "zh"},
        {"voice_id": "v", "sentence": 3}, {"voice_id": "v", "sentence": "hello"}, {"voice_id": "v", "sentence": "ZH"},
        {"voice_id": "v", "sentence": "zh", "text": "any words at all"}, {"voice_id": "v", "sentence": "zh", "model": "x"},
        [], "zh", None,
    ],
)
@async_test
async def test_malformed_preview_requests_are_400_and_never_reach_the_synthesizer(tmp_path, payload):
    previewer = FakePreviewer()
    async with access_client(app_factory=app_with(rig(tmp_path).manager, previewer)) as client:
        response = await client.post(VOICE_PREVIEW, headers=same_origin(client), json=payload)
        assert response.status == 400 and (await response.json())["code"] == -1
    assert previewer.calls == []


@async_test
async def test_a_bad_json_body_to_preview_is_400(tmp_path):
    previewer = FakePreviewer()
    async with access_client(app_factory=app_with(rig(tmp_path).manager, previewer)) as client:
        response = await client.post(VOICE_PREVIEW, data=b"{no", headers={**same_origin(client), "Content-Type": "application/json"})
    assert response.status == 400 and previewer.calls == []


@pytest.mark.parametrize("status", [404, 500])
@async_test
async def test_a_refused_preview_keeps_the_reason_and_status_as_json(tmp_path, status):
    previewer = FakePreviewer(TtsError("聲線模型「v」不在 models/tts 清單中", status=status))
    async with access_client(app_factory=app_with(rig(tmp_path).manager, previewer)) as client:
        response = await client.post(VOICE_PREVIEW, headers=same_origin(client), json={"voice_id": "v", "sentence": "zh"})
        body = await response.json()
    assert response.status == status and body == {"code": -1, "msg": "聲線模型「v」不在 models/tts 清單中"}
    assert response.headers["Content-Type"].startswith("application/json")


@async_test
async def test_an_unexpected_synthesizer_failure_is_a_generic_500(tmp_path):
    previewer = FakePreviewer(RuntimeError("secret path /home/x"))
    async with access_client(app_factory=app_with(rig(tmp_path).manager, previewer)) as client:
        response = await client.post(VOICE_PREVIEW, headers=same_origin(client), json={"voice_id": "v", "sentence": "zh"})
        body = await response.json()
    assert response.status == 500 and body["code"] == -1 and "secret" not in body["msg"]


@async_test
async def test_a_slow_synthesis_does_not_block_the_event_loop(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def slow(voice_id, sentence):
        entered.set()
        assert release.wait(10)
        return WAV

    async with access_client(app_factory=app_with(rig(tmp_path).manager, slow)) as client:
        pending = asyncio.ensure_future(client.post(VOICE_PREVIEW, headers=same_origin(client), json={"voice_id": "v", "sentence": "zh"}))
        assert await asyncio.to_thread(entered.wait, 5)
        # The loop still serves other requests while the worker thread synthesises.
        other = await asyncio.wait_for(client.get(BASE), 2)
        assert other.status == 200
        assert not pending.done()
        release.set()
        assert (await pending).status == 200


@async_test
async def test_a_synthesis_past_the_time_limit_is_504(tmp_path, monkeypatch):
    # The layer stops its own synthesis at its deadline; the route does not wait past its own.
    monkeypatch.setattr(tts_training, "PREVIEW_TIMEOUT_SECONDS", 0.2)
    release = threading.Event()

    def stuck(voice_id, sentence):
        release.wait(10)
        return WAV

    async with access_client(app_factory=app_with(rig(tmp_path).manager, stuck)) as client:
        response = await client.post(VOICE_PREVIEW, headers=same_origin(client), json={"voice_id": "v", "sentence": "zh"})
        body = await response.json()
        release.set()
    assert response.status == 504 and body == {"code": -1, "msg": "試聽合成逾時，請稍後再試"}


# --------------------------------------------------------------------------- server lifecycle


def test_startup_recovers_interrupted_jobs_and_shutdown_stops_the_running_one(tmp_path):
    r = rig(tmp_path)
    calls: list[str] = []
    r.manager.recover = lambda: calls.append("recover")  # type: ignore[method-assign]
    r.manager.shutdown = lambda *a, **k: calls.append("shutdown")  # type: ignore[method-assign]
    training = TrainingService(r.manager)

    training._start_training()
    assert calls == ["recover"]
    training._stop_training()
    assert calls == ["recover", "shutdown"]


def test_a_job_running_at_shutdown_is_cancelled_and_its_child_stopped(tmp_path):
    from nova_tts.training.jobs import StartRequest

    r = rig(tmp_path, train_code=None)
    training = TrainingService(r.manager)
    r.manager.start(StartRequest(corpus="voice", name="我的聲音"))
    wait_until(lambda: r.spawner.processes)
    training._stop_training()
    assert r.spawner.processes[0].signals == ["TERM"]
    assert r.manager.status()["status"] == "cancelled"


def wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        time.sleep(0.01)


def test_the_layers_job_refuses_to_start_while_its_transcription_runs(tmp_path):
    from types import SimpleNamespace

    running = {"value": False}
    training = InProcessVoiceTraining(
        settings=TtsEngineSettings,
        corpus_store=rig(tmp_path).store,
        transcription=SimpleNamespace(running=lambda: running["value"]),  # type: ignore[arg-type]
    )
    manager = training._training_jobs

    assert manager._transcription_check().status == "pass"
    running["value"] = True
    assert manager._transcription_check().status == "fail"
