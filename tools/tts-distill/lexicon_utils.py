# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Shared bilingual lexicon builder and phonemizer helpers for Matcha-TTS."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

PAD_ID = 0
_ASCII_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_ASCII_OR_ZH_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[\u4e00-\u9fff]+|[,.;:!?，。；：！？—…]")

_PUNCTUATION_MAP = {
    "，": ",",
    "。": ".",
    "！": "!",
    "？": "?",
    "；": ";",
    "：": ":",
    "、": ",",
}

# Verified US-English IPA entries for single letters and Nova Avatar / Jetson
# domain terms whose phonemes all exist in dengcunqin/matcha_tts_zh_en_20251010/tokens.txt.
EXTRA_TECH_LEXICON: dict[str, tuple[str, ...]] = {
    "a": ("A",),
    "b": ("b", "ˈ", "i"),
    "c": ("s", "ˈ", "i"),
    "d": ("d", "ˈ", "i"),
    "e": ("ˈ", "i"),
    "f": ("ˈ", "ɛ", "f"),
    "g": ("ʤ", "ˈ", "i"),
    "h": ("ˈ", "A", "ʧ"),
    "i": ("ˈ", "I"),
    "j": ("ʤ", "ˈ", "A"),
    "k": ("k", "ˈ", "A"),
    "l": ("ˈ", "ɛ", "l"),
    "m": ("ˈ", "ɛ", "m"),
    "n": ("ˈ", "ɛ", "n"),
    "o": ("ˈ", "O"),
    "p": ("p", "ˈ", "i"),
    "q": ("k", "j", "ˈ", "u"),
    "r": ("ˈ", "ɑ", "ɹ"),
    "s": ("ˈ", "ɛ", "s"),
    "t": ("t", "ˈ", "i"),
    "u": ("j", "ˈ", "u"),
    "v": ("v", "ˈ", "i"),
    "w": ("d", "ˈ", "ʌ", "b", "ᵊ", "l", "j", "u"),
    "x": ("ˈ", "ɛ", "k", "s"),
    "y": ("w", "ˈ", "I"),
    "z": ("z", "ˈ", "i"),
    "ai": ("ˈ", "A", "ˌ", "I"),
    "api": ("ˈ", "A", "p", "ˈ", "i"),
    "asr": ("ˈ", "A", "ˈ", "ɛ", "s", "ˈ", "ɑ", "ɹ"),
    "tts": ("t", "ˈ", "i", "t", "ˈ", "i", "ˈ", "ɛ", "s"),
    "llm": ("ˈ", "ɛ", "l", "ˈ", "ɛ", "l", "ˈ", "ɛ", "m"),
    "cpu": ("s", "ˈ", "i", "p", "ˈ", "i", "j", "ˈ", "u"),
    "gpu": ("ʤ", "ˈ", "i", "p", "ˈ", "i", "j", "ˈ", "u"),
    "onnx": ("ˈ", "ɔ", "n", "ˌ", "ɛ", "k", "s"),
    "jetson": ("ʤ", "ˈ", "ɛ", "t", "s", "ə", "n"),
    "orin": ("ˈ", "ɔ", "ɹ", "ɪ", "n"),
    "musetalk": ("m", "j", "ˈ", "u", "z", "t", "ˈ", "ɔ", "k"),
    "matcha": ("m", "ˈ", "ɑ", "ʧ", "ə"),
    "whisper": ("w", "ˈ", "ɪ", "s", "p", "ɚ"),
    "webrtc": ("w", "ˈ", "ɛ", "b", "ˈ", "ɑ", "ɹ", "t", "ˈ", "i", "s", "ˈ", "i"),
    "rag": ("ɹ", "ˈ", "æ", "ɡ"),
    "gemma": ("ʤ", "ˈ", "ɛ", "m", "ə"),
    "nova": ("n", "ˈ", "O", "v", "ə"),
    "avatar": ("ˈ", "æ", "v", "ə", "t", "ˌ", "ɑ", "ɹ"),
    "fps": ("ˈ", "ɛ", "f", "p", "ˈ", "i", "ˈ", "ɛ", "s"),
    "vad": ("v", "ˈ", "æ", "d"),
}


