# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
import pickle
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import pytest
import torch

from src.avatars import builder, catalog
from src.avatars.musetalk.utils.face_parsing.resnet import Resnet18


ROOT = Path(__file__).resolve().parents[1]
REAL_RESNET_CKPT = ROOT / "models/face-parse-bisent/resnet18-5c106cde.pth"
REAL_BISENET_CKPT = ROOT / "models/face-parse-bisent/79999_iter.pth"


def _add_tar_bytes(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))


def _write_legacy_tar_checkpoint(path: Path) -> None:
    """Create a minimal PyTorch legacy .tar checkpoint matching resnet18-5c106cde.pth."""
    storages = pickle.dumps(0) + pickle.dumps([])
    tensors = pickle.dumps(0)
    state_dict = pickle.dumps({"fc.bias": 0})
    with tarfile.open(path, mode="w:", format=tarfile.PAX_FORMAT) as tar:
        _add_tar_bytes(tar, "storages", storages)
        _add_tar_bytes(tar, "tensors", tensors)
        _add_tar_bytes(tar, "pickle", state_dict)


def _write_test_video(path: Path, frame: np.ndarray) -> None:
    height, width = frame.shape[:2]
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (width, height)
    )
    assert writer.isOpened()
    try:
        writer.write(frame)
    finally:
        writer.release()


def test_resnet18_loads_legacy_tar_checkpoint_under_pytorch_weights_only_default(tmp_path):
    legacy_ckpt = tmp_path / "legacy_resnet18.pth"
    _write_legacy_tar_checkpoint(legacy_ckpt)

    net = Resnet18(str(legacy_ckpt))
    feat8, feat16, feat32 = net(torch.zeros(1, 3, 64, 64))
    assert feat8.shape == (1, 128, 8, 8)
    assert feat16.shape == (1, 256, 4, 4)
    assert feat32.shape == (1, 512, 2, 2)


@pytest.mark.skipif(
    not (REAL_RESNET_CKPT.is_file() and REAL_BISENET_CKPT.is_file()),
    reason="local face-parse-bisent weights not installed",
)
def test_build_musetalk_character_registers_in_catalog_with_real_face_parsing(tmp_path):
    frame = np.full((512, 512, 3), (40, 190, 40), dtype=np.uint8)
    cv2.circle(frame, (256, 240), 90, (190, 200, 220), -1)
    clip = tmp_path / "musetalk_clip.mp4"
    _write_test_video(clip, frame)
    avatars_dir = tmp_path / "avatars"
    avatars_dir.mkdir()

    class StubVAE:
        def get_latents_for_unet(self, _crop):
            return torch.zeros((1, 8, 32, 32), dtype=torch.float16)

    with (
        patch.object(builder, "avatars_root", return_value=avatars_dir),
        patch.object(catalog, "avatars_root", return_value=avatars_dir),
        patch(
            "src.avatars.musetalk.utils.preprocessing.get_landmark_and_bbox",
            return_value=([(160, 140, 352, 340)], [frame]),
        ),
        patch.object(builder, "_musetalk_vae", return_value=StubVAE()),
    ):
        result = builder.build_character(
            "musetalk",
            clip,
            "musetalk_imported",
            green_screen=True,
        )
        characters = catalog.list_avatar_characters()

    assert result == {"type": "musetalk", "avatar_id": "musetalk_imported", "frames": 1}
    matched = next((item for item in characters if item["id"] == "musetalk_imported"), None)
    assert matched is not None
    assert matched["type"] == "musetalk"
    assert matched["green_screen"] is True
    assert (avatars_dir / "musetalk_imported" / "latents.pt").is_file()
    assert (avatars_dir / "musetalk_imported" / "mask" / "00000000.png").is_file()


def test_build_wav2lip_character_imports_bundled_face_detector_from_package(tmp_path):
    from src.avatars.wav2lip.face_detection.detection.sfd import sfd_detector

    frame = np.full((320, 320, 3), 120, dtype=np.uint8)
    clip = tmp_path / "wav2lip_clip.mp4"
    _write_test_video(clip, frame)
    avatars_dir = tmp_path / "avatars"
    avatars_dir.mkdir()

    class FakeSFDDetector:
        def __init__(self, device, verbose=False):
            self.device = device
            self.verbose = verbose

        def detect_from_batch(self, images):
            return [[np.array([80, 60, 240, 250, 0.99])] for _ in range(len(images))]

    progress_events = []
    with (
        patch.object(sfd_detector, "SFDDetector", FakeSFDDetector),
        patch(
            "src.avatars.wav2lip.face_detection.detection.sfd.FaceDetector",
            FakeSFDDetector,
        ),
        patch.object(builder, "avatars_root", return_value=avatars_dir),
        patch.object(catalog, "avatars_root", return_value=avatars_dir),
    ):
        result = builder.build_character(
            "wav2lip",
            clip,
            "wav2lip_imported",
            progress=lambda pct, msg: progress_events.append((pct, msg)),
        )
        characters = catalog.list_avatar_characters()

    assert result == {"type": "wav2lip", "avatar_id": "wav2lip_imported", "frames": 1}
    assert progress_events and all(0 <= pct <= 100 for pct, _ in progress_events)
    matched = next((item for item in characters if item["id"] == "wav2lip_imported"), None)
    assert matched is not None
    assert matched["type"] == "wav2lip"
    assert (avatars_dir / "wav2lip_imported" / "face_imgs" / "00000000.png").is_file()


