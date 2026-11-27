# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Avatar import: safe overwrite, bounded uploads and job bookkeeping."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import pytest

from nova_render.builder import BuildError, build_character
from nova_render.catalog import list_archived_avatars, list_avatar_characters
from nova_core.config.schema import Config
from nova_render.adapter import create_avatar_service
from nova_core.server import import_jobs
from nova_core.server.routes import settings as settings_routes
from nova_core.server.state import state
from access_helpers import access_client, same_origin

OLD_MARKER = b"old-avatar-frame"


@pytest.fixture(autouse=True)
def avatar_service(monkeypatch):
    monkeypatch.setattr(state, "avatar_service", create_avatar_service())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("nova_render.catalog.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nova_render.builder.get_data_dir", lambda: tmp_path)
    return tmp_path


def make_musetalk_avatar(root: Path, avatar_id: str) -> Path:
    avatar = root / "avatars" / avatar_id
    (avatar / "mask").mkdir(parents=True)
    (avatar / "full_imgs").mkdir()
    (avatar / "full_imgs" / "00000000.png").write_bytes(OLD_MARKER)
    (avatar / "latents.pt").write_bytes(b"latents")
    return avatar


def fake_video(root: Path) -> Path:
    video = root / "clip.mp4"
    video.write_bytes(b"not-a-real-video")
    return video


def fake_musetalk_build(work_dir, avatar_id, source_name, report, options, **_kwargs):
    (work_dir / "mask").mkdir(parents=True, exist_ok=True)
    (work_dir / "latents.pt").write_bytes(b"new-latents")


def remaining_build_dirs(root: Path) -> list[str]:
    return [child.name for child in (root / "avatars").iterdir() if child.name.startswith(".building")]


# ---------------------------------------------------------------- builder


def test_overwrite_refused_when_guard_reports_avatar_in_use(data_dir):
    old = make_musetalk_avatar(data_dir, "musetalk_host")
    with patch("nova_render.builder.extract_frames", return_value=1), \
         patch("nova_render.builder._build_musetalk", side_effect=fake_musetalk_build) as build:
        with pytest.raises(BuildError, match="使用"):
            build_character(
                "musetalk", fake_video(data_dir), "musetalk_host", overwrite=True,
                replace_guard=lambda avatar_id: "正在使用的數字人無法覆寫",
            )
    build.assert_not_called()
    assert (old / "full_imgs" / "00000000.png").read_bytes() == OLD_MARKER
    assert remaining_build_dirs(data_dir) == []


def test_failed_overwrite_keeps_old_avatar_and_removes_only_staging(data_dir):
    old = make_musetalk_avatar(data_dir, "musetalk_host")
    seen = {}

    def failing_build(work_dir, avatar_id, source_name, report, options, **_kwargs):
        seen["work_dir"] = work_dir
        # While the build runs, /offer and the catalog still see only the old avatar.
        seen["catalog"] = [item["id"] for item in list_avatar_characters()]
        seen["old_intact"] = (old / "full_imgs" / "00000000.png").read_bytes() == OLD_MARKER
        raise BuildError("沒有偵測到臉")

    with patch("nova_render.builder.extract_frames", return_value=1), \
         patch("nova_render.builder._build_musetalk", side_effect=failing_build):
        with pytest.raises(BuildError):
            build_character("musetalk", fake_video(data_dir), "musetalk_host", overwrite=True)

    assert seen["work_dir"] != old
    assert seen["work_dir"].parent == data_dir / "avatars"
    assert seen["catalog"] == ["musetalk_host"]
    assert seen["old_intact"]
    assert (old / "full_imgs" / "00000000.png").read_bytes() == OLD_MARKER
    assert remaining_build_dirs(data_dir) == []
    assert list_archived_avatars() == []


def test_successful_overwrite_moves_old_avatar_to_recycle_bin(data_dir):
    make_musetalk_avatar(data_dir, "musetalk_host")
    with patch("nova_render.builder.extract_frames", return_value=1), \
         patch("nova_render.builder._build_musetalk", side_effect=fake_musetalk_build):
        build_character("musetalk", fake_video(data_dir), "musetalk_host", overwrite=True)

    assert (data_dir / "avatars" / "musetalk_host" / "latents.pt").read_bytes() == b"new-latents"
    archived = list_archived_avatars()
    assert [item["avatar_id"] for item in archived] == ["musetalk_host"]
    archived_dir = data_dir / "avatars" / ".deleted" / archived[0]["archive_name"]
    assert (archived_dir / "full_imgs" / "00000000.png").read_bytes() == OLD_MARKER
    assert remaining_build_dirs(data_dir) == []


