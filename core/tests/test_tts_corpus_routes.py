# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Console routes for training corpora: upload, transcripts, transcription, review.

The routes reach the TTS layer through ``state.tts``; here that is the layer's real
``InProcessVoiceTraining`` around a temporary store and a fake transcriber.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import io
import threading
import wave
from pathlib import Path

import aiohttp
import numpy as np
import pytest
import soundfile as sf
from aiohttp import web

from nova_contracts.tts import MAX_CORPUS_UPLOAD_BYTES as MAX_UPLOAD_BYTES
from nova_contracts.tts import TtsEngineSettings
from nova_core.server.access import ROUTE_ACCESS, Access, access_guard, install_access, route_key
from nova_core.server.state import state
from nova_tts.training.corpus import CorpusStore
from nova_tts.training.edge_acknowledgement import MSA_CLAUSE, read_acknowledgement
from nova_tts.training.gpu_guard import DeviceChoice
from nova_tts.training.gpu_probe import VramReading
from nova_tts.training.service import InProcessVoiceTraining
from nova_tts.training.transcription import TranscriptionJobs
from nova_core.server.routes.tts_corpus import ROUTES, register
from access_helpers import access_client, same_origin

BASE = "/api/tts/corpora"


class FakeTranscriber:
    def __init__(self, gate: threading.Event | None = None):
        self.gate = gate
        self.entered = threading.Event()
        self.closed = False

    def transcribe(self, path: Path) -> str:
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(10)
        return "測試文字"

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A store, its transcription jobs and the fake transcriber behind them; no stage connected."""
    store = CorpusStore(tmp_path / "training")
    fake = FakeTranscriber()
    jobs = TranscriptionJobs(store, lambda model, device: fake, lambda: DeviceChoice("cuda"))
    monkeypatch.setattr(state, "avatar_streams", {})
    monkeypatch.setattr(state, "tts", None, raising=False)
    return store, jobs, fake


def factory_for(store, jobs):
    def make(admin_env: Path) -> web.Application:
        app = web.Application(middlewares=[access_guard])
        install_access(app, admin_env, ())
        register(app)
        state.tts = InProcessVoiceTraining(settings=TtsEngineSettings, corpus_store=store, transcription=jobs)
        return app

    return make


def console(test):
    """Run an async test against a logged-in console client; ``client`` and ``env`` are injected."""
    names = list(inspect.signature(test).parameters)

    def wrapper(env, **fixtures):
        async def scenario():
            async with access_client(app_factory=factory_for(env[0], env[1])) as client:
                given = {"client": client, "env": env, **fixtures}
                await test(**{name: given[name] for name in names})

        asyncio.run(scenario())

    functools.update_wrapper(wrapper, test)
    del wrapper.__wrapped__
    wrapper.__signature__ = inspect.Signature(
        [inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD) for name in ["env", *[n for n in names if n not in ("client", "env")]]]
    )
    return wrapper


def tone(seconds: float = 2.0, rate: int = 16000, amplitude: float = 0.2) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    buffer = io.BytesIO()
    sf.write(buffer, (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32), rate, format="WAV")
    return buffer.getvalue()


def audio_form(data: bytes, filename: str = "take.wav", text: str | None = None, field: str = "audio") -> aiohttp.FormData:
    form = aiohttp.FormData(quote_fields=False)
    form.add_field(field, data, filename=filename, content_type="audio/wav")
    if text is not None:
        form.add_field("text", text)
    return form


async def post(client, path: str, headers: dict | None = None, **kwargs):
    return await client.post(path, headers={**same_origin(client), **(headers or {})}, **kwargs)


async def put(client, path: str, **kwargs):
    return await client.put(path, headers=same_origin(client), **kwargs)


async def create(client, slug: str = "mine", source: str = "self-recorded", consent: bool = True):
    response = await post(client, BASE, json={"slug": slug, "source": source, "consent": consent})
    assert response.status == 200, await response.text()
    return (await response.json())["data"]


async def upload(client, slug: str = "mine", name: str = "take.wav", text: str | None = None, seconds: float = 2.0):
    response = await post(client, f"{BASE}/{slug}/lines", data=audio_form(tone(seconds), name, text))
    assert response.status == 200, await response.text()
    return (await response.json())["data"]["line"]


# ------------------------------------------------------------------ access


def test_every_route_is_listed_as_admin_in_route_access():
    assert ROUTES
    for method, path in ROUTES:
        assert ROUTE_ACCESS[(method, path)] is Access.ADMIN, (method, path)


def test_the_registered_routes_are_exactly_the_declared_ones(env):
    app = web.Application()
    register(app)

    registered = {route_key(route) for route in app.router.routes()}

    assert registered == set(ROUTES)


# ------------------------------------------------------------------ corpus and source declaration


@console
async def test_creating_a_corpus_declares_its_source_and_label(client):
    data = await create(client, "mine", "written-authorization")

    assert data["slug"] == "mine" and data["source"] == "written-authorization"
    assert data["usage_label"] == "Research / Non-commercial"
    assert data["trainable"] is False and "no_confirmed_lines" in data["reasons"]
    assert data["counts"] == {"pending": 0, "confirmed": 0, "excluded": 0, "total": 0}


@console
async def test_development_recordings_are_development_only(client):
    data = await create(client, "dev", "development-unlicensed", consent=False)

    assert data["usage_label"] == "Development only"


@console
async def test_the_edge_test_teacher_corpus_needs_no_consent_and_is_development_only(client, env):
    response = await post(client, BASE, json={"slug": "edge-one", "source": "edge-test-teacher"})
    data = (await response.json())["data"]

    assert response.status == 200
    assert data["slug"] == "edge-one" and data["source"] == "edge-test-teacher"
    assert data["usage_label"] == "Development only"
    assert env[0].get("edge-one").source == "edge-test-teacher"


@console
async def test_an_edge_corpus_still_refuses_uploaded_recordings(client):
    await post(client, BASE, json={"slug": "edge-one", "source": "edge-test-teacher"})

    response = await post(client, f"{BASE}/edge-one/lines", data=audio_form(tone(2.0)))

    assert response.status == 409


@console
async def test_a_duplicate_slug_is_refused_for_an_edge_corpus_too(client):
    assert (await post(client, BASE, json={"slug": "edge-one", "source": "edge-test-teacher"})).status == 200

    assert (await post(client, BASE, json={"slug": "edge-one", "source": "edge-test-teacher"})).status == 409


@pytest.mark.parametrize(
    "body",
    [
        {"slug": "mine", "source": "self-recorded", "consent": False},
        {"slug": "mine", "source": "self-recorded"},
        {"slug": "mine", "source": "written-authorization", "consent": "yes"},
        {"slug": "mine", "source": "bogus", "consent": True},
        {"slug": "mine", "consent": True},
        {"slug": "../evil", "source": "self-recorded", "consent": True},
        {"slug": "a/b", "source": "self-recorded", "consent": True},
        {"slug": "", "source": "self-recorded", "consent": True},
    ],
)
@console
async def test_bad_declarations_create_nothing(client, env, body):
    response = await post(client, BASE, json=body)

    assert response.status == 400
    payload = await response.json()
    assert payload["code"] == -1 and payload["msg"]
    assert env[0].list() == []


@console
async def test_a_duplicate_corpus_conflicts_and_bad_json_is_a_400(client):
    await create(client)

    assert (await post(client, BASE, json={"slug": "mine", "source": "self-recorded", "consent": True})).status == 409
    assert (await post(client, BASE, data=b"not json", headers={"Content-Type": "application/json"})).status == 400
    assert (await post(client, BASE, json=[1, 2])).status == 400


@console
async def test_listing_corpora_summarises_each(client):
    await create(client, "b-voice")
    await create(client, "a-voice", "development-unlicensed", consent=False)
    await upload(client, "a-voice")

    response = await client.get(BASE)
    listed = (await response.json())["data"]["corpora"]

    assert [item["slug"] for item in listed] == ["a-voice", "b-voice"]
    assert listed[0]["counts"]["total"] == 1 and "lines" not in listed[0]


# ------------------------------------------------------------------ upload


@console
async def test_upload_converts_and_returns_the_new_pending_line(client, env):
    await create(client)

    response = await post(client, f"{BASE}/mine/lines", data=audio_form(tone(2.0, 44100), "My Take.wav", text="你好"))
    data = (await response.json())["data"]

    assert response.status == 200
    line = data["line"]
    assert (line["id"], line["original_name"], line["text"], line["review"]) == ("000001", "My Take.wav", "你好", "pending")
    assert line["audio_url"] == f"{BASE}/mine/lines/000001/audio"
    assert 1.9 < data["duration"] < 2.7
    with wave.open(str(env[0].audio_path("mine", "000001"))) as handle:
        assert (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) == (16000, 1, 2)


@console
async def test_upload_needs_a_declared_source_corpus(client, env):
    env[0].create("undeclared")
    env[0].create("edge", source="edge-test-teacher")

    for slug in ("undeclared", "edge"):
        response = await post(client, f"{BASE}/{slug}/lines", data=audio_form(tone()))
        assert response.status == 409


@pytest.mark.parametrize(
    ("data", "name", "status"),
    [
        (b"MZ not audio" * 50, "take.wav", 415),
        (b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40, "take.wav", 422),
        (tone(), "take.exe", 415),
        (tone(0.2), "take.wav", 422),
        (tone(20.0), "take.wav", 422),
    ],
)
@console
async def test_unusable_uploads_are_rejected_with_a_message(client, env, data, name, status):
    await create(client)

    response = await post(client, f"{BASE}/mine/lines", data=audio_form(data, name))

    assert response.status == status
    assert (await response.json())["msg"]
    assert env[0].get("mine").lines == ()


@console
async def test_an_oversized_upload_is_cut_off_with_413(client, env):
    await create(client)

    response = await post(client, f"{BASE}/mine/lines", data=audio_form(b"\x00" * (MAX_UPLOAD_BYTES + 4096)))

    assert response.status == 413
    assert env[0].get("mine").lines == ()


@console
async def test_upload_needs_exactly_the_audio_field_and_a_file(client):
    await create(client)

    assert (await post(client, f"{BASE}/mine/lines", data=audio_form(tone(), field="voice"))).status == 400
    empty = aiohttp.FormData()
    empty.add_field("text", "只有文字")
    assert (await post(client, f"{BASE}/mine/lines", data=empty)).status == 400
    assert (await post(client, f"{BASE}/mine/lines", data=b"plain body")).status == 400


@console
async def test_unknown_corpora_and_bad_slugs_are_404_or_400(client):
    assert (await post(client, f"{BASE}/nobody/lines", data=audio_form(tone()))).status == 404
    assert (await client.get(f"{BASE}/nobody")).status == 404
    assert (await client.get(f"{BASE}/..%2Fetc")).status in (400, 404)


# ------------------------------------------------------------------ transcripts


def transcripts_form(**files: bytes) -> aiohttp.FormData:
    form = aiohttp.FormData()
    for name, data in files.items():
        form.add_field("files", data, filename=name.replace("__", "."), content_type="text/plain")
    return form


@console
async def test_same_name_txt_files_fill_the_transcripts(client):
    await create(client)
    await upload(client, name="one.wav")
    await upload(client, name="two.wav")

    form = aiohttp.FormData()
    form.add_field("files", "第一句".encode(), filename="one.txt", content_type="text/plain")
    form.add_field("files", "第二句".encode(), filename="two.txt", content_type="text/plain")
    response = await post(client, f"{BASE}/mine/transcripts", data=form)
    data = (await response.json())["data"]

    assert response.status == 200
    assert data["applied"] == 2 and data["without_transcript"] == []
    lines = (await (await client.get(f"{BASE}/mine")).json())["data"]["lines"]
    assert [line["text"] for line in lines] == ["第一句", "第二句"]


@console
async def test_metadata_csv_fills_the_transcripts(client):
    await create(client)
    await upload(client, name="one.wav")
    await upload(client, name="two.wav")

    form = aiohttp.FormData()
    form.add_field("files", "filename|text\none.wav|甲\ntwo|乙\n".encode(), filename="metadata.csv", content_type="text/csv")
    response = await post(client, f"{BASE}/mine/transcripts", data=form)

    assert response.status == 200
    lines = (await (await client.get(f"{BASE}/mine")).json())["data"]["lines"]
    assert [line["text"] for line in lines] == ["甲", "乙"]


@console
async def test_transcript_problems_are_listed_and_nothing_is_applied(client):
    await create(client)
    await upload(client, name="one.wav")

    form = aiohttp.FormData()
    form.add_field("files", b"ok", filename="one.txt", content_type="text/plain")
    form.add_field("files", b"", filename="empty.txt", content_type="text/plain")
    form.add_field("files", "你好".encode("big5"), filename="big5.txt", content_type="text/plain")
    response = await post(client, f"{BASE}/mine/transcripts", data=form)
    payload = await response.json()

    assert response.status == 422
    assert any("empty.txt" in item for item in payload["problems"])
    assert any("big5.txt" in item and "UTF-8" in item for item in payload["problems"])
    assert (await (await client.get(f"{BASE}/mine")).json())["data"]["lines"][0]["text"] == ""


@console
async def test_a_transcript_naming_no_upload_is_reported_and_nothing_is_applied(client):
    await create(client)
    await upload(client, name="one.wav")

    form = aiohttp.FormData()
    form.add_field("files", b"ok", filename="one.txt", content_type="text/plain")
    form.add_field("files", b"x", filename="ghost.txt", content_type="text/plain")
    response = await post(client, f"{BASE}/mine/transcripts", data=form)
    payload = await response.json()

    assert response.status == 422
    assert any("ghost" in item for item in payload["problems"])
    assert (await (await client.get(f"{BASE}/mine")).json())["data"]["lines"][0]["text"] == ""


@pytest.mark.parametrize("filename", ["notes.docx", "metadata.csv.exe", "../metadata.csv"])
@console
async def test_only_txt_and_metadata_csv_are_accepted(client, filename):
    await create(client)
    form = aiohttp.FormData()
    form.add_field("files", b"x", filename=filename, content_type="text/plain")

    response = await post(client, f"{BASE}/mine/transcripts", data=form)

    assert response.status in (400, 422)
    assert (await response.json())["msg"]


@console
async def test_two_metadata_files_or_none_are_refused(client):
    await create(client)
    form = aiohttp.FormData()
    for _ in range(2):
        form.add_field("files", b"a.wav|x\n", filename="metadata.csv", content_type="text/csv")
    assert (await post(client, f"{BASE}/mine/transcripts", data=form)).status == 400
    assert (await post(client, f"{BASE}/mine/transcripts", data=aiohttp.FormData())).status == 400


# ------------------------------------------------------------------ review


@console
async def test_the_review_table_shows_state_and_digit_expanded_text(client):
    await create(client)
    await upload(client, name="a.wav", text="我有15個蘋果")
    await upload(client, name="b.wav", text="只花了$50")
    await upload(client, name="c.wav")

    data = (await (await client.get(f"{BASE}/mine")).json())["data"]
    first, second, third = data["lines"]

    assert first["text"] == "我有15個蘋果" and first["normalized_text"] == "我有十五個蘋果"
    assert first["unresolved"] == [] and first["review"] == "pending"
    assert second["normalized_text"] == "只花了$50"
    assert second["unresolved"] == [{"text": "$50", "start": 3, "end": 6, "reason": "currency"}]
    assert third["text"] == "" and third["normalized_text"] == ""
    assert data["counts"] == {"pending": 3, "confirmed": 0, "excluded": 0, "total": 3}
    assert data["trainable"] is False


@console
async def test_a_line_is_edited_confirmed_and_excluded_through_one_route(client):
    await create(client)
    await upload(client, text="舊稿")
    path = f"{BASE}/mine/lines/000001"

    confirmed = await (await put(client, path, json={"review": "confirmed"})).json()
    assert confirmed["data"]["line"]["review"] == "confirmed"
    assert confirmed["data"]["summary"]["trainable"] is True

    edited = await (await put(client, path, json={"text": "新稿 2026年"})).json()
    line = edited["data"]["line"]
    assert (line["text"], line["review"], line["normalized_text"]) == ("新稿 2026年", "pending", "新稿 二零二六年")
    assert edited["data"]["summary"]["trainable"] is False  # a changed transcript is reviewed again

    both = await (await put(client, path, json={"text": "最終稿", "review": "confirmed"})).json()
    assert (both["data"]["line"]["text"], both["data"]["line"]["review"]) == ("最終稿", "confirmed")

    excluded = await (await put(client, path, json={"review": "excluded"})).json()
    assert excluded["data"]["line"]["review"] == "excluded"
    assert excluded["data"]["summary"]["counts"]["excluded"] == 1


@pytest.mark.parametrize(
    "body",
    [{}, {"review": "maybe"}, {"text": 5}, {"text": "bad\x07"}, {"review": "confirmed", "path": "/etc/passwd"}, {"text": "字" * 501}],
)
@console
async def test_bad_review_bodies_are_400(client, body):
    await create(client)
    await upload(client, text="稿")

    response = await put(client, f"{BASE}/mine/lines/000001", json=body)

    assert response.status == 400
    assert (await response.json())["msg"]


@console
async def test_a_line_without_a_transcript_cannot_be_confirmed(client):
    await create(client)
    await upload(client)

    response = await put(client, f"{BASE}/mine/lines/000001", json={"review": "confirmed"})

    assert response.status == 400


@console
async def test_unknown_lines_are_404(client):
    await create(client)

    assert (await put(client, f"{BASE}/mine/lines/000009", json={"review": "excluded"})).status == 404
    assert (await put(client, f"{BASE}/mine/lines/abc", json={"review": "excluded"})).status == 404
    assert (await client.get(f"{BASE}/mine/lines/000009/audio")).status == 404


@console
async def test_bulk_confirm_confirms_pending_lines_with_text_and_reports_the_rest(client):
    await create(client)
    await upload(client, name="a.wav", text="一")
    await upload(client, name="b.wav", text="二")
    await upload(client, name="c.wav")
    await put(client, f"{BASE}/mine/lines/000002", json={"review": "excluded"})

    response = await post(client, f"{BASE}/mine/confirm")
    data = (await response.json())["data"]

    assert response.status == 200
    assert (data["confirmed"], data["without_text"]) == (1, 1)
    assert data["summary"]["counts"] == {"pending": 1, "confirmed": 1, "excluded": 1, "total": 3}
    assert data["summary"]["trainable"] is False  # one line still lacks a transcript


@console
async def test_a_corpus_is_trainable_only_after_everything_is_confirmed(client):
    await create(client)
    await upload(client, name="a.wav", text="一")
    await upload(client, name="b.wav", text="二")

    before = (await (await client.get(f"{BASE}/mine")).json())["data"]
    assert before["trainable"] is False and "pending_lines" in before["reasons"]

    response = await post(client, f"{BASE}/mine/confirm", json={"line_ids": ["000001"]})
    assert (await response.json())["data"]["confirmed"] == 1
    assert (await (await client.get(f"{BASE}/mine")).json())["data"]["trainable"] is False

    await post(client, f"{BASE}/mine/confirm")
    after = (await (await client.get(f"{BASE}/mine")).json())["data"]
    assert after["trainable"] is True and after["reasons"] == []


@console
async def test_bulk_confirm_rejects_bad_line_ids(client):
    await create(client)
    await upload(client, text="稿")

    assert (await post(client, f"{BASE}/mine/confirm", json={"line_ids": ["../x"]})).status == 404
    assert (await post(client, f"{BASE}/mine/confirm", json={"line_ids": "000001"})).status == 400


@console
async def test_a_line_plays_back_as_audio_for_review(client):
    await create(client)
    await upload(client)

    response = await client.get(f"{BASE}/mine/lines/000001/audio")
    body = await response.read()

    assert response.status == 200
    assert response.content_type == "audio/wav"
    assert response.headers["Cache-Control"] == "no-store"
    assert body[:4] == b"RIFF"


@console
async def test_edge_teacher_audio_is_neither_played_back_nor_taken_out(client, env):
    """Spec decision 13 and ADR 0026: Edge output has no playback route; uploads keep theirs."""
    store = env[0]
    store.create("edge-one", source="edge-test-teacher")
    line = store.add_line("edge-one", tone(), ".wav", text="你好")

    response = await client.get(f"{BASE}/edge-one/lines/{line.id}/audio")
    payload = await response.json()

    assert response.status == 403
    assert payload["code"] == -1
    assert "Edge" in payload["msg"] and any("\u4e00" <= ch <= "\u9fff" for ch in payload["msg"])
    assert b"RIFF" not in await response.read()


@console
async def test_an_unknown_corpus_or_line_is_still_404_for_the_audio_route(client):
    await create(client)

    assert (await client.get(f"{BASE}/nobody/lines/000001/audio")).status == 404
    assert (await client.get(f"{BASE}/mine/lines/000009/audio")).status == 404


# ------------------------------------------------------------------ automatic transcription


@console
async def test_transcription_runs_in_the_background_and_reports_progress(client, env):
    store, jobs, fake = env
    await create(client)
    await upload(client, name="a.wav")
    await upload(client, name="b.wav")

    response = await post(client, f"{BASE}/mine/transcription", json={})
    started = (await response.json())["data"]
    assert response.status == 202 and started["state"] == "running" and started["total"] == 2
    assert await _wait_idle(jobs)

    status = (await (await client.get(f"{BASE}/mine/transcription")).json())["data"]
    assert (status["state"], status["done"], status["total"], status["failed"]) == ("done", 2, 2, [])
    lines = (await (await client.get(f"{BASE}/mine")).json())["data"]["lines"]
    assert [line["text"] for line in lines] == ["測試文字", "測試文字"]
    assert all(line["review"] == "pending" for line in lines)
    assert fake.closed


@console
async def test_the_start_and_status_responses_name_the_device_and_why_it_is_the_cpu(client, env):
    store, jobs, _ = env
    jobs.choose_device = lambda: DeviceChoice("cpu", "有舞台連線")
    await create(client)
    await upload(client, name="a.wav")

    started = (await (await post(client, f"{BASE}/mine/transcription", json={})).json())["data"]
    assert (started["device"], started["fallback_reason"]) == ("cpu", "有舞台連線")
    assert await _wait_idle(jobs)

    status = (await (await client.get(f"{BASE}/mine/transcription")).json())["data"]
    assert (status["state"], status["device"], status["fallback_reason"]) == ("done", "cpu", "有舞台連線")


@console
async def test_a_connected_stage_keeps_the_transcription_on_the_cpu(client, env):
    store, jobs, _ = env
    jobs.choose_device = lambda: DeviceChoice("cuda")  # the layer alone would pick the GPU
    await create(client)
    await upload(client, name="a.wav")
    state.avatar_streams[1] = None

    started = (await (await post(client, f"{BASE}/mine/transcription", json={})).json())["data"]

    assert (started["device"], started["fallback_reason"]) == ("cpu", "有舞台連線")
    assert await _wait_idle(jobs)


def test_the_layers_device_choice_uses_the_training_threshold_from_its_settings(tmp_path):
    free_10_gb = lambda: VramReading(10 * 1024)  # noqa: E731
    current = {"value": TtsEngineSettings(training_min_free_vram_gb=8)}
    training = InProcessVoiceTraining(
        settings=lambda: current["value"], corpus_store=CorpusStore(tmp_path), vram_probe=free_10_gb,
        cuda_available=lambda: True,
    )
    assert training._gpu_choice() == DeviceChoice("cuda")
    current["value"] = TtsEngineSettings(training_min_free_vram_gb=12)
    assert training._gpu_choice() == DeviceChoice("cpu", "剩餘顯存不足")


async def _wait_idle(jobs) -> bool:
    return await asyncio.to_thread(jobs.wait, 10)


@console
async def test_transcription_can_be_cancelled_and_status_is_per_corpus(client, env):
    store, jobs, fake = env
    fake.gate = threading.Event()
    await create(client)
    await create(client, "other")
    await upload(client, name="a.wav")
    await upload(client, name="b.wav")

    await post(client, f"{BASE}/mine/transcription", json={"model": "small"})
    assert await asyncio.to_thread(fake.entered.wait, 10)
    assert (await post(client, f"{BASE}/mine/transcription", json={})).status == 409
    other = (await (await client.get(f"{BASE}/other/transcription")).json())["data"]
    assert other["state"] == "idle"

    cancelled = await client.delete(f"{BASE}/mine/transcription", headers=same_origin(client))
    assert cancelled.status == 200
    assert (await cancelled.json())["data"]["cancel_requested"] is True
    fake.gate.set()
    assert await _wait_idle(jobs)

    status = (await (await client.get(f"{BASE}/mine/transcription")).json())["data"]
    assert status["state"] == "cancelled" and status["done"] == 1
    assert fake.closed


@console
async def test_cancelling_without_a_job_conflicts_and_bad_requests_are_400(client):
    await create(client)
    await upload(client)

    assert (await client.delete(f"{BASE}/mine/transcription", headers=same_origin(client))).status == 409
    assert (await post(client, f"{BASE}/mine/transcription", json={"model": "/home/me/model"})).status == 400
    assert (await post(client, f"{BASE}/mine/transcription", json={"line_ids": "all"})).status == 400
    assert (await post(client, f"{BASE}/mine/transcription", json={"model": 5})).status == 400
    assert (await post(client, f"{BASE}/mine/transcription", json={"line_ids": ["000099"]})).status == 404


@console
async def test_transcription_with_nothing_to_do_conflicts(client):
    await create(client)
    await upload(client, text="已有稿")

    assert (await post(client, f"{BASE}/mine/transcription", json={})).status == 409


# ------------------------------------------------------------------ the event loop

@console
async def test_handlers_do_the_heavy_work_off_the_event_loop(client, monkeypatch):
    """Decoding and QC run in a worker thread, never on the server's event loop."""
    from nova_tts.training import ingest

    main = threading.get_ident()
    seen: list[int] = []
    real = ingest.ingest_audio

    def spy(*args, **kwargs):
        seen.append(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr("nova_tts.training.service.ingest_audio", spy)
    await create(client)
    await upload(client)

    assert seen and main not in seen


# ------------------------------------------------------------------ Edge clause acknowledgement


async def create_edge(client, slug: str = "edge-one"):
    response = await post(client, BASE, json={"slug": slug, "source": "edge-test-teacher"})
    assert response.status == 200, await response.text()


def confirmed_body() -> dict:
    return {"shown_text": MSA_CLAUSE.text, "confirmed": True}


@pytest.mark.parametrize("confirmed", [False, None, "true", 1, "yes", [True]])
@console
async def test_the_exact_text_alone_is_not_a_confirmation(client, env, confirmed):
    await create_edge(client)

    response = await post(client, f"{BASE}/edge-one/acknowledgement", json={"shown_text": MSA_CLAUSE.text, "confirmed": confirmed})

    assert response.status == 400
    assert (await response.json())["code"] == -1
    assert read_acknowledgement(env[0], "edge-one") is None


@console
async def test_a_body_without_the_confirmed_flag_records_nothing(client, env):
    await create_edge(client)

    response = await post(client, f"{BASE}/edge-one/acknowledgement", json={"shown_text": MSA_CLAUSE.text})

    assert response.status == 400
    assert read_acknowledgement(env[0], "edge-one") is None


@console
async def test_acknowledging_the_clause_records_it_and_returns_when_and_where_from(client, env):
    await create_edge(client)

    response = await post(client, f"{BASE}/edge-one/acknowledgement", json=confirmed_body())
    data = (await response.json())["data"]

    assert response.status == 200
    assert data["clause_reference"] == MSA_CLAUSE.reference
    assert data["clause_effective"] == MSA_CLAUSE.effective
    record = read_acknowledgement(env[0], "edge-one")
    assert record is not None and data["acknowledged_at"] == record.acknowledged_at
    assert record.clause_text == MSA_CLAUSE.text


@pytest.mark.parametrize("shown", ["You may not use the AI services", MSA_CLAUSE.text + " ", None, 7])
@console
async def test_a_text_that_is_not_the_servers_clause_records_nothing(client, env, shown):
    await create_edge(client)

    response = await post(client, f"{BASE}/edge-one/acknowledgement", json={"shown_text": shown, "confirmed": True})

    assert response.status == 400
    assert (await response.json())["code"] == -1
    assert read_acknowledgement(env[0], "edge-one") is None


@console
async def test_a_missing_shown_text_records_nothing(client, env):
    await create_edge(client)

    assert (await post(client, f"{BASE}/edge-one/acknowledgement", json={})).status == 400
    assert read_acknowledgement(env[0], "edge-one") is None


@console
async def test_only_an_edge_corpus_can_be_acknowledged(client, env):
    await create(client, "mine", "self-recorded")

    response = await post(client, f"{BASE}/mine/acknowledgement", json=confirmed_body())

    assert response.status == 409
    assert (await post(client, f"{BASE}/nobody/acknowledgement", json=confirmed_body())).status == 404


@console
async def test_review_payloads_are_built_off_the_event_loop(client, env, monkeypatch):
    from nova_tts.training import service

    main = threading.get_ident()
    seen: dict[str, set[int]] = {}

    def spy(name):
        real = getattr(service, name)

        def wrapper(*args, **kwargs):
            seen.setdefault(name, set()).add(threading.get_ident())
            return real(*args, **kwargs)

        monkeypatch.setattr(service, name, wrapper)

    for name in ("_summary_fields", "_line"):
        spy(name)
    await create(client)
    await upload(client, text="稿")
    steps = {
        "list": lambda: client.get(BASE),
        "detail": lambda: client.get(f"{BASE}/mine"),
        "edit": lambda: put(client, f"{BASE}/mine/lines/000001", json={"text": "新稿"}),
        "confirm": lambda: post(client, f"{BASE}/mine/confirm", json={}),
    }
    for label, step in steps.items():
        seen.clear()
        assert (await step()).status == 200, label
        assert seen, label
        assert main not in set().union(*seen.values()), f"{label} built its payload on the event loop"


@console
async def test_transcript_files_are_parsed_off_the_event_loop(client, monkeypatch):
    from nova_tts.training import service

    main = threading.get_ident()
    seen: list[int] = []
    for name in ("parse_txt", "parse_metadata_csv"):
        real = getattr(service, name)

        def wrapper(*args, _real=real, **kwargs):
            seen.append(threading.get_ident())
            return _real(*args, **kwargs)

        monkeypatch.setattr(service, name, wrapper)
    await create(client)
    await upload(client, name="take.wav")
    await upload(client, name="other.wav")
    form = aiohttp.FormData(quote_fields=False)
    form.add_field("files", "我說了話".encode(), filename="take.txt", content_type="text/plain")
    form.add_field("files", "filename|text\nother.wav|另一句\n".encode(), filename="metadata.csv", content_type="text/csv")

    response = await post(client, f"{BASE}/mine/transcripts", data=form)

    assert response.status == 200, await response.text()
    assert len(seen) == 2 and main not in seen


# ------------------------------------------------------------------ deletion


@console
async def test_a_corpus_is_deleted_into_the_recycle_bin(client, env):
    store, _, _ = env
    await create(client)
    await upload(client)
    await create(client, "other")

    response = await client.delete(f"{BASE}/mine", headers=same_origin(client))

    assert response.status == 200, await response.text()
    assert (await response.json())["data"] == {"slug": "mine"}
    assert (await client.get(f"{BASE}/mine")).status == 404
    listed = (await (await client.get(BASE)).json())["data"]["corpora"]
    assert [corpus["slug"] for corpus in listed] == ["other"]
    [recycled] = list((store.root / ".deleted").iterdir())
    assert recycled.name.startswith("mine-") and (recycled / "corpus.json").is_file()


@console
async def test_deleting_an_unknown_corpus_is_404_and_a_bad_slug_is_refused(client):
    assert (await client.delete(f"{BASE}/missing", headers=same_origin(client))).status == 404
    assert (await client.delete(f"{BASE}/bad..slug%2F", headers=same_origin(client))).status in {400, 404}


@console
async def test_a_corpus_being_transcribed_cannot_be_deleted(client, env):
    store, jobs, fake = env
    fake.gate = threading.Event()
    await create(client)
    await upload(client, name="a.wav")
    await post(client, f"{BASE}/mine/transcription", json={"model": "small"})
    assert await asyncio.to_thread(fake.entered.wait, 10)

    refused = await client.delete(f"{BASE}/mine", headers=same_origin(client))

    assert refused.status == 409
    assert "自動轉寫" in (await refused.json())["msg"]
    fake.gate.set()
    assert await _wait_idle(jobs)
    assert (await client.delete(f"{BASE}/mine", headers=same_origin(client))).status == 200


@console
async def test_a_corpus_in_a_running_training_job_cannot_be_deleted(client, monkeypatch):
    await create(client)
    await create(client, "other")
    job = {"corpus": "mine", "voice_id": "trained-x", "status": "running"}
    monkeypatch.setattr(state.tts._training_jobs, "status", lambda: job)

    refused = await client.delete(f"{BASE}/mine", headers=same_origin(client))

    assert refused.status == 409
    assert "訓練中" in (await refused.json())["msg"]
    # Another corpus is free, and so is this one once the job has settled.
    assert (await client.delete(f"{BASE}/other", headers=same_origin(client))).status == 200
    job["status"] = "done"
    assert (await client.delete(f"{BASE}/mine", headers=same_origin(client))).status == 200
