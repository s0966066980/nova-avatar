# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Training job routes: admin only, structured pre-flight reasons, no download of any kind."""

from __future__ import annotations

import asyncio
import functools
import threading
from pathlib import Path

import pytest

from src.server.access import ROUTE_ACCESS, Access
from src.server.routes import tts_training
from src.server.server import create_app
from src.server.tts_training_jobs import TrainingJobManager, TrainingParams
from tests.access_helpers import LAN_ADDRESS, access_client, built_frontend, same_origin
from tests.test_training_jobs import ENOUGH_VRAM_MIB, edge_synthesis, rig
from src.tts.training.usage import SOURCE_EDGE_TEST_TEACHER
from src.tts.training.edge_acknowledgement import MSA_CLAUSE, record_acknowledgement
from src.tts.training.gpu_probe import VramReading

BASE = "/api/tts/training"
PREVIEW = BASE + "/text-preview"
ROUTES = [
    ("GET", BASE),
    ("POST", BASE + "/start"),
    ("POST", BASE + "/cancel"),
    ("GET", BASE + "/log"),
    ("POST", PREVIEW),
]


def async_test(function):
    """Run a coroutine test with ``asyncio.run`` (the suite has no pytest-asyncio)."""

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def app_with(manager: TrainingJobManager):
    def factory(admin_env_path: Path):
        app = create_app(admin_env_path=admin_env_path, frontend_dir=built_frontend())
        app[tts_training.MANAGER_KEY] = manager
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
    paths = {route.resource.canonical for route in app.router.routes() if route.resource is not None}
    assert not [p for p in paths if "export" in p or "voice-models" in p or ("download" in p and "training" in p)]
    assert not [p for p in paths if p.startswith(BASE) and p not in {r[1] for r in ROUTES}]


@async_test
async def test_status_lists_the_checks_with_reasons_and_no_job_yet(tmp_path):
    r = rig(tmp_path, sessions=1, vram=VramReading(6 * 1024))
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
    assert data["settings"] == {"min_free_vram_gb": 8.0, "whisper_model": "small"}


@async_test
async def test_status_without_a_corpus_still_reports_the_global_checks(tmp_path):
    r = rig(tmp_path)
    async with access_client(app_factory=app_with(r.manager)) as client:
        data = (await (await client.get(BASE)).json())["data"]
    ids = [c["id"] for c in data["preflight"]["checks"]]
    assert "free_vram" in ids and data["preflight"]["can_start"] is False


@async_test
async def test_a_refused_start_answers_409_with_the_structured_checks(tmp_path):
    r = rig(tmp_path, sessions=2)
    async with access_client(app_factory=app_with(r.manager)) as client:
        response = await client.post(BASE + "/start", headers=same_origin(client), json={"corpus": "voice", "name": "我的聲音"})
        body = await response.json()
    assert response.status == 409 and body["code"] == -1 and "舞台" in body["msg"]
    failed = [c["id"] for c in body["preflight"]["checks"] if c["status"] == "fail"]
    assert failed == ["stage_connections"]
    assert r.spawner.commands == []


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
    r = rig(tmp_path, sessions=3, vram=VramReading(0))
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


@async_test
async def test_the_routes_refuse_anonymous_and_lan_clients(tmp_path):
    r = rig(tmp_path)
    async with access_client(admin=False, app_factory=app_with(r.manager)) as client:
        for method, path in ROUTES:
            response = await client.request(method, path)
            assert response.status == 401, (method, path)
    async with access_client(admin=False, remote=LAN_ADDRESS, app_factory=app_with(r.manager)) as client:
        assert (await client.get(BASE)).status == 401
    assert r.spawner.commands == []


def test_the_default_manager_reads_the_live_configuration(tmp_path, monkeypatch):
    from src.config.loader import dict_to_config
    from src.server.state import state

    monkeypatch.setattr(state, "config", dict_to_config({"matcha": {"training_min_free_vram_gb": 5}}))
    manager = tts_training.build_manager()
    assert manager.settings().min_free_vram_gb == 5
    monkeypatch.setattr(state, "config", dict_to_config({"matcha": {"training_min_free_vram_gb": 12}}))
    assert manager.settings().min_free_vram_gb == 12
    assert isinstance(manager.params, TrainingParams)
