#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Compare Whisper and FunASR speed and accuracy on the first-audio fixtures.

Each fixture utterance from ``scripts/measure_first_audio.py`` (or a site
``--fixtures`` file) is synthesized in memory with Edge TTS, cut where the
stage VAD would end the turn, encoded as the voice session encodes it, and
recognized by each engine through the same ``transcribe`` call the voice
session times as its ``asr`` stage. Engines load one at a time.

Reports per engine and language: latency P50/P95 and the corpus error rate
(CER for zh-TW, WER for en-US; mixed text scores Chinese per character and
Latin words whole). ``error_rate`` ignores traditional/simplified script
differences; ``raw_error_rate`` counts them, since the subtitle shows the
recognized text. Audio is never stored (ADR 0004); fixture text is synthetic.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gc
import json
import re
import sys
import time
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np
import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.asr.base import asr_language
from src.server.reply_streaming.latency_baseline import (
    FIXTURES,
    LANGUAGES,
    LatencyFixture,
    fixtures_from_json,
    voiced_end_sample,
)
from src.server.reply_streaming.soak import percentile

SAMPLE_RATE = 16000
# The stage VAD ends a turn after 320 ms of silence (voice_session endpoint);
# the recognizer receives that silence too.
ENDPOINT_SILENCE_SECONDS = 0.32
METRICS = {"zh-TW": "CER", "en-US": "WER"}
# English sessions require Whisper (src/server/conversations.check_language_support).
APP_LANGUAGES = {"whisper": set(LANGUAGES), "funasr": {"zh-TW"}}

_TOKEN = re.compile(r"[㐀-鿿豈-﫿]|[a-z0-9]+(?:'[a-z0-9]+)*")


@lru_cache(maxsize=1)
def _to_simplified():
    from opencc import OpenCC

    return OpenCC("t2s")


def recognition_tokens(text: str, *, normalize_script: bool = True) -> list[str]:
    """Scoring units: Chinese characters and lowercase Latin words, no punctuation."""
    text = text.lower().replace("’", "'")
    if normalize_script:
        text = _to_simplified().convert(text)
    return _TOKEN.findall(text)


def _edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, start=1):
        current = [i]
        for j, hyp in enumerate(hypothesis, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ref != hyp)))
        previous = current
    return previous[-1]


def error_counts(reference: str, hypothesis: str, *, normalize_script: bool = True) -> tuple[int, int]:
    """(substitutions + insertions + deletions, reference length) in scoring units."""
    ref = recognition_tokens(reference, normalize_script=normalize_script)
    hyp = recognition_tokens(hypothesis, normalize_script=normalize_script)
    return _edit_distance(ref, hyp), len(ref)


def utterance_audio(samples: np.ndarray, *, sample_rate: int = SAMPLE_RATE,
                    endpoint_silence_seconds: float = ENDPOINT_SILENCE_SECONDS) -> np.ndarray:
    """The fixture as the VAD hands it over: voice plus the endpoint silence."""
    end = voiced_end_sample(samples) + int(round(endpoint_silence_seconds * sample_rate))
    return samples[:end]


def wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    buffer = BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def measure_engine(name: str, engine, fixtures: Sequence[LatencyFixture],
                   audio: Mapping[str, bytes], *, rounds: int,
                   clock: Callable[[], float] = time.perf_counter) -> list[dict]:
    """Time one ``transcribe`` call per fixture and round, as the voice session does.

    Engines with language options detect Chinese or English per utterance, as
    speech turns do; the detected language is scored against the fixture's.
    """
    samples = []
    language_options = getattr(engine, "supports_language_options", False) is True
    for round_index in range(1, rounds + 1):
        for fixture in fixtures:
            payload = audio[fixture.fixture_id]
            started = clock()
            if language_options:
                result = engine.transcribe(payload, language="auto")
            else:
                result = engine.transcribe(payload)
            seconds = clock() - started
            hypothesis = str(result.get("text", "")).strip()
            edits, length = error_counts(fixture.text, hypothesis)
            raw_edits, _ = error_counts(fixture.text, hypothesis, normalize_script=False)
            samples.append({
                "engine": name, "fixture_id": fixture.fixture_id,
                "language": fixture.language, "round": round_index,
                "seconds": seconds, "reference": fixture.text, "hypothesis": hypothesis,
                "edits": edits, "raw_edits": raw_edits, "reference_tokens": length,
                "expected_language": asr_language(fixture.language) if language_options else None,
                "detected_language": result.get("language"),
            })
    return samples


def _summary(samples: Iterable[Mapping]) -> dict:
    rows = list(samples)
    tokens = sum(row["reference_tokens"] for row in rows)
    seconds = [row["seconds"] for row in rows]
    detected = [row for row in rows if row.get("expected_language")]
    return {
        "samples": len(rows),
        "utterances": len({row["fixture_id"] for row in rows}),
        "latency_seconds": {"p50": percentile(seconds, 50), "p95": percentile(seconds, 95)},
        "error_rate": sum(row["edits"] for row in rows) / tokens if tokens else None,
        "raw_error_rate": sum(row["raw_edits"] for row in rows) / tokens if tokens else None,
        "language_accuracy": (
            sum(row["detected_language"] == row["expected_language"] for row in detected)
            / len(detected) if detected else None),
    }


