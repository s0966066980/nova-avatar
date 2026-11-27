# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Catalog of installed voice models (聲線模型) under ``models/tts/<id>/``.

A voice model is a set of Matcha-TTS weights that always speaks with one voice,
for both zh-TW and en-US. Voice models are not in git and are never downloaded;
they are copied onto each machine by hand. A directory is listed only when it
is complete:

- ``model.onnx``: the acoustic model;
- ``vocos-16khz-univ.onnx``: the vocoder (output is 16 kHz);
- ``lexicon.txt`` and ``tokens.txt``;
- ``voice.json``: the usage label, a UTF-8 JSON object::

      {
        "name": "曉臻（Edge 蒸餾）",
        "usage": "Development only",
        "languages": ["zh-TW", "en-US"],
        "source": "Distilled from Edge zh-TW-HsiaoChenNeural"
      }

  ``name`` is shown to users, ``usage`` is one of ``USAGE_LABELS``,
  ``languages`` lists the languages the voice speaks and ``source`` says where
  the weights came from. All four are required and non-empty.

The optional text-normalisation rules ``phone-zh.fst``, ``date-zh.fst`` and
``number-zh.fst`` are used when present. Incomplete or unlabelled directories
are skipped and the reason is logged; files and hidden directories under the
root are ignored. The directory name is the voice model's ID (``VOICE_MODEL_ID``),
so settings name a voice model by ID and never by path. The label is metadata
for people: the system shows it but does not block use (spec item 11).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from src.utils.logging import logger
from src.utils.paths import get_project_root

VOICE_MODELS_ROOT = get_project_root() / "models" / "tts"
LABEL_FILE = "voice.json"
ACOUSTIC_MODEL = "model.onnx"
VOCODER = "vocos-16khz-univ.onnx"
LEXICON = "lexicon.txt"
TOKENS = "tokens.txt"
REQUIRED_FILES = (ACOUSTIC_MODEL, VOCODER, LEXICON, TOKENS)
# Optional text-normalisation rules, in the order sherpa-onnx applies them.
RULE_FSTS = ("phone-zh.fst", "date-zh.fst", "number-zh.fst")
VOICE_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
# The usage classifications of spec item "使用限制". Voice models are never
# labelled commercially usable: every one so far derives from Edge audio or
# from a base model whose training data is undocumented.
USAGE_LABELS = ("Development only", "Research / Non-commercial")


@dataclass(frozen=True)
class VoiceModel:
    id: str
    name: str
    usage: str
    languages: tuple[str, ...]
    source: str
    acoustic_model: Path
    vocoder: Path
    lexicon: Path
    tokens: Path
    rule_fsts: tuple[Path, ...]


class _Incomplete(Exception):
    """Why a directory under the root is not a listable voice model."""


def list_voice_models(root: Path | None = None) -> list[VoiceModel]:
    """The complete, labelled voice models under ``root``, ordered by ID."""
    root = VOICE_MODELS_ROOT if root is None else root
    if not root.is_dir():
        return []
    models = []
    for model_dir in sorted(root.iterdir()):
        # Files beside the models and hidden directories are not candidates.
        if not model_dir.is_dir() or model_dir.name.startswith("."):
            continue
        try:
            models.append(_voice_model(model_dir))
        except _Incomplete as reason:
            logger.info("Voice model %s not listed: %s", model_dir.name, reason)
    return models


def _voice_model(model_dir: Path) -> VoiceModel:
    if not VOICE_MODEL_ID.fullmatch(model_dir.name):
        raise _Incomplete("directory name is not a valid voice-model ID")
    label_path = model_dir / LABEL_FILE
    if not label_path.is_file():
        raise _Incomplete(f"no usage label ({LABEL_FILE})")
    missing = [name for name in REQUIRED_FILES if not (model_dir / name).is_file()]
    if missing:
        raise _Incomplete(f"missing {', '.join(missing)}")
    try:
        label = json.loads(label_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Incomplete(f"unreadable {LABEL_FILE}: {exc}") from exc
    if not isinstance(label, dict):
        raise _Incomplete(f"{LABEL_FILE} is not a JSON object")
    name, usage, source = (_text(label, key) for key in ("name", "usage", "source"))
    if usage not in USAGE_LABELS:
        raise _Incomplete(f"{LABEL_FILE} usage {usage!r} is not one of {USAGE_LABELS}")
    languages = label.get("languages")
    if (
        not isinstance(languages, list)
        or not languages
        or not all(isinstance(lang, str) and lang.strip() for lang in languages)
    ):
        raise _Incomplete(f"{LABEL_FILE} languages must be a non-empty list of strings")
    return VoiceModel(
        id=model_dir.name,
        name=name,
        usage=usage,
        languages=tuple(languages),
        source=source,
        acoustic_model=model_dir / ACOUSTIC_MODEL,
        vocoder=model_dir / VOCODER,
        lexicon=model_dir / LEXICON,
        tokens=model_dir / TOKENS,
        rule_fsts=tuple(model_dir / name for name in RULE_FSTS if (model_dir / name).is_file()),
    )


def _text(label: dict, key: str) -> str:
    value = label.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _Incomplete(f"{LABEL_FILE} {key} must be a non-empty string")
    return value.strip()
