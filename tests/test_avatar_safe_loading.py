# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Avatar assets load without executing code planted in a writable avatar dir."""

from __future__ import annotations

import ast
import json
import os
import pickle
import subprocess
from pathlib import Path

import numpy as np
import pytest
import torch

from src.avatars.asset_io import (
    UnsafeAssetError,
    coords_present,
    load_avatar_tensors,
    load_coords,
    save_coords,
)
from src.avatars.catalog import detect_avatar_type

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED_ENGINES = ("musetalk", "ultralight", "wav2lip")
TORCH_LOADERS = {"load_url", "load_state_dict_from_url"}


class _Exploit:
    """Unpickling this object would create ``marker`` as a side effect."""

    def __init__(self, marker: Path):
        self.marker = marker

    def __reduce__(self):
        return (os.mkdir, (str(self.marker),))


class _ObjectScalar:
    """A NumPy scalar pickle whose dtype carries raw object pointers."""

    def __reduce__(self):
        return (np.core.multiarray.scalar, (np.dtype(object), b"\0" * 8))


def _write_pickle(path: Path, value) -> None:
    path.write_bytes(pickle.dumps(value))


# ------------------------------------------------------------ legacy coords


def test_malicious_legacy_coords_pickle_is_rejected_without_side_effects(tmp_path):
    marker = tmp_path / "pwned"
    _write_pickle(tmp_path / "coords.pkl", [[1, 2, 3, 4], _Exploit(marker)])

    with pytest.raises(UnsafeAssetError):
        load_coords(tmp_path, "coords")

    assert not marker.exists()
    assert not (tmp_path / "coords.json").exists()


@pytest.mark.parametrize(
    "payload",
    [
        [np.array([1, 2, 3, 4])],
        [_ObjectScalar()],
        [[1, 2, 3]],
        [[True, 2, 3, 4]],
        [[1, 2, 3, "4"]],
        {"x": [1, 2, 3, 4]},
    ],
    ids=["ndarray", "object-dtype-scalar", "short-box", "bool", "string", "dict"],
)
def test_legacy_coords_outside_the_coordinate_shape_are_rejected(tmp_path, payload):
    _write_pickle(tmp_path / "coords.pkl", payload)

    with pytest.raises(UnsafeAssetError):
        load_coords(tmp_path, "coords")


def test_legacy_coords_convert_once_to_json(tmp_path):
    legacy = [
        [10, 20, 110, 120],
        (5, 6, 7, 8),
        (np.int64(1), np.int64(2), np.int32(3), np.float32(4.5)),
        (0.0, 0.0, 0.0, 0.0),
    ]
    _write_pickle(tmp_path / "mask_coords.pkl", legacy)

    coords = load_coords(tmp_path, "mask_coords")

    expected = [[10, 20, 110, 120], [5, 6, 7, 8], [1, 2, 3, 4.5], [0.0, 0.0, 0.0, 0.0]]
    assert coords == expected
    assert all(type(value) in (int, float) for box in coords for value in box)
    assert json.loads((tmp_path / "mask_coords.json").read_text()) == expected

    # Once converted, the pickle is never consulted again.
    _write_pickle(tmp_path / "mask_coords.pkl", [_Exploit(tmp_path / "pwned")])
    assert load_coords(tmp_path, "mask_coords") == expected
    assert not (tmp_path / "pwned").exists()