def test_new_avatar_appears_only_after_a_successful_build(data_dir):
    seen = {}

    def build(work_dir, avatar_id, source_name, report, options, **_kwargs):
        seen["visible"] = (data_dir / "avatars" / "musetalk_new").exists()
        fake_musetalk_build(work_dir, avatar_id, source_name, report, options)

    with patch("nova_render.builder.extract_frames", return_value=1), \
         patch("nova_render.builder._build_musetalk", side_effect=build):
        build_character("musetalk", fake_video(data_dir), "musetalk_new")

    assert seen["visible"] is False
    assert (data_dir / "avatars" / "musetalk_new" / "source.mp4").is_file()


# ---------------------------------------------------------------- import jobs


def wait_for(job, timeout=2.0):
    """Wait until the job finished and its worker released the import lock."""
    deadline = time.monotonic() + timeout
    while (job.status not in {"done", "failed"} or import_jobs.import_in_progress()) \
            and time.monotonic() < deadline:
        time.sleep(0.01)
    return job


def test_unexpected_job_error_does_not_leak_absolute_paths(tmp_path, data_dir):
    video = tmp_path / "upload" / "source.mp4"
    video.parent.mkdir()
    video.write_bytes(b"clip")
    secret = f"{tmp_path}/models/musetalk/unet.pth"

    with patch("nova_render.builder.build_character", side_effect=FileNotFoundError(secret)):
        job = import_jobs.start_import_job(
            engine="musetalk", video_path=video, original_name="clip.mp4", avatar_id="musetalk_x",
        )
        wait_for(job)

    assert job.status == "failed"
    assert str(tmp_path) not in job.error
    assert str(tmp_path) not in job.message
    assert not video.exists()


def test_the_builder_reuses_the_vae_the_core_hands_it_without_loading_models():
    from nova_render import builder

    loaded = object()
    with patch.dict("sys.modules", {"nova_render.musetalk.utils.utils": None}):
        # Loading the models would fail here; the handed-in VAE must be used instead.
        assert builder._musetalk_vae(lambda: loaded) is loaded


def test_the_running_model_comes_from_the_core_state(monkeypatch):
    model = (object(), "unet", "pe")
    config = Config()
    config.model.type = "musetalk"
    monkeypatch.setattr(state, "config", config)
    monkeypatch.setattr(state, "model", model)
    assert import_jobs.running_avatar_model() == ("musetalk", model)
    monkeypatch.setattr(state, "model", None)
    assert import_jobs.running_avatar_model() is None
    monkeypatch.setattr(state, "model", model)
    monkeypatch.setattr(state, "config", None)
    assert import_jobs.running_avatar_model() is None


def test_an_import_job_hands_the_running_vae_to_the_builder(tmp_path, data_dir, monkeypatch):
    vae = object()
    config = Config()
    config.model.type = "musetalk"
    monkeypatch.setattr(state, "config", config)
    monkeypatch.setattr(state, "model", (vae, "unet", "pe"))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"clip")
    with patch("nova_render.builder.build_character", return_value={}) as build:
        wait_for(import_jobs.start_import_job(
            engine="musetalk", video_path=video, original_name="clip.mp4", avatar_id="musetalk_vae",
        ))
    assert build.call_args.kwargs["loaded_vae"]() is vae


def test_finished_jobs_are_pruned(tmp_path, monkeypatch, data_dir):
    monkeypatch.setattr(import_jobs, "_JOBS", {})
    jobs = []
    with patch("nova_render.builder.build_character", return_value={}):
        for index in range(import_jobs.MAX_FINISHED_JOBS + 5):
            video = tmp_path / f"clip{index}.mp4"
            video.write_bytes(b"clip")
            job = import_jobs.start_import_job(
                engine="musetalk", video_path=video, original_name="clip.mp4",
                avatar_id=f"musetalk_{index}",
            )
            jobs.append(wait_for(job))

    assert len(import_jobs._JOBS) <= import_jobs.MAX_FINISHED_JOBS + 1
    assert import_jobs.get_job(jobs[-1].id) is jobs[-1]
    assert import_jobs.get_job(jobs[0].id) is None


# ---------------------------------------------------------------- HTTP handler


@pytest.fixture
def import_server(data_dir, monkeypatch):
    config = Config()
    config.model.type = "musetalk"
    config.model.avatar_id = "musetalk_live"
    monkeypatch.setattr(state, "config", config)
    monkeypatch.setattr(state, "roles", None)
    monkeypatch.setattr(state, "avatar_streams", {})
    started = []
    monkeypatch.setattr(
        settings_routes, "start_import_job",
        lambda **kwargs: started.append(kwargs) or SimpleNamespace(to_dict=lambda: {"id": "job"}),
    )
    persisted = []
    monkeypatch.setattr(
        settings_routes, "apply_mouth_quality",
        lambda config, quality, *, avatars: persisted.append(quality) or quality,
    )
    return SimpleNamespace(root=data_dir, config=config, started=started, persisted=persisted)


