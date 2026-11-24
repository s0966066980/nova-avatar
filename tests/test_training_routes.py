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
from tests.test_training_jobs import ENOUGH_VRAM_MIB, rig
from src.tts.training.gpu_probe import VramReading

BASE = "/api/tts/training"
ROUTES = [("GET", BASE), ("POST", BASE + "/start"), ("POST", BASE + "/cancel"), ("GET", BASE + "/log")]


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
