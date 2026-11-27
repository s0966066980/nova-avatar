# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Writing a trained voice model into the catalog (``models/tts/<id>/``).

"Export" in this project means only this step (spec decision 14): the bundle stays on
this machine, in the directory ``src.tts.voice_models`` lists; no route offers a
download, and moving a voice model to another machine is a manual copy by the
administrator.

``install_voice_model`` is atomic for readers: the bundle is copied into a hidden
sibling directory (ignored by the catalog) and renamed into place, so a half-written
model is never listed, and an existing directory is never replaced. ``voice.json``
carries the usage label computed by the corpus (``Corpus.usage_label``). IDs are
generated here, never taken from a request.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import unicodedata
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from src.tts.voice_models import (
    LABEL_FILE,
    REQUIRED_FILES,
    USAGE_LABELS,
    VOICE_MODEL_ID,
    VOICE_MODELS_ROOT,
    list_voice_models,
)
from src.utils.logging import logger

LANGUAGES = ["zh-TW", "en-US"]
MAX_NAME_CHARS = 40
BASE_MODEL = "dengcunqin/matcha_tts_zh_en_20251010"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class BundleError(ValueError):
    """A problem the administrator can act on; ``status`` is the HTTP status a route should use."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _fold(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip().casefold()


def check_model_name(name: object, existing_names: Iterable[str]) -> str:
    """The cleaned name: required, at most 40 characters, not already used by a voice model."""
    if not isinstance(name, str) or not name.strip():
        raise BundleError("聲線模型名稱必填")
    cleaned = " ".join(name.split())
    if _CONTROL.search(name):
        raise BundleError("聲線模型名稱不可含控制字元")
    if len(cleaned) > MAX_NAME_CHARS:
        raise BundleError(f"聲線模型名稱最多 {MAX_NAME_CHARS} 字")
    if _fold(cleaned) in {_fold(existing) for existing in existing_names}:
        raise BundleError("已有同名的聲線模型，請換一個名稱", status=409)
    return cleaned


def new_model_id(existing_ids: Iterable[str], now: datetime | None = None) -> str:
    """A server-generated, catalog-valid ID that no existing directory uses."""
    taken = set(existing_ids)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M")
    while True:
        candidate = f"trained-{stamp}-{secrets.token_hex(2)}"
        if candidate not in taken and VOICE_MODEL_ID.fullmatch(candidate):
            return candidate


def source_description(corpus_source: str, detail: str = "") -> str:
    text = f"Fine-tuned from {BASE_MODEL}; corpus source: {corpus_source}"
    return f"{text} ({detail})" if detail else text


def install_voice_model(
    staging: Path,
    voice_id: str,
    *,
    name: str,
    usage: str,
    source: str,
    root: Path | None = None,
) -> Path:
    """Install the bundle in ``staging`` as ``<root>/<voice_id>/`` and return that directory."""
    root = VOICE_MODELS_ROOT if root is None else root
    if not VOICE_MODEL_ID.fullmatch(voice_id):
        raise BundleError("聲線模型 ID 不合規則", status=500)
    if usage not in USAGE_LABELS:
        raise BundleError("使用限制標示不明", status=500)
    missing = [file for file in REQUIRED_FILES if not (staging / file).is_file()]
    if missing:
        raise BundleError(f"匯出的聲線模型缺少 {', '.join(missing)}", status=500)

    target = root / voice_id
    if target.exists():
        raise BundleError("聲線模型 ID 已存在", status=409)
    root.mkdir(parents=True, exist_ok=True)
    partial = root / f".installing-{voice_id}"
    shutil.rmtree(partial, ignore_errors=True)
    try:
        shutil.copytree(staging, partial)
        label = {"name": name, "usage": usage, "languages": LANGUAGES, "source": source}
        (partial / LABEL_FILE).write_text(json.dumps(label, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        partial.rename(target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    if all(model.id != voice_id for model in list_voice_models(root)):
        shutil.rmtree(target, ignore_errors=True)
        raise BundleError("寫入後聲線模型沒有出現在清單中", status=500)
    logger.info("Installed voice model %s (%s, %s)", voice_id, name, usage)
    return target
