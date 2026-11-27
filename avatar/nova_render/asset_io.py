# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Load avatar assets without executing code stored next to them.

Avatar directories are writable by the console's import flow, so nothing read
from them may be unpickled freely. Face boxes are stored as JSON; tensors are
loaded with ``torch.load(weights_only=True)``. Avatars built before this format
change still have ``coords.pkl`` files: those are read once with a restricted
unpickler that only rebuilds lists, tuples and numeric scalars, then rewritten
as JSON next to the original.
"""

from __future__ import annotations

import io
import json
import math
import os
import pickle
import tempfile
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from src.utils.logging import logger

MAX_COORDS_BYTES = 16 * 1024 * 1024
BOX_LENGTH = 4

# Plain fixed-size numeric dtypes a legacy NumPy scalar may carry.
_NUMERIC_DTYPES = frozenset(
    {"b1", "i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8", "f2", "f4", "f8"}
)
_BYTE_ORDERS = frozenset({"<", ">", "|", "="})

Coords = list[list[float]]


class UnsafeAssetError(ValueError):
    """An avatar asset holds something other than plain data."""


# ------------------------------------------------------------ coordinates


def coords_present(avatar_dir: Path, name: str) -> bool:
    avatar_dir = Path(avatar_dir)
    return (avatar_dir / f"{name}.json").is_file() or (avatar_dir / f"{name}.pkl").is_file()


def load_coords(avatar_dir: Path, name: str) -> Coords:
    """Return the face boxes stored as ``<name>.json`` (or legacy ``<name>.pkl``)."""
    avatar_dir = Path(avatar_dir)
    json_path = avatar_dir / f"{name}.json"
    if json_path.is_file():
        try:
            raw = json.loads(_read_bounded(json_path).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UnsafeAssetError(f"{json_path} is not valid JSON") from exc
        return _validated(raw, json_path)

    legacy_path = avatar_dir / f"{name}.pkl"
    if not legacy_path.is_file():
        raise FileNotFoundError(json_path)
    coords = _validated(_restricted_unpickle(_read_bounded(legacy_path), legacy_path), legacy_path)
    try:
        save_coords(json_path, coords)
        logger.info("Converted legacy avatar coordinates %s to %s", legacy_path, json_path.name)
    except OSError as exc:
        # A read-only avatar keeps working; the restricted reader runs again next load.
        logger.warning("Could not write %s; keeping legacy coordinates: %s", json_path, exc)
    return coords


def save_coords(path: Path, coords: Sequence[Sequence[Any]]) -> None:
    """Atomically write face boxes as JSON."""
    path = Path(path)
    data = _validated(coords, path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _read_bounded(path: Path) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(MAX_COORDS_BYTES + 1)
    if len(data) > MAX_COORDS_BYTES:
        raise UnsafeAssetError(f"{path} is larger than {MAX_COORDS_BYTES} bytes")
    return data


def _validated(raw: Any, source: Path) -> Coords:
    if not isinstance(raw, (list, tuple)):
        raise UnsafeAssetError(f"{source}: expected a list of face boxes")
    boxes: Coords = []
    for index, box in enumerate(raw):
        if not isinstance(box, (list, tuple)) or len(box) != BOX_LENGTH:
            raise UnsafeAssetError(f"{source}: box {index} is not {BOX_LENGTH} numbers")
        boxes.append([_number(value, source, index) for value in box])
    return boxes


def _number(value: Any, source: Path, index: int):
    if isinstance(value, np.generic) and not isinstance(value, np.bool_):
        value = value.item()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnsafeAssetError(f"{source}: box {index} holds a non-numeric value")
    if isinstance(value, float) and not math.isfinite(value):
        raise UnsafeAssetError(f"{source}: box {index} holds a non-finite value")
    return value


# ------------------------------------------------------------ legacy pickles


class _DTypeSpec:
    """Stand-in for ``numpy.dtype`` that never runs NumPy's ``__setstate__``."""

    def __init__(self, spec: Any, align: Any = False, copy: Any = False):
        if not isinstance(spec, str) or spec not in _NUMERIC_DTYPES:
            raise UnsafeAssetError(f"legacy coordinates use unsupported dtype {spec!r}")
        self.spec = spec
        self.byte_order = "="

    def __setstate__(self, state: Any) -> None:
        # numpy.dtype state: (version, byteorder, subdtype, names, fields, ...)
        if (
            not isinstance(state, tuple)
            or len(state) < 5
            or state[1] not in _BYTE_ORDERS
            or any(part is not None for part in state[2:5])
        ):
            raise UnsafeAssetError("legacy coordinates use a structured dtype")
        self.byte_order = state[1]


def _numpy_scalar(dtype: Any, data: Any = None):
    if not isinstance(dtype, _DTypeSpec) or not isinstance(data, bytes):
        raise UnsafeAssetError("legacy coordinates hold a non-numeric NumPy scalar")
    resolved = np.dtype(dtype.spec).newbyteorder(dtype.byte_order)
    if len(data) != resolved.itemsize:
        raise UnsafeAssetError("legacy coordinates hold a malformed NumPy scalar")
    return np.frombuffer(data, dtype=resolved)[0].item()


_ALLOWED_GLOBALS = {
    ("numpy", "dtype"): _DTypeSpec,
    ("numpy.core.multiarray", "scalar"): _numpy_scalar,
    ("numpy._core.multiarray", "scalar"): _numpy_scalar,
}


class _CoordsUnpickler(pickle.Unpickler):
    """Rebuild only lists, tuples, ints, floats and numeric NumPy scalars.

    Every callable a pickle can invoke is resolved through ``find_class``; the
    two NumPy names are replaced by validating stand-ins, so no real NumPy or
    other constructor ever runs on attacker-chosen arguments.
    """

    def find_class(self, module: str, name: str):
        try:
            return _ALLOWED_GLOBALS[(module, name)]
        except KeyError:
            raise UnsafeAssetError(f"legacy coordinates reference {module}.{name}") from None

    def persistent_load(self, pid: Any):
        raise UnsafeAssetError("legacy coordinates use persistent references")


def _restricted_unpickle(data: bytes, source: Path) -> Any:
    try:
        return _CoordsUnpickler(io.BytesIO(data)).load()
    except UnsafeAssetError as exc:
        raise UnsafeAssetError(f"{source}: {exc}") from None
    except Exception as exc:
        raise UnsafeAssetError(f"{source}: unreadable legacy coordinates ({exc})") from exc


# ------------------------------------------------------------ tensors


def load_avatar_tensors(path: Path, map_location: Any = None) -> Any:
    """Load tensors saved with ``torch.save`` without unpickling arbitrary objects."""
    import torch

    return torch.load(path, map_location=map_location, weights_only=True)
