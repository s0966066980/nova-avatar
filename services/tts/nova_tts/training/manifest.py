# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The training manifest: prepared audio paired with the token IDs of its transcript.

Training text comes only from ``Corpus.training_lines()``: the confirmed lines of a
trainable corpus, already digit-expanded by ``numerals.normalize_digits``. This module
normalises that text the way the Matcha engine does before synthesis
(``normalize_matcha_text``: Simplified-Chinese lexicon spelling, English words as the
lexicon spells them) and tokenises it with the training lexicon helpers in
``tools/tts-distill/lexicon_utils.py`` (loaded by path, because the folder name is not a
package name). A digit reaching the tokeniser is an error, never skipped, because the
audio would no longer match the tokens.

The tokeniser runs here, in the application's environment (it needs OpenCC); the
training script only reads token IDs. The lexicon used is the base lexicon merged with
the technical terms of ``lexicon_utils`` and restricted to tokens the base model has; the
same file is installed with the exported voice model.

A line that cannot be used is skipped and reported, and training goes on without it:
``no_audio`` (its prepared audio is missing), ``no_tokens`` (nothing in the text is in the
lexicon) or ``unknown_token`` (a token outside the base model's embedding table).
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import ModuleType

from nova_tts.engines.matcha import normalize_matcha_text
from nova_tts.training.corpus import Line
from nova_tts.training.preparation import prepared_path
from nova_core.utils.paths import get_project_root

TOOLS_DIR = get_project_root() / "tools" / "tts-distill"
BASE_VOCAB = 2190  # rows of the base model's embedding table; valid token IDs are below this
MANIFEST_FILE = "manifest.jsonl"
LEXICON_FILE = "lexicon.txt"

SKIP_NO_AUDIO = "no_audio"
SKIP_NO_TOKENS = "no_tokens"
SKIP_UNKNOWN_TOKEN = "unknown_token"


@dataclass(frozen=True)
class ManifestResult:
    manifest: Path
    lexicon: Path
    written: int
    skipped: tuple[tuple[str, str], ...]  # (line id, reason)


@cache
def load_lexicon_utils(tools_dir: Path = TOOLS_DIR) -> ModuleType:
    spec = importlib.util.spec_from_file_location("nova_matcha_lexicon_utils", tools_dir / "lexicon_utils.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"lexicon_utils.py not found in {tools_dir}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_manifest(
    lines: Sequence[tuple[Line, str]],
    workdir: Path,
    base_assets: Path,
    *,
    tools_dir: Path = TOOLS_DIR,
    vocab: int = BASE_VOCAB,
    converter=None,
) -> ManifestResult:
    """Write ``workdir/manifest.jsonl`` and ``workdir/lexicon.txt`` for ``lines`` (line, expanded text)."""
    utils = load_lexicon_utils(tools_dir)
    tokens_path = base_assets / "tokens.txt"
    tok_to_id = utils.load_tokens(tokens_path)
    lexicon_path = workdir / LEXICON_FILE
    lexicon = utils.build_merged_lexicon(base_assets / "lexicon.txt", tokens_path, out_path=lexicon_path)
    if converter is None:
        from opencc import OpenCC

        converter = OpenCC("t2s")
    words = set(lexicon)

    rows: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for line, text in lines:
        wav = prepared_path(workdir, line.id)
        if not wav.is_file():
            skipped.append((line.id, SKIP_NO_AUDIO))
            continue
        spoken = normalize_matcha_text(text, lexicon_words=words, converter=converter)
        # An identity converter: the text is already in the lexicon's script.
        ids = utils.text_to_phoneme_ids(spoken, lexicon, tok_to_id, converter=_Identity())
        if not ids:
            skipped.append((line.id, SKIP_NO_TOKENS))
        elif max(ids) >= vocab:
            skipped.append((line.id, SKIP_UNKNOWN_TOKEN))
        else:
            rows.append({"wav": str(wav), "phoneme_ids": ids, "text": spoken})

    manifest = workdir / MANIFEST_FILE
    manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return ManifestResult(manifest, lexicon_path, len(rows), tuple(skipped))


class _Identity:
    @staticmethod
    def convert(text: str) -> str:
        return text
