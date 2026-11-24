# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Repeated-syllable benchmark for Matcha voice models.

Synthesises a fixed set of sentences with sherpa-onnx on the CPU, transcribes
each synthesis with Whisper (also on the CPU) and counts the syllables heard
twice in a row that the sentence does not contain. The rule is that of the
2026-11-24 diagnosis (``.scratch/matcha-training/evidence/2026-11-24-diagnosis``):
a token of one or two characters that repeats back to back in the transcript
but not in the reference text is a repeat, and one repeat flags the run.

Usage, from the repository root with the project environment::

    uv run --no-sync python tools/tts-bench/repeated_syllables.py \
        models/tts/zh-tw-hsiaochen-edge --output /tmp/hsiaochen.json

The argument is a voice-model directory: ``model.onnx`` (or the base
checkpoint's ``model-steps-3.onnx``), ``vocos-16khz-univ.onnx``,
``lexicon.txt``, ``tokens.txt`` and optional ``*-zh.fst`` rules; ``voice.json``
is not needed, so the base model can be compared with voice models.

Whisper defaults to ``models/whisper-large-v3-turbo`` (the model the diagnosis
used, so the numbers stay comparable). It runs from that local directory with
int8 weights, offline; a missing model stops the run. ``--whisper-model`` takes
another local directory or a size name that is already in the Hugging Face
cache (never downloaded). The GPU is hidden with ``CUDA_VISIBLE_DEVICES=``
before any model is created, so the benchmark is safe beside a running stage.
"""

from __future__ import annotations

import argparse
import collections
import functools
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WHISPER_MODEL = ROOT / "models" / "whisper-large-v3-turbo"
DEFAULT_REPEATS = 3
THREADS = 4
SAMPLE_RATE = 16000
SENTENCES_FILE = Path(__file__).with_name("sentences.json")
# A voice model's acoustic model is model.onnx; the base checkpoint ships as model-steps-3.onnx.
ACOUSTIC_MODEL_NAMES = ("model.onnx", "model-steps-3.onnx")
VOCODER = "vocos-16khz-univ.onnx"
RULE_FSTS = ("phone-zh.fst", "date-zh.fst", "number-zh.fst")


class BenchmarkError(RuntimeError):
    """A precondition of the benchmark is not met; the run stops instead of skipping."""


class ModelFiles(NamedTuple):
    acoustic_model: Path
    vocoder: Path
    lexicon: Path
    tokens: Path
    rule_fsts: tuple[Path, ...]

_PUNCTUATION = re.compile(r"[\s，。？！、,.?!$:：;；'\"]")
_ADJACENT_REPEAT = re.compile(r"(.{1,2}?)\1")


@functools.lru_cache(maxsize=1)
def _traditional_to_simplified():
    from opencc import OpenCC

    return OpenCC("t2s").convert


def _normalise(text: str, to_simplified) -> str:
    return _PUNCTUATION.sub("", to_simplified(text)).lower()


def _repeat_counts(text: str) -> collections.Counter:
    return collections.Counter(match.group(1) for match in _ADJACENT_REPEAT.finditer(text))


def repeated_tokens(reference: str, hypothesis: str, to_simplified=None) -> list[str]:
    """Adjacent repeats the transcript has and the reference text does not."""
    if to_simplified is None:
        to_simplified = _traditional_to_simplified()
    heard = _repeat_counts(_normalise(hypothesis, to_simplified))
    meant = _repeat_counts(_normalise(reference, to_simplified))
    return sorted(
        token for token in heard
        if token not in meant and not token.isdigit() and not token.isascii()
    )


class Transcript(NamedTuple):
    text: str
    words: list[tuple[str, float, float]]


def _run_record(reference: str, samples, transcript: Transcript, index: int) -> dict:
    tokens = repeated_tokens(reference, transcript.text)
    return {
        "run": index,
        "hypothesis": transcript.text,
        "words": [[word, start, end] for word, start, end in transcript.words],
        "repeated_tokens": tokens,
        "flagged": bool(tokens),
        "duration": round(len(samples) / SAMPLE_RATE, 2),
    }


def _sentence_record(synthesise, transcribe, sentence: dict, repeats: int) -> dict:
    runs = []
    for index in range(repeats):
        samples = synthesise(sentence["text"])
        runs.append(_run_record(sentence["text"], samples, transcribe(samples), index))
    return {
        "id": sentence["id"],
        "text": sentence["text"],
        "runs": runs,
        "flagged_runs": sum(run["flagged"] for run in runs),
        "repeated_tokens": sorted({token for run in runs for token in run["repeated_tokens"]}),
        "durations": [run["duration"] for run in runs],
    }


def run_benchmark(synthesise, transcribe, sentence_sets: dict[str, list[dict]], repeats: int) -> dict:
    """Synthesise every sentence ``repeats`` times and flag the repeated syllables heard.

    ``synthesise(text)`` returns 16 kHz mono float samples and ``transcribe(samples)``
    a ``Transcript``; both are injected so the benchmark needs no model to test.
    """
    sets = {}
    for name, sentences in sentence_sets.items():
        records = [_sentence_record(synthesise, transcribe, sentence, repeats) for sentence in sentences]
        sets[name] = {
            "sentences": records,
            "flagged_runs": sum(record["flagged_runs"] for record in records),
            "total_runs": sum(len(record["runs"]) for record in records),
        }
    return {"repeats": repeats, "sets": sets}


def load_sentences(path: Path = SENTENCES_FILE) -> dict[str, list[dict]]:
    return json.loads(path.read_text(encoding="utf-8"))


def locate_model_files(directory: Path) -> ModelFiles:
    """The files sherpa-onnx needs from a voice-model directory; ``voice.json`` is not required."""
    acoustic = next((directory / name for name in ACOUSTIC_MODEL_NAMES if (directory / name).is_file()), None)
    if acoustic is None:
        raise BenchmarkError(f"{directory}: no acoustic model ({' or '.join(ACOUSTIC_MODEL_NAMES)})")
    required = {name: directory / name for name in (VOCODER, "lexicon.txt", "tokens.txt")}
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise BenchmarkError(f"{directory}: missing {', '.join(missing)}")
    return ModelFiles(
        acoustic_model=acoustic,
        vocoder=required[VOCODER],
        lexicon=required["lexicon.txt"],
        tokens=required["tokens.txt"],
        rule_fsts=tuple(directory / name for name in RULE_FSTS if (directory / name).is_file()),
    )


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def summary_line(directory: Path, sha256: str, report: dict) -> str:
    sets = report["sets"]

    def ratio(name: str) -> str:
        return f"{sets[name]['flagged_runs']}/{sets[name]['total_runs']}"

    return f"model={directory} sha256={sha256} repeat-prone={ratio('repeat_prone')} clean={ratio('clean')}"


def make_sherpa_synthesiser(files: ModelFiles) -> Callable:
    """A ``synthesise(text)`` configured like ``src/tts/engines/matcha.py``, on the CPU."""
    sys.path.insert(0, str(ROOT))
    import numpy as np
    import sherpa_onnx
    from opencc import OpenCC

    from src.tts.engines.matcha import (
        LENGTH_SCALE,
        NOISE_SCALE,
        PEAK,
        load_lexicon_words,
        normalize_matcha_text,
    )

    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=str(files.acoustic_model),
                vocoder=str(files.vocoder),
                lexicon=str(files.lexicon),
                tokens=str(files.tokens),
                noise_scale=NOISE_SCALE,
                length_scale=LENGTH_SCALE,
            ),
            num_threads=THREADS,
            provider="cpu",
            debug=False,
        ),
        rule_fsts=",".join(str(path) for path in files.rule_fsts),
        max_num_sentences=1,
    )
    # sherpa-onnx ends the process on an invalid configuration; check it first.
    if not config.validate():
        raise BenchmarkError(f"sherpa-onnx cannot load {files.acoustic_model.parent}")
    tts = sherpa_onnx.OfflineTts(config)
    lexicon_words = load_lexicon_words(files.lexicon)
    converter = OpenCC("t2s")

    def synthesise(text: str):
        spoken = normalize_matcha_text(text, lexicon_words=lexicon_words, converter=converter)
        generated = tts.generate(spoken, sid=0, speed=1.0)
        if generated.sample_rate != SAMPLE_RATE:
            raise BenchmarkError(f"expected {SAMPLE_RATE} Hz audio, got {generated.sample_rate} Hz")
        samples = np.asarray(generated.samples, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        return samples * (PEAK / peak) if peak > PEAK else samples

    return synthesise


def make_whisper_transcriber(whisper_model: str) -> Callable:
    """A ``transcribe(samples)`` using faster-whisper on the CPU, offline."""
    path = Path(whisper_model)
    is_path = os.sep in whisper_model or whisper_model.startswith(".") or path.exists()
    if is_path and not (path / "model.bin").is_file():
        raise BenchmarkError(f"Whisper model not found at {path} (no model.bin); the benchmark does not skip")
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(
            whisper_model, device="cpu", compute_type="int8", cpu_threads=THREADS, local_files_only=True
        )
    except Exception as error:  # faster-whisper raises several types for an absent cache entry
        raise BenchmarkError(f"Whisper model {whisper_model!r} cannot be loaded offline: {error}") from error

    def transcribe(samples) -> Transcript:
        segments, _info = model.transcribe(
            samples,
            language="zh",
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            word_timestamps=True,
        )
        segments = list(segments)
        words = [(w.word, round(w.start, 2), round(w.end, 2)) for segment in segments for w in segment.words]
        return Transcript("".join(segment.text for segment in segments), words)

    return transcribe


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Count repeated syllables in a Matcha voice model's speech.")
    parser.add_argument("model_dir", type=Path, help="voice-model directory (voice.json not required)")
    parser.add_argument("--output", type=Path, required=True, help="where to write the per-sentence JSON")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="syntheses per sentence (default 3)")
    parser.add_argument(
        "--whisper-model",
        default=str(DEFAULT_WHISPER_MODEL),
        help="local faster-whisper directory or a cached size name (default: models/whisper-large-v3-turbo)",
    )
    args = parser.parse_args(argv)
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    return args


def main(
    argv: list[str] | None = None,
    make_synthesiser: Callable = make_sherpa_synthesiser,
    make_transcriber: Callable = make_whisper_transcriber,
) -> int:
    args = parse_args(argv)
    # Before any model exists: the stage owns the GPU, the benchmark never touches it.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    started = time.perf_counter()
    try:
        files = locate_model_files(args.model_dir)
        transcribe = make_transcriber(args.whisper_model)
        synthesise = make_synthesiser(files)
        report = run_benchmark(synthesise, transcribe, load_sentences(), args.repeats)
    except BenchmarkError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    sha256 = file_sha256(files.acoustic_model)
    report.update(
        model_dir=str(args.model_dir),
        acoustic_model=files.acoustic_model.name,
        acoustic_model_sha256=sha256,
        whisper_model=args.whisper_model,
        elapsed_seconds=round(time.perf_counter() - started, 1),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary_line(args.model_dir, sha256, report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
