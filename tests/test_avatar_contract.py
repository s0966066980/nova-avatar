# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The avatar rendering layer's contract: its DTOs and the in-process adapter."""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from nova_contracts.avatar import (
    STAGE_FPS,
    STAGE_FRAME,
    AvatarBootCheck,
    AvatarRenderer,
    AvatarService,
    FrameSize,
)
from nova_contracts.common import ServiceError
from src.scene.service import scene_service


def test_a_boot_check_explains_why_an_avatar_cannot_start():
    refused = AvatarBootCheck(bootable=False, reason="素材不存在")

    assert (refused.bootable, refused.reason) == (False, "素材不存在")
    assert AvatarBootCheck(bootable=True).reason == ""


def test_a_frame_size_is_positive_and_immutable():
    size = FrameSize(width=720, height=1280)

    with pytest.raises(ValidationError):
        FrameSize(width=0, height=1280)
    with pytest.raises(ValidationError):
        size.width = 360  # type: ignore[misc]


def test_the_stage_is_a_portrait_720p_canvas_at_25_fps():
    assert (STAGE_FRAME.width, STAGE_FRAME.height, STAGE_FPS) == (720, 1280, 25)


# One conversation's renderer, as the core sees it.

def _renderer():
    from src.avatars.base import BaseAvatar

    return BaseAvatar(SimpleNamespace(
        model=SimpleNamespace(type="none"), audio=SimpleNamespace(fps=50),
        video=SimpleNamespace(max_height=0), sessionid=7, customopt=[],
    ))


def _frame(value):
    return np.full((STAGE_FRAME.height, STAGE_FRAME.width, 3), value, np.uint8)


def test_the_renderer_satisfies_the_avatar_renderer_protocol():
    renderer = _renderer()

    assert isinstance(renderer, AvatarRenderer)
    assert (renderer.sessionid, renderer.chunk, renderer.asset_epoch) == (7, 320, 0)


def test_a_role_transition_holds_the_old_role_until_the_core_starts_it(monkeypatch):
    monkeypatch.setattr(scene_service, "background_frame", lambda *_: None)
    renderer = _renderer()
    renderer.reset_role_presentation(True)
    renderer._present_frame(_frame(10), None)

    renderer.begin_role_transition("t1", {"kind": "effect", "effect": "fade", "duration": .01},
                                   clip=None, started_at=time.monotonic() + 3600)
    held, marker = renderer._present_frame(_frame(200), None)
    assert held.mean() < 50 and marker == {}

    renderer.start_role_transition(time.monotonic() - 1)
    played, marker = renderer._present_frame(_frame(200), {"turn_id": "a"})
    assert played.mean() > 150
    assert marker == {"turn_id": "a", "role_transition_id": "t1", "role_transition_end": True}

    renderer.close_role_transition()
    assert renderer._present_frame(_frame(200), None)[1] == {}


def test_without_role_composition_a_frame_is_only_height_limited():
    renderer = _renderer()
    renderer.reset_role_presentation(False)
    renderer.close_role_transition()
    frame = _frame(30)

    passed, marker = renderer._present_frame(frame, None)
    assert passed is frame and marker is None
    renderer.ensure_role_presentation()
    composed, _ = renderer._present_frame(frame, None)
    assert composed is not frame


# The process-wide service, served in-process.

@pytest.fixture
def avatars(tmp_path, monkeypatch):
    from src.avatars.adapter import create_avatar_service

    monkeypatch.setattr("src.avatars.catalog.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.scene.service.get_data_dir", lambda: tmp_path)
    return create_avatar_service()


def _install_avatar(root, avatar_id, size=(40, 80)):
    from PIL import Image

    directory = root / "avatars" / avatar_id
    (directory / "full_imgs").mkdir(parents=True)
    (directory / "mask").mkdir()
    (directory / "latents.pt").write_bytes(b"")
    Image.new("RGB", size).save(directory / "full_imgs" / "00000000.png")
    return directory


def test_the_adapter_is_an_avatar_service(avatars):
    assert isinstance(avatars, AvatarService)


def test_an_unknown_engine_is_not_bootable_and_says_why(avatars):
    check = avatars.bootable("wav2lip", "someone")

    assert check == AvatarBootCheck(bootable=False, reason="不支援的數字人引擎: wav2lip")
    assert not avatars.knows_engine("wav2lip") and avatars.knows_engine("musetalk")
    assert avatars.can_import("musetalk") and not avatars.can_import("wav2lip")


def test_catalog_refusals_are_service_errors_for_operators(avatars):
    with pytest.raises(ServiceError, match="找不到數字人"):
        avatars.archive_avatar("nobody")
    with pytest.raises(ServiceError, match="找不到封存的數字人"):
        avatars.restore_avatar("nobody-000000000000")
    with pytest.raises(ServiceError):
        avatars.normalize_quality({"mouth_sharpen": "very"})
    with pytest.raises(ServiceError):
        avatars.background_preview("../../etc")


def test_an_archived_avatar_is_named_by_its_archive_and_restores(avatars, tmp_path):
    _install_avatar(tmp_path, "angela")
    assert avatars.avatar_exists("angela")

    archive_name = avatars.archive_avatar("angela")

    assert not avatars.avatar_exists("angela")
    assert avatars.list_archived_avatars() == [{"archive_name": archive_name, "avatar_id": "angela"}]
    assert avatars.restore_avatar(archive_name) == "angela"


def test_the_source_and_output_size_come_from_the_avatar_preview(avatars, tmp_path):
    _install_avatar(tmp_path, "angela", size=(720, 1280))

    assert avatars.source_size("angela") == FrameSize(width=720, height=1280)
    assert avatars.source_size("../angela") is None
    assert avatars.output_size(720, 1280, 640) == FrameSize(width=360, height=640)
    assert avatars.output_size(720, 1280) == FrameSize(width=720, height=1280)


def test_a_build_borrows_the_running_musetalk_vae(avatars, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("src.avatars.builder.build_character",
                        lambda *args, **kwargs: calls.append(kwargs) or {"avatar_id": args[2]})
    vae = object()

    avatars.build_avatar("musetalk", tmp_path / "v.mp4", "angela",
                         running_model=lambda: ("musetalk", (vae, "unet")))
    avatars.build_avatar("musetalk", tmp_path / "v.mp4", "angela", running_model=lambda: None)

    assert calls[0]["loaded_vae"]() is vae
    assert calls[1]["loaded_vae"]() is None


def test_a_failed_build_is_a_service_error(avatars, monkeypatch, tmp_path):
    from src.avatars import builder

    def refuse(*_args, **_kwargs):
        raise builder.BuildError("角色 angela 已存在，請換一個名稱")

    monkeypatch.setattr(builder, "build_character", refuse)

    with pytest.raises(ServiceError, match="已存在"):
        avatars.build_avatar("musetalk", tmp_path / "v.mp4", "angela")