def build_report(samples: Sequence[Mapping], *, engines: Mapping[str, Mapping],
                 environment: Mapping) -> dict:
    report_engines = {}
    for name, settings in engines.items():
        rows = [row for row in samples if row["engine"] == name]
        supported = APP_LANGUAGES.get(name, set(LANGUAGES))
        languages = {}
        for language in LANGUAGES:
            subset = [row for row in rows if row["language"] == language]
            if subset:
                languages[language] = {**_summary(subset), "metric": METRICS[language],
                                       "supported_in_app": language in supported}
        report_engines[name] = {
            "settings": dict(settings),
            "languages": languages,
            # Only languages a session can actually use with this engine.
            "all": _summary(row for row in rows if row["language"] in supported),
        }
    return {
        "environment": dict(environment),
        "definitions": {
            "latency_seconds": "一次 transcribe 呼叫（與語音輪次 asr 階段相同），暖機後",
            "error_rate": "語料層級：編輯距離總和 ÷ 參考長度總和；zh-TW 為 CER（中文逐字、英文字詞整體），"
                          "en-US 為 WER；忽略大小寫、標點與繁簡字形",
            "raw_error_rate": "同 error_rate，但繁簡字形不同也算錯（字幕直接顯示辨識文字）",
            "language_accuracy": "只在中英文間自動偵測時，偵測語言與錄音語系相符的比例；"
                                 "不支援語言選項的引擎為 null",
            "all": "僅計入此引擎在應用中可用的語系",
        },
        "engines": report_engines,
        "samples": [dict(row) for row in samples],
    }


async def synthesize_audio(fixtures: Sequence[LatencyFixture]) -> dict[str, bytes]:
    from scripts.measure_first_audio import FIXTURE_VOICES
    from scripts.run_voice_soak import synthesize_fixture

    audio = {}
    for fixture in fixtures:
        samples = await synthesize_fixture(fixture.text, FIXTURE_VOICES[fixture.language])
        audio[fixture.fixture_id] = wav_bytes(utterance_audio(samples))
    return audio


def _load_engine(name: str, args):
    from src.asr.factory import create_asr_engine
    from src.config.schema import Config

    config = Config()
    config.asr.type = name
    config.asr.device = args.device
    config.asr.output_script = "traditional-tw"
    model = args.whisper_model if name == "whisper" else args.funasr_model
    engine = create_asr_engine(name, config=config, model_size=model)
    started = time.perf_counter()
    engine.prewarm()
    return engine, time.perf_counter() - started


def _free_gpu_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def run(args) -> dict:
    fixtures = (fixtures_from_json(args.fixtures.read_text(encoding="utf-8"))
                if args.fixtures else FIXTURES)
    audio = asyncio.run(synthesize_audio(fixtures))
    samples: list[dict] = []
    settings: dict[str, dict] = {}
    for name in args.engines:
        engine, load_seconds = _load_engine(name, args)
        info = engine.get_info()
        settings[name] = {
            "model": info.get("model_size") or info.get("model_name"),
            "device": info.get("device"),
            "compute_type": info.get("compute_type"),
            "language": "auto, zh or en only" if name == "whisper" else "zh only",
            "beam_size": 1 if name == "whisper" else None,
            "input": "in-memory waveform" if name == "whisper" else "temp WAV file",
            "load_and_prewarm_seconds": round(load_seconds, 3),
        }
        rows = measure_engine(name, engine, fixtures, audio, rounds=args.rounds)
        samples.extend(rows)
        print(f"{name}: {len(rows)} recognitions", flush=True)
        # Engines run one at a time so both fit beside the live services.
        del engine
        _free_gpu_memory()
    return build_report(samples, engines=settings, environment={
        "measured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "gpu": args.gpu,
        "device": args.device,
        "input": "synthetic Edge TTS fixtures, cut at voice end + 320 ms, 16 kHz PCM16 WAV",
        "fixture_set": str(args.fixtures) if args.fixtures else "builtin",
        "rounds": str(args.rounds),
        "note": args.note,
    })


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engines", default="whisper,funasr",
                        type=lambda value: [item.strip() for item in value.split(",") if item.strip()])
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--funasr-model", default="paraformer-zh")
    parser.add_argument("--device", default="cuda", choices=("cuda", "cpu"))
    parser.add_argument("--rounds", type=int, default=3, help="recognitions per fixture after prewarm")
    parser.add_argument("--fixtures", type=Path, help="site fixture JSON replacing the builtin set")
    parser.add_argument("--gpu", default="NVIDIA GeForce RTX 4090")
    parser.add_argument("--note", default="", help="configuration note stored in the report")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / ".scratch" / "first-audio-latency"
                        / f"asr-comparison-{dt.date.today().isoformat()}.json")
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    unknown = set(args.engines) - set(APP_LANGUAGES)
    if not args.engines or unknown:
        parser.error(f"--engines must name whisper and/or funasr, got {args.engines}")
    return args


def main() -> int:
    args = parse_args()
    report = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, summary in report["engines"].items():
        for language, row in summary["languages"].items():
            note = "" if row["supported_in_app"] else " (not usable in app)"
            accuracy = row["language_accuracy"]
            detection = "" if accuracy is None else f" language_accuracy={accuracy:.3f}"
            print(f"{name} {language}: n={row['samples']} latency={row['latency_seconds']} "
                  f"{row['metric']}={row['error_rate']:.3f} raw={row['raw_error_rate']:.3f}"
                  f"{detection}{note}", flush=True)
    print(f"report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