def test_musetalk_vae_loads_vae_only_without_unet_when_runtime_model_absent(tmp_path):
    loaded = {}

    class FakeInnerModule:
        def half(self):
            loaded["half"] = True
            return self

        def to(self, device):
            loaded["device"] = str(device)
            return self

    class FakeVAE:
        def __init__(self, model_path):
            loaded["model_path"] = model_path
            self.vae = FakeInnerModule()

    fake_state = SimpleNamespace(config=SimpleNamespace(model=SimpleNamespace(type="musetalk")), model=None)
    with (
        patch("src.server.state.state", fake_state),
        patch("src.avatars.musetalk.models.vae.VAE", FakeVAE),
        patch(
            "src.avatars.musetalk.utils.utils.load_all_model",
            side_effect=AssertionError("load_all_model should not be called for VAE-only import"),
        ),
    ):
        vae = builder._musetalk_vae()

    assert isinstance(vae, FakeVAE)
    assert Path(loaded["model_path"]).name == "sd-vae"
    assert loaded["half"] is True


def test_build_character_replaces_incomplete_orphan_directory_without_overwrite(tmp_path):
    avatars_dir = tmp_path / "avatars"
    orphan = avatars_dir / "test"
    (orphan / "full_imgs").mkdir(parents=True)
    (orphan / "mask").mkdir(parents=True)
    (orphan / "avator_info.json").write_text('{"avatar_id": "test", "engine": "musetalk"}', encoding="utf-8")
    (orphan / "source.mp4").write_bytes(b"interrupted-upload")

    video = tmp_path / "fresh.mp4"
    video.write_bytes(b"fresh-video")

    def fake_build(work_dir, avatar_id, video_path, report, options):
        assert work_dir.name.startswith(".building-")
        (work_dir / "mask").mkdir(exist_ok=True)
        (work_dir / "latents.pt").write_bytes(b"latents")
        (work_dir / "coords.pkl").write_bytes(b"coords")
        (work_dir / "mask_coords.pkl").write_bytes(b"mask_coords")

    with (
        patch.object(builder, "avatars_root", return_value=avatars_dir),
        patch.object(catalog, "avatars_root", return_value=avatars_dir),
        patch.object(builder, "extract_frames", side_effect=lambda _src, dst, **_kw: dst.mkdir(parents=True, exist_ok=True) or 2),
        patch.object(builder, "_build_musetalk", side_effect=fake_build),
    ):
        assert catalog.list_avatar_characters() == []
        result = builder.build_character("musetalk", video, "test", overwrite=False)
        characters = catalog.list_avatar_characters()

    assert result["avatar_id"] == "test"
    assert [item["id"] for item in characters] == ["test"]
    assert not list(avatars_dir.glob(".building-*"))


def test_build_character_failed_overwrite_preserves_existing_usable_avatar(tmp_path):
    avatars_dir = tmp_path / "avatars"
    existing = avatars_dir / "musetalk_keep"
    (existing / "full_imgs").mkdir(parents=True)
    (existing / "mask").mkdir(parents=True)
    (existing / "latents.pt").write_bytes(b"original-latents")
    (existing / "coords.pkl").write_bytes(b"original-coords")
    (existing / "mask_coords.pkl").write_bytes(b"original-mask-coords")

    video = tmp_path / "bad.mp4"
    video.write_bytes(b"bad-video")

    with (
        patch.object(builder, "avatars_root", return_value=avatars_dir),
        patch.object(catalog, "avatars_root", return_value=avatars_dir),
        patch.object(builder, "extract_frames", side_effect=builder.BuildError("影片損毀")),
    ):
        with pytest.raises(builder.BuildError, match="影片損毀"):
            builder.build_character("musetalk", video, "musetalk_keep", overwrite=True)

    assert (existing / "latents.pt").read_bytes() == b"original-latents"
    assert not list(avatars_dir.glob(".building-*"))