def load_tokens(tokens_path: Path) -> dict[str, int]:
    """Load `token id` pairs from sherpa-onnx tokens.txt (1..2190)."""
    mapping: dict[str, int] = {}
    for line in tokens_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        tok, idx_str = line.rsplit(" ", 1)
        mapping[tok] = int(idx_str)
    return mapping


def _parse_lexicon_file(path: Path) -> Iterable[tuple[str, list[str]]]:
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            parts = raw_line.strip().split()
            if len(parts) >= 2:
                yield parts[0], parts[1:]


def load_lexicon_dict(lexicon_path: Path) -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {}
    for word, phons in _parse_lexicon_file(lexicon_path):
        entries.setdefault(word, phons)
    return entries


def build_merged_lexicon(
    zh_lexicon_path: Path,
    tokens_path: Path,
    *,
    en_lexicon_path: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, list[str]]:
    """Merge Chinese pinyin lexicon, US-English IPA lexicon, and tech terms."""
    valid_tokens = set(load_tokens(tokens_path).keys())
    merged: dict[str, list[str]] = {}

    sources: list[Iterable[tuple[str, list[str]]]] = [_parse_lexicon_file(zh_lexicon_path)]
    if en_lexicon_path is not None and en_lexicon_path.is_file():
        sources.append(_parse_lexicon_file(en_lexicon_path))

    for source in sources:
        for word, phons in source:
            if word not in merged and all(p in valid_tokens for p in phons):
                merged[word] = list(phons)

    for word, phons in EXTRA_TECH_LEXICON.items():
        if all(p in valid_tokens for p in phons):
            merged.setdefault(word, list(phons))

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as handle:
            for word, phons in merged.items():
                handle.write(f"{word} {' '.join(phons)}\n")

    return merged


def _build_t2s():
    try:
        from opencc import OpenCC
    except ImportError:
        return None
    return OpenCC("t2s")


def text_to_phoneme_ids(
    text: str,
    word_lexicon: dict[str, list[str]],
    tok_to_id: dict[str, int],
    *,
    converter=None,
) -> list[int]:
    """Convert bilingual text into 1-indexed Matcha phoneme token IDs matching sherpa-onnx."""
    if converter is None:
        converter = _build_t2s()
    converted = converter.convert(text) if converter is not None else text

    phonemes: list[str] = []
    space_tok = " " if " " in tok_to_id else None

    for chunk in _ASCII_OR_ZH_RE.findall(converted):
        mapped_punct = _PUNCTUATION_MAP.get(chunk, chunk)
        if mapped_punct in tok_to_id:
            phonemes.append(mapped_punct)
            continue
        if _ASCII_WORD_RE.fullmatch(chunk):
            parts = [p for p in _CAMEL_BOUNDARY_RE.split(chunk) if p]
            for piece in (parts if len(parts) > 1 else [chunk]):
                low = piece.lower()
                if phonemes and space_tok is not None and phonemes[-1] != space_tok:
                    phonemes.append(space_tok)
                if low in word_lexicon:
                    phonemes.extend(word_lexicon[low])
                elif all(c in word_lexicon for c in low):
                    for ch in low:
                        phonemes.extend(word_lexicon[ch])
            continue
        # Greedy longest match over CJK substring
        i = 0
        n = len(chunk)
        while i < n:
            matched = False
            for end in range(min(n, i + 4), i, -1):
                sub = chunk[i:end]
                if sub in word_lexicon:
                    phonemes.extend(word_lexicon[sub])
                    i = end
                    matched = True
                    break
            if not matched:
                i += 1

    if not phonemes:
        return []
    return [tok_to_id[p] for p in phonemes if p in tok_to_id]
