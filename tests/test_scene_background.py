# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from types import SimpleNamespace
import asyncio
import json

import cv2
import numpy as np
import pytest

from src.scene import service
from src.avatars import catalog
from src.server.routes import settings as settings_routes


def test_green_screen_composites_person_and_keeps_background_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "backgrounds_root", lambda: tmp_path / "backgrounds")
    source = tmp_path / "uploaded.png"
    background = np.full((64, 64, 3), (200, 40, 20), np.uint8)
    assert cv2.imwrite(str(source), background)
    item = service.add_background(source, "studio.png")

    scene = service.SceneService()
    try:
        scene.select(item["id"], fade_seconds=0)
        foreground = np.full((64, 64, 3), (52, 185, 53), np.uint8)
        foreground[20:44, 20:44] = (20, 20, 210)
        result = scene.compose(foreground, green_screen=True)
        assert np.array_equal(result[0, 0], background[0, 0])
        assert np.array_equal(result[30, 30], foreground[30, 30])
        assert np.array_equal(scene.compose(foreground, green_screen=False), foreground)
    finally:
        scene.close()


def test_chroma_composite_despills_translucent_and_opaque_edge_without_changing_interior():
    foreground = np.full((48, 48, 3), (20, 180, 20), np.uint8)
    foreground[8:40, 8:40] = (90, 105, 90)
    foreground[8:40, 8] = (60, 115, 60)  # Green mixed into a translucent edge.
    foreground[8:40, 9] = (80, 100, 80)  # Opaque pixel with a green fringe.
    background = np.full_like(foreground, 100)

    result = service.chroma_composite(foreground, background)

    assert np.array_equal(result[0, 0], background[0, 0])
    assert result[24, 8, 1] <= result[24, 8, 0] + 1
    assert result[24, 9, 1] <= result[24, 9, 0] + 1
    # Far from any green edge (well past the despill radius, and away from
    # the block's own far border): untouched bit-for-bit.
    assert np.array_equal(result[24, 28], foreground[24, 28])


def test_chroma_composite_cleans_a_wide_ambient_spill_halo_on_high_resolution_frame():
    """A real camera's green-screen bounce light spills ~15-20px around the
    silhouette (measured on production footage), not just a few pixels. A
    fixed, narrow edge band misses most of that halo and leaves a visible
    green fringe once composited onto a new background."""
    height = 1200  # Scales the despill radius up from its low-resolution floor.
    foreground = np.full((height, 64, 3), (20, 180, 20), np.uint8)
    foreground[:, 20:] = (90, 95, 90)  # True interior: a faint, legitimate cool tint.
    foreground[:, 18:20] = (60, 115, 60)  # Translucent transition into the screen.
    # Ambient spill band: still classified "clean foreground" by the old
    # excess<=20 rule, but visibly green a dozen pixels into the silhouette.
    for offset, excess in enumerate([18, 16, 14, 12, 10, 8, 6]):
        column = 20 + offset
        foreground[:, column] = (90, 90 + excess, 90)

    background = np.full_like(foreground, 150)
    result = service.chroma_composite(foreground, background)

    for offset in range(4):  # Close to the edge: the halo must be cleaned up.
        column = 20 + offset
        assert result[0, column, 1] <= result[0, column, 0] + 2, f"column {column} still shows green spill"
    # Far past the measured halo width: legitimate interior color is untouched.
    assert np.array_equal(result[0, 60], foreground[0, 60])


def test_chroma_composite_fits_the_render_frame_budget_on_a_portrait_avatar():
    """Compositing runs on the render thread for every frame. Past the 40ms
    budget at 25fps the WebRTC media clock falls behind real time, which
    shows up as heavy idle-state jitter."""
    import time

    height, width = 1920, 1080
    yy, xx = np.mgrid[0:height, 0:width]
    person = ((xx - width / 2) / 380) ** 2 + ((yy - height) / 1400) ** 2 < 1
    foreground = np.full((height, width, 3), (60, 200, 80), np.uint8)
    foreground[person] = (120, 110, 150)
    background = np.full_like(foreground, 150)

    service.chroma_composite(foreground, background)
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        service.chroma_composite(foreground, background)
        timings.append(time.perf_counter() - started)
    assert sorted(timings)[2] < 0.030


def test_background_catalog_rejects_unsupported_file(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "backgrounds_root", lambda: tmp_path / "backgrounds")
    source = tmp_path / "uploaded.txt"
    source.write_text("not an image")
    with pytest.raises(service.SceneError):
        service.add_background(source, "script.txt")
    assert source.is_file()


def test_background_selection_rejects_missing_id(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "backgrounds_root", lambda: tmp_path / "backgrounds")
    scene = service.SceneService()
    with pytest.raises(service.SceneError):
        scene.select("../../other")
    assert scene.snapshot()["background_id"] == ""


def test_existing_green_trial_and_new_asset_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "avatars_root", lambda: tmp_path)
    for avatar_id in ("musetalk_avatar", "musetalk_other"):
        avatar = tmp_path / avatar_id
        avatar.mkdir()
        (avatar / "latents.pt").write_bytes(b"test")
        (avatar / "mask").mkdir()
    assert catalog.avatar_uses_green_screen("musetalk_avatar")
    assert not catalog.avatar_uses_green_screen("musetalk_other")
    archived = catalog.archive_avatar("musetalk_other")
    assert archived.is_dir()
    assert not (tmp_path / "musetalk_other").exists()
    assert [item["id"] for item in catalog.list_avatar_characters()] == ["musetalk_avatar"]
    assert catalog.list_archived_avatars() == [
        {"archive_name": archived.name, "avatar_id": "musetalk_other"}
    ]
    assert catalog.restore_avatar(archived.name) == "musetalk_other"
    assert (tmp_path / "musetalk_other").is_dir()