def test_legacy_coords_still_load_from_a_read_only_avatar_dir(tmp_path, monkeypatch):
    _write_pickle(tmp_path / "coords.pkl", [(1, 2, 3, 4)])

    def refuse(*_args, **_kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr("src.avatars.asset_io.os.replace", refuse)

    assert load_coords(tmp_path, "coords") == [[1, 2, 3, 4]]
    assert not (tmp_path / "coords.json").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["coords.pkl"]


def test_json_coords_are_validated(tmp_path):
    (tmp_path / "coords.json").write_text(json.dumps([[1, 2, 3]]))

    with pytest.raises(UnsafeAssetError):
        load_coords(tmp_path, "coords")


def test_saved_coords_round_trip_as_json(tmp_path):
    save_coords(tmp_path / "coords.json", [(np.int64(1), 2, 3, 4), [5, 6, 7, 8]])

    assert json.loads((tmp_path / "coords.json").read_text()) == [[1, 2, 3, 4], [5, 6, 7, 8]]
    assert load_coords(tmp_path, "coords") == [[1, 2, 3, 4], [5, 6, 7, 8]]
    assert coords_present(tmp_path, "coords")
    assert not coords_present(tmp_path, "mask_coords")


def test_missing_coords_raise_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_coords(tmp_path, "coords")


# ------------------------------------------------------------ tensors


def test_avatar_tensors_refuse_pickled_code(tmp_path):
    marker = tmp_path / "pwned"
    path = tmp_path / "latents.pt"
    torch.save([torch.zeros(1), _Exploit(marker)], path)

    with pytest.raises(pickle.UnpicklingError):
        load_avatar_tensors(path)

    assert not marker.exists()


def test_avatar_tensors_load_plain_tensor_lists(tmp_path):
    path = tmp_path / "latents.pt"
    torch.save([torch.ones(1, 8, 32, 32), torch.zeros(1, 8, 32, 32)], path)

    latents = load_avatar_tensors(path)

    assert [tuple(t.shape) for t in latents] == [(1, 8, 32, 32)] * 2


# ------------------------------------------------------------ MuseTalk avatar


def _musetalk_fixture(root: Path, avatar_id: str) -> Path:
    avatar = root / "data" / "avatars" / avatar_id
    (avatar / "full_imgs").mkdir(parents=True)
    (avatar / "mask").mkdir()
    torch.save([torch.zeros(1, 8, 32, 32)], avatar / "latents.pt")
    return avatar


def test_musetalk_avatar_rejects_malicious_coords(tmp_path, monkeypatch):
    from src.avatars.musetalk.avatar import load_avatar

    avatar = _musetalk_fixture(tmp_path, "musetalk_evil")
    marker = tmp_path / "pwned"
    _write_pickle(avatar / "coords.pkl", [_Exploit(marker)])
    _write_pickle(avatar / "mask_coords.pkl", [[1, 2, 3, 4]])
    monkeypatch.chdir(tmp_path)

    with pytest.raises(UnsafeAssetError):
        load_avatar("musetalk_evil")
    assert not marker.exists()


def test_musetalk_avatar_rejects_malicious_latents(tmp_path, monkeypatch):
    from src.avatars.musetalk.avatar import load_avatar

    avatar = _musetalk_fixture(tmp_path, "musetalk_evil")
    marker = tmp_path / "pwned"
    torch.save([_Exploit(marker)], avatar / "latents.pt")
    save_coords(avatar / "coords.json", [[1, 2, 3, 4]])
    save_coords(avatar / "mask_coords.json", [[1, 2, 3, 4]])
    monkeypatch.chdir(tmp_path)

    with pytest.raises(pickle.UnpicklingError):
        load_avatar("musetalk_evil")
    assert not marker.exists()


def test_musetalk_avatar_converts_legacy_coords(tmp_path, monkeypatch):
    from src.avatars.musetalk.avatar import load_avatar

    avatar = _musetalk_fixture(tmp_path, "musetalk_old")
    _write_pickle(avatar / "coords.pkl", [[1, 2, 3, 4]])
    _write_pickle(avatar / "mask_coords.pkl", [[0, 0, 9, 9]])
    monkeypatch.chdir(tmp_path)

    _frames, _masks, coords, mask_coords, latents = load_avatar("musetalk_old")

    assert coords == [[1, 2, 3, 4]]
    assert mask_coords == [[0, 0, 9, 9]]
    assert len(latents) == 1
    assert (avatar / "coords.json").is_file()
    assert (avatar / "mask_coords.json").is_file()


def test_wav2lip_build_writes_json_coords(tmp_path, monkeypatch):
    import cv2

    from src.avatars import builder
    from src.avatars.mouth_quality import normalize_quality

    class FakeDetector:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_detections_for_batch(self, frames):
            return [(8, 8, 40, 40) for _ in frames]

    monkeypatch.setattr("src.avatars.wav2lip.face_detection.FaceAlignment", FakeDetector)
    full_imgs = tmp_path / "full_imgs"
    full_imgs.mkdir()
    for index in range(2):
        cv2.imwrite(str(full_imgs / f"{index:08d}.png"), np.zeros((64, 64, 3), np.uint8))

    builder._build_wav2lip(tmp_path, lambda *_: None, normalize_quality(None))

    assert not (tmp_path / "coords.pkl").exists()
    assert load_coords(tmp_path, "coords") == [[8, 50, 8, 40], [8, 50, 8, 40]]


def test_catalog_recognizes_wav2lip_avatars_with_json_coords(tmp_path):
    avatar = tmp_path / "host"
    (avatar / "face_imgs").mkdir(parents=True)
    save_coords(avatar / "coords.json", [[1, 2, 3, 4]])

    assert detect_avatar_type(avatar) == "wav2lip"


# ------------------------------------------------------------ static guard


def _call_name(node: ast.Call) -> str:
    func = node.func
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def _weights_only_true(node: ast.Call) -> bool:
    return any(
        kw.arg == "weights_only"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in node.keywords
    )


def _tracked_engine_sources() -> list[Path]:
    # Gitignored local copies (for example vendored model packages under a
    # ``models/`` directory) are outside the repository's control.
    listed = subprocess.run(
        ["git", "ls-files", "--", *(f"src/avatars/{engine}" for engine in SCANNED_ENGINES)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [REPO_ROOT / name for name in listed if name.endswith(".py")]


def test_engine_sources_never_unpickle_arbitrary_objects():
    sources = _tracked_engine_sources()
    assert sources
    offenders = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            where = f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
            is_loader = name == "torch.load" or name.rsplit(".", 1)[-1] in TORCH_LOADERS
            if is_loader and not _weights_only_true(node):
                offenders.append(f"{where} {name} without weights_only=True")
            if name in {"pickle.load", "pickle.loads", "pickle.Unpickler"}:
                offenders.append(f"{where} {name}")
    assert offenders == []
