# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Per-model settings that sit beside a GGUF file (``<name>.model.json``).

llama.cpp lists every ``*.gguf`` in the model folder, so a text model needs no
setup. A model that can read images also needs its vision projector (a separate
GGUF), and a projector must only be attached to the model it was made for, so the
pairing is declared, never guessed from file names. The declaration is a small JSON
object next to the model, named after the model file without ``.gguf``::

    # Qwen3.5-VL-9B-Q4_K_M.model.json
    {"mmproj": "Qwen3.5-VL-9B-mmproj.gguf"}

``mmproj`` names a projector in the same folder, or is ``null`` to attach none.
The tested Gemma 4 E2B pairing is built in, so an existing install keeps its vision
without a descriptor; a descriptor beside that model overrides the built-in pairing.
A descriptor that cannot be used is reported and the model runs as text-only.
"""

from __future__ import annotations

import json
from pathlib import Path

from nova_core.utils.logging import logger

SIDECAR_SUFFIX = ".model.json"
KNOWN_KEYS = frozenset({"mmproj"})
# The pairing tested for the default model; used only when no descriptor exists.
BUILTIN_PROJECTORS = {"gemma-4-E2B_q4_0-it.gguf": "gemma-4-E2B-it-mmproj.gguf"}


def sidecar_path(gguf: Path) -> Path:
    """The descriptor of ``gguf``: same folder, ``<stem>.model.json``."""
    return gguf.parent / f"{gguf.stem}{SIDECAR_SUFFIX}"


def projector_for(gguf: Path) -> Path | None:
    """The vision projector to attach to ``gguf``, or ``None`` for a text-only model."""
    sidecar = sidecar_path(gguf)
    if not sidecar.is_file():
        name = BUILTIN_PROJECTORS.get(gguf.name)
        projector = gguf.parent / name if name else None
        return projector if projector is not None and projector.is_file() else None
    try:
        declared = _read_mmproj(sidecar)
    except ValueError as reason:
        logger.warning("Model descriptor %s not used, the model runs without vision: %s", sidecar.name, reason)
        return None
    if declared is None:
        return None
    projector = gguf.parent / declared
    if not projector.is_file():
        logger.warning("Model descriptor %s names %s, which is not in the folder; running without vision",
                       sidecar.name, declared)
        return None
    return projector


def _read_mmproj(sidecar: Path) -> str | None:
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("it is not a JSON object")
    unknown = sorted(set(data) - KNOWN_KEYS)
    if unknown:
        raise ValueError(f"unknown field(s): {', '.join(unknown)}")
    declared = data.get("mmproj")
    if declared is None:
        return None
    if not isinstance(declared, str) or Path(declared).name != declared or not declared.lower().endswith(".gguf"):
        raise ValueError("mmproj must be a .gguf file name in the same folder")
    return declared