def import_form(fields: dict, videos=(b"video-bytes",)) -> aiohttp.FormData:
    form = aiohttp.FormData()
    for name, value in fields.items():
        form.add_field(name, value)
    for content in videos:
        form.add_field("video", content, filename="clip.mp4", content_type="video/mp4")
    return form


def leftover_uploads(root: Path) -> list[Path]:
    imports = root / "imports"
    return sorted(imports.rglob("*")) if imports.exists() else []


def post_import(form: aiohttp.FormData):
    async def run():
        async with access_client() as client:
            response = await client.post("/api/avatars/import", data=form, headers=same_origin(client))
            return response.status, await response.json()
    return asyncio.run(run())


def test_import_refuses_to_overwrite_the_live_avatar(import_server):
    make_musetalk_avatar(import_server.root, "musetalk_live")
    status, body = post_import(import_form({"type": "musetalk", "avatar_id": "musetalk_live", "overwrite": "true"}))
    assert status == 409, body
    assert import_server.started == []
    assert leftover_uploads(import_server.root) == []


def test_avatars_referenced_by_a_profile_cannot_be_replaced(import_server, monkeypatch):
    library = {"profiles": [{"avatar_id": "musetalk_guest"}]}
    monkeypatch.setattr(state, "roles", SimpleNamespace(library=library, store=SimpleNamespace(load=lambda: library)))
    assert "設定檔" in settings_routes._avatar_replace_conflict("musetalk_guest")
    assert "使用" in settings_routes._avatar_replace_conflict("musetalk_live")
    assert settings_routes._avatar_replace_conflict("musetalk_spare") is None


def test_unreadable_profiles_refuse_overwrite_before_the_build(import_server, monkeypatch):
    from nova_core.profiles.store import ProfileError

    def broken():
        raise ProfileError("角色設定 YAML 無法解析")

    class Roles:
        library = {"profiles": []}
        store = SimpleNamespace(load=broken)
        enabled = profiles_applied = False

        async def close(self):
            pass

    monkeypatch.setattr(state, "roles", Roles())
    make_musetalk_avatar(import_server.root, "musetalk_spare")
    status, body = post_import(import_form({"type": "musetalk", "avatar_id": "musetalk_spare", "overwrite": "true"}))
    assert status == 409, body
    assert "角色設定" in body["msg"]
    assert import_server.started == []
    assert leftover_uploads(import_server.root) == []
    # The builder thread asks the same guard again before installing.
    assert "角色設定" in settings_routes._avatar_replace_conflict("musetalk_spare")


def test_import_refuses_existing_avatar_without_overwrite_before_upload(import_server):
    make_musetalk_avatar(import_server.root, "musetalk_guest")
    status, body = post_import(import_form({"type": "musetalk", "avatar_id": "musetalk_guest"}))
    assert status == 409, body
    assert leftover_uploads(import_server.root) == []


def test_oversized_upload_is_rejected_with_413_and_leaves_no_files(import_server, monkeypatch):
    monkeypatch.setattr(settings_routes, "MAX_IMPORT_VIDEO_BYTES", 1024)
    status, body = post_import(import_form({"type": "musetalk"}, videos=(b"x" * 4096,)))
    assert status == 413, body
    assert import_server.started == []
    assert leftover_uploads(import_server.root) == []


@pytest.mark.parametrize("engine", ["wav2lip", "talkinggaussian", "ernerf", "ultralight"])
def test_a_removed_engine_is_rejected_before_anything_is_written(import_server, engine):
    status, body = post_import(import_form({"type": engine}))
    assert status == 400, body
    assert import_server.started == []
    assert leftover_uploads(import_server.root) == []


def test_multiple_video_parts_are_rejected(import_server):
    status, body = post_import(import_form({"type": "musetalk"}, videos=(b"one", b"two")))
    assert status == 400, body
    assert import_server.started == []
    assert leftover_uploads(import_server.root) == []


def test_quality_is_not_persisted_when_the_import_is_rejected(import_server, monkeypatch):
    monkeypatch.setattr(state, "avatar_streams", {1: object()})
    status, body = post_import(import_form({"type": "musetalk", "quality": '{"mouth_sharpen": 0.9}'}))
    assert status == 409, body
    assert import_server.persisted == []
    assert leftover_uploads(import_server.root) == []


def test_accepted_import_persists_quality_and_hands_upload_to_job(import_server):
    status, body = post_import(import_form({"type": "musetalk", "quality": '{"mouth_sharpen": 0.9}'}))
    assert status == 200, body
    assert import_server.persisted == [{"mouth_sharpen": 0.9}]
    [started] = import_server.started
    assert started["video_path"].read_bytes() == b"video-bytes"
    assert started["replace_guard"] is not None