def test_archived_avatar_can_be_permanently_deleted_without_touching_active_avatars(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "avatars_root", lambda: tmp_path)
    active = tmp_path / "musetalk_active"
    active.mkdir()
    archived_source = tmp_path / "musetalk_old"
    archived_source.mkdir()
    (archived_source / "source.mp4").write_bytes(b"original upload")
    archive = catalog.archive_avatar("musetalk_old")

    with pytest.raises(ValueError, match="找不到封存"):
        catalog.delete_archived_avatar("../musetalk_active")
    assert catalog.delete_archived_avatar(archive.name) == "musetalk_old"
    assert not archive.exists()
    assert active.is_dir()
    assert catalog.list_archived_avatars() == []


def test_archived_avatar_delete_route_removes_only_the_requested_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "avatars_root", lambda: tmp_path)
    monkeypatch.setattr(settings_routes.state, "config", SimpleNamespace())
    archives = []
    for avatar_id in ("musetalk_one", "musetalk_two"):
        source = tmp_path / avatar_id
        source.mkdir()
        archives.append(catalog.archive_avatar(avatar_id))
    request = SimpleNamespace(match_info={"archive_name": archives[0].name})

    response = asyncio.run(settings_routes.delete_archived_avatar_permanently(request))

    assert response.status == 200
    assert json.loads(response.text)["data"]["avatar_id"] == "musetalk_one"
    assert not archives[0].exists()
    assert archives[1].is_dir()


def test_console_scene_preview_uses_selected_background(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog, "avatars_root", lambda: tmp_path / "avatars")
    monkeypatch.setattr(service, "backgrounds_root", lambda: tmp_path / "backgrounds")
    avatar = tmp_path / "avatars" / "musetalk_avatar"
    (avatar / "full_imgs").mkdir(parents=True)
    (avatar / "mask").mkdir()
    (avatar / "latents.pt").write_bytes(b"test")
    foreground = np.full((64, 64, 3), (52, 185, 53), np.uint8)
    foreground[20:44, 20:44] = (20, 20, 210)
    assert cv2.imwrite(str(avatar / "full_imgs" / "00000000.png"), foreground)
    upload = tmp_path / "background.png"
    assert cv2.imwrite(str(upload), np.full((64, 64, 3), (200, 40, 20), np.uint8))
    item = service.add_background(upload, "background.png")
    scene = service.SceneService()
    try:
        scene.select(item["id"], fade_seconds=0)
        jpeg = service.render_avatar_preview("musetalk_avatar", scene)
        rendered = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert rendered is not None
        assert np.max(np.abs(rendered[0, 0].astype(int) - (200, 40, 20))) < 8
        assert np.max(np.abs(rendered[30, 30].astype(int) - (20, 20, 210))) < 8
        second_upload = tmp_path / "second.png"
        assert cv2.imwrite(str(second_upload), np.full((64, 64, 3), (20, 80, 180), np.uint8))
        second_item = service.add_background(second_upload, "second.png")
        scene.select(second_item["id"], fade_seconds=0.2)
        immediate = cv2.imdecode(
            np.frombuffer(service.render_avatar_preview("musetalk_avatar", scene), np.uint8),
            cv2.IMREAD_COLOR,
        )
        assert np.max(np.abs(immediate[0, 0].astype(int) - (20, 80, 180))) < 8
    finally:
        scene.close()


def test_background_can_be_archived_and_restored_without_changing_id(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "backgrounds_root", lambda: tmp_path / "backgrounds")
    upload = tmp_path / "studio.png"
    assert cv2.imwrite(str(upload), np.full((32, 32, 3), (30, 80, 150), np.uint8))
    item = service.add_background(upload, "studio.png")
    archive = service.archive_background(item["id"])
    assert service.list_backgrounds() == []
    assert service.list_archived_backgrounds() == [{
        "archive_name": archive.name, "id": item["id"], "label": "studio", "kind": "image",
    }]
    conflict = tmp_path / "backgrounds" / f"{item['id']}.json"
    conflict.write_text("{}", encoding="utf-8")
    with pytest.raises(service.SceneError, match="同 ID 背景已存在"):
        service.restore_background(archive.name)
    assert archive.is_dir()
    conflict.unlink()
    assert service.restore_background(archive.name) == item["id"]
    assert [entry["id"] for entry in service.list_backgrounds()] == [item["id"]]
    assert service.list_archived_backgrounds() == []


def test_active_background_cannot_be_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "backgrounds_root", lambda: tmp_path / "backgrounds")
    upload = tmp_path / "studio.png"
    assert cv2.imwrite(str(upload), np.full((32, 32, 3), (30, 80, 150), np.uint8))
    item = service.add_background(upload, "studio.png")
    monkeypatch.setattr(settings_routes.state, "config", SimpleNamespace(
        stage=SimpleNamespace(background_id=item["id"]),
    ))
    request = SimpleNamespace(match_info={"background_id": item["id"]})
    response = asyncio.run(settings_routes.delete_background(request))
    assert response.status == 409
    assert [entry["id"] for entry in service.list_backgrounds()] == [item["id"]]
