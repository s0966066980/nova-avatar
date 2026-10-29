#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""TTS bake-off (issue 10): BreezyVoice vs Qwen3-TTS vs Fun-CosyVoice3.

Every engine runs behind the owned zero-shot HTTP contract
(``GET /health`` with ``sample_rate``; ``POST /inference_zero_shot`` taking
``tts_text``, ``prompt_text``, ``prompt_wav`` and returning raw PCM16):
``scripts/cosyvoice_fastapi_server.py`` serves BreezyVoice and Fun-CosyVoice3,
``scripts/qwen3_tts_server.py`` serves Qwen3-TTS. One server runs at a time.

Subcommands:

- ``vram``: print GPU memory in use; run before starting a server for the baseline.
- ``run``: against one running server, time the first fragment (~15 字) cold,
  warm and while an LLM streams; sample VRAM through nvidia-smi; synthesize the
  zh-TW and en-US sets and repeat them up to the stability count; save WAVs.
- ``score``: after the servers are stopped, recognize the saved WAVs with
  Whisper and score error rate, truncation and hallucination.
- ``report``: merge runs into ``bakeoff.json`` and a static listening page.
- ``soak``: the long stability run (8 h by default), streaming JSON lines.

Generated audio stays under ``.scratch/first-audio-latency/tts-bakeoff/runs/``,
which git ignores. Synthesized speech is synthetic text only (ADR 0004).
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

import numpy as np
import requests
import soundfile as sf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BAKEOFF_DIR = PROJECT_ROOT / ".scratch" / "first-audio-latency" / "tts-bakeoff"
DEFAULT_SENTENCES = BAKEOFF_DIR / "sentences.json"
LANGUAGES = ("zh-TW", "en-US")

_COUNTED = re.compile(r"[㐀-鿿豈-﫿A-Za-z0-9]")


def fragment_length(text: str) -> int:
    """Characters a listener hears: CJK, Latin letters and digits, no punctuation."""
    return len(_COUNTED.findall(text))


@dataclasses.dataclass(frozen=True)
class Sentence:
    sentence_id: str
    language: str
    category: str
    text: str
    focus: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"id": self.sentence_id, "language": self.language, "category": self.category,
                "text": self.text, "focus": list(self.focus), "alternatives": list(self.alternatives)}


@dataclasses.dataclass(frozen=True)
class SentenceSets:
    first_fragments: tuple[Sentence, ...]
    sentences: tuple[Sentence, ...]

    def corpus(self, language: str) -> list[Sentence]:
        return [item for item in self.sentences if item.language == language]

    def all_items(self) -> list[Sentence]:
        return [*self.first_fragments, *self.sentences]


def _sentence(raw: dict, language: str, category: str | None = None) -> Sentence:
    return Sentence(
        sentence_id=str(raw["id"]), language=language,
        category=category or str(raw["category"]), text=str(raw["text"]),
        focus=tuple(raw.get("focus", ())), alternatives=tuple(raw.get("alternatives", ())))


def load_sentence_sets(path: Path) -> SentenceSets:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fragments = tuple(_sentence(raw, "zh-TW", "first-fragment") for raw in data["first_fragments"])
    sentences = tuple(_sentence(raw, language) for language in LANGUAGES for raw in data.get(language, ()))
    ids = [item.sentence_id for item in (*fragments, *sentences)]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate sentence ids: {duplicates}")
    return SentenceSets(fragments, sentences)


# Language names the Qwen3-TTS server expects; the CosyVoice server ignores the field.
SERVER_LANGUAGE = {"zh-TW": "Chinese", "en-US": "English"}


@dataclasses.dataclass
class SynthesisResult:
    ok: bool
    first_audio_seconds: float | None
    total_seconds: float
    samples: np.ndarray
    sample_rate: int
    error: str = ""

    @property
    def audio_seconds(self) -> float:
        return self.samples.size / self.sample_rate if self.sample_rate else 0.0


class ZeroShotClient:
    """One engine behind the owned ``/inference_zero_shot`` contract.

    ``first_audio_seconds`` runs from sending the request to the first PCM
    bytes, as the app's ``first audio:`` log line does; ``total_seconds`` to
    the last byte (for non-streaming BreezyVoice the two are close).
    """

    def __init__(self, url: str, prompt_wav: Path, prompt_text: str, *,
                 session: requests.Session | None = None, timeout: float = 120.0,
                 clock: Callable[[], float] = time.perf_counter):
        self.url = url.rstrip("/")
        self.prompt_bytes = Path(prompt_wav).read_bytes()
        self.prompt_text = prompt_text
        self.session = session or requests.Session()
        self.timeout = timeout
        self.clock = clock
        self.family = ""
        self.sample_rate = 0

    def health(self) -> dict:
        response = self.session.get(f"{self.url}/health", timeout=10)
        response.raise_for_status()
        info = response.json()
        self.family = str(info.get("family", ""))
        self.sample_rate = int(info["sample_rate"])
        return info

    def _prompt_text(self) -> str:
        from src.tts.engines.cosyvoice import CosyVoiceTTS

        # The same prompt text the app sends (Fun-CosyVoice3 needs its prefix).
        return CosyVoiceTTS._zero_shot_request("", self.prompt_text, self.family)[1]["prompt_text"]

    def synthesize(self, text: str, language: str) -> SynthesisResult:
        if not self.sample_rate:
            self.health()
        data = {"tts_text": text, "prompt_text": self._prompt_text(),
                "language": SERVER_LANGUAGE.get(language, "Auto")}
        files = {"prompt_wav": ("prompt.wav", self.prompt_bytes, "application/octet-stream")}
        started = self.clock()
        first: float | None = None
        payload = bytearray()
        try:
            with self.session.post(f"{self.url}/inference_zero_shot", data=data, files=files,
                                   stream=True, timeout=(5, self.timeout)) as response:
                if response.status_code != 200:
                    detail = response.text[:300]
                    return SynthesisResult(False, None, self.clock() - started, _EMPTY,
                                           self.sample_rate, f"HTTP {response.status_code}: {detail}")
                for chunk in response.iter_content(chunk_size=None):
                    if not chunk:
                        continue
                    if first is None:
                        first = self.clock() - started
                    payload.extend(chunk)
        except requests.RequestException as exc:
            return SynthesisResult(False, first, self.clock() - started, _EMPTY,
                                   self.sample_rate, f"{type(exc).__name__}: {exc}")
        total = self.clock() - started
        usable = len(payload) - len(payload) % 2
        samples = np.frombuffer(bytes(payload[:usable]), dtype=np.int16).copy()
        if not samples.size:
            return SynthesisResult(False, first, total, samples, self.sample_rate, "no audio")
        return SynthesisResult(True, first, total, samples, self.sample_rate)


_EMPTY = np.zeros(0, dtype=np.int16)


# --- VRAM --------------------------------------------------------------------


def _run_command(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=10).stdout


class NvidiaSmi:
    """GPU memory in MiB, read through nvidia-smi (no CUDA context of our own)."""

    def __init__(self, executable: str = "nvidia-smi", gpu_index: int = 0,
                 runner: Callable[[list[str]], str] = _run_command):
        self.executable, self.gpu_index, self.runner = executable, gpu_index, runner

    def gpu_used_mib(self) -> int:
        output = self.runner([self.executable, f"--id={self.gpu_index}", "--query-gpu=memory.used",
                              "--format=csv,noheader,nounits"])
        return int(output.strip().splitlines()[0])

    def process_used_mib(self, pid: int) -> int | None:
        output = self.runner([self.executable, f"--id={self.gpu_index}",
                              "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"])
        for line in output.strip().splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) == 2 and fields[0] == str(pid):
                return int(fields[1])
        return None


class VramSampler:
    """Peak GPU memory while a phase runs, against a baseline taken before the server started."""

    def __init__(self, probe: NvidiaSmi, *, server_pid: int | None, baseline_mib: int | None,
                 interval: float = 1.0):
        self.probe, self.server_pid, self.baseline_mib = probe, server_pid, baseline_mib
        self.interval = interval
        self.gpu: list[int] = []
        self.process: list[int] = []
        self.errors: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self) -> None:
        try:
            self.gpu.append(self.probe.gpu_used_mib())
            if self.server_pid is not None:
                used = self.probe.process_used_mib(self.server_pid)
                if used is not None:
                    self.process.append(used)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
            if len(self.errors) < 5:
                self.errors.append(f"{type(exc).__name__}: {exc}")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread = threading.Thread(target=self._loop, name="vram-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
        self.sample()

    def summary(self) -> dict[str, Any]:
        peak = max(self.gpu) if self.gpu else None
        return {
            "baseline_mib": self.baseline_mib,
            "first_sample_mib": self.gpu[0] if self.gpu else None,
            "peak_mib": peak,
            "delta_peak_mib": peak - self.baseline_mib if peak is not None and self.baseline_mib is not None else None,
            "server_pid": self.server_pid,
            "server_process_peak_mib": max(self.process) if self.process else None,
            "samples": len(self.gpu),
            "errors": list(self.errors),
        }


# --- Scoring -----------------------------------------------------------------

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"萬": 10_000, "万": 10_000, "億": 100_000_000, "亿": 100_000_000}
_CN_START = "".join([*_CN_DIGITS, "十"])
_CN_ANY = "".join([*_CN_DIGITS, *_CN_UNITS, *_CN_BIG])
# A number: Arabic digits or Chinese numerals, mixed as Whisper writes them (3萬2千9百).
_NUMERAL = re.compile(f"(?:\\d+|[{_CN_START}])(?:\\d+|[{_CN_ANY}])*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3})")


def _numeral_value(run: str) -> str:
    pieces = re.findall(r"\d+|.", run)
    if not any(piece in _CN_UNITS or piece in _CN_BIG for piece in pieces):
        # Read digit by digit: 二零二六, 一二三四, 2026.
        return "".join(piece if piece.isdigit() else str(_CN_DIGITS[piece]) for piece in pieces)
    total = section = number = 0
    for piece in pieces:
        if piece.isdigit():
            number = int(piece)
        elif piece in _CN_DIGITS:
            number = _CN_DIGITS[piece]
        elif piece in _CN_UNITS:
            section += (number or 1) * _CN_UNITS[piece]
            number = 0
        else:
            total += (section + number) * _CN_BIG[piece]
            section = number = 0
    return str(total + section + number)


def normalize_numbers(text: str) -> str:
    """Spoken (三萬兩千九百, 二零二六), written (32,900, 2026) and mixed numbers alike."""
    return _NUMERAL.sub(lambda match: _numeral_value(match.group()), _THOUSANDS.sub("", text))


def scoring_tokens(text: str) -> list[str]:
    """compare_asr scoring units after number normalization (script-insensitive)."""
    from scripts.compare_asr import recognition_tokens

    return recognition_tokens(normalize_numbers(text))


def _alignment(reference: list[str], hypothesis: list[str]) -> list[str]:
    """Levenshtein operations: ``ok``, ``sub``, ``ins`` and ``del``."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    cost = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        cost[i][0] = i
    for j in range(cols):
        cost[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1,
                             cost[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]))
    ops: list[str] = []
    i, j = rows - 1, cols - 1
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]):
            ops.append("ok" if reference[i - 1] == hypothesis[j - 1] else "sub")
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            ops.append("del")
            i -= 1
        else:
            ops.append("ins")
            j -= 1
    return ops[::-1]


# Two or more reference units missing at the end: the engine stopped early.
TRUNCATION_TAIL_UNITS = 2
# Extra speech: at least this many inserted units, or 30% of the reference.
HALLUCINATION_MIN_INSERTIONS = 3
HALLUCINATION_INSERTION_RATIO = 0.3
# An n-gram (2-4 units) spoken this many times more than the reference has it.
REPEAT_COUNT = 3


def _repeats(reference: list[str], hypothesis: list[str]) -> bool:
    for size in (2, 3, 4):
        grams = [tuple(hypothesis[index:index + size]) for index in range(len(hypothesis) - size + 1)]
        expected = [tuple(reference[index:index + size]) for index in range(len(reference) - size + 1)]
        for gram in set(grams):
            if grams.count(gram) - expected.count(gram) >= REPEAT_COUNT - 1 and grams.count(gram) >= REPEAT_COUNT:
                return True
    return False


def transcript_flags(reference: list[str], hypothesis: list[str]) -> list[str]:
    ops = _alignment(reference, hypothesis)
    trailing = 0
    for op in reversed(ops):
        if op != "del":
            break
        trailing += 1
    flags = []
    if reference and trailing >= min(TRUNCATION_TAIL_UNITS, len(reference)):
        flags.append("truncated")
    insertions = ops.count("ins")
    if (insertions >= max(HALLUCINATION_MIN_INSERTIONS, HALLUCINATION_INSERTION_RATIO * len(reference))
            or _repeats(reference, hypothesis)):
        flags.append("hallucinated")
    return flags


def score_transcript(sentence: Sentence, hypothesis: str) -> dict[str, Any]:
    """Error count against the closest accepted transcript, plus ASR-based flags."""
    hyp = scoring_tokens(hypothesis)
    best: tuple[int, str, list[str]] | None = None
    for candidate in (sentence.text, *sentence.alternatives):
        ref = scoring_tokens(candidate)
        edits = len([op for op in _alignment(ref, hyp) if op != "ok"])
        if best is None or edits < best[0]:
            best = (edits, candidate, ref)
    assert best is not None
    edits, candidate, ref = best
    return {"hypothesis": hypothesis, "reference": candidate, "edits": edits,
            "reference_tokens": len(ref), "flags": transcript_flags(ref, hyp)}


# Plausible speaking time per unit (CJK character or digit; English word) plus
# slack for leading and trailing silence. Outside the range = truncated or runaway audio.
SECONDS_PER_UNIT = {"zh-TW": (0.10, 0.60), "en-US": (0.15, 1.00)}
DURATION_SLACK_SECONDS = 1.5
EMPTY_PEAK = 300  # int16; below this the clip is silence
EMPTY_SECONDS = 0.2


def speech_units(text: str) -> int:
    from scripts.compare_asr import recognition_tokens

    return sum(len(token) if token.isdigit() else 1
               for token in recognition_tokens(text, normalize_script=False))


def duration_flags(sentence: Sentence, samples: np.ndarray, sample_rate: int) -> list[str]:
    if samples.size < EMPTY_SECONDS * sample_rate or int(np.abs(samples).max()) < EMPTY_PEAK:
        return ["empty"]
    seconds = samples.size / sample_rate
    units = [speech_units(text) for text in (sentence.text, *sentence.alternatives)]
    fastest, slowest = SECONDS_PER_UNIT.get(sentence.language, SECONDS_PER_UNIT["zh-TW"])
    if seconds < min(units) * fastest:
        return ["too_short"]
    if seconds > max(units) * slowest + DURATION_SLACK_SECONDS:
        return ["too_long"]
    return []


# --- Measurement -------------------------------------------------------------

# Issue 10 / spec Q23: first fragment synthesis P50 <= 0.4 s, P95 <= 0.7 s.
TARGET_P50_SECONDS = 0.4
TARGET_P95_SECONDS = 0.7


def _rounded(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples, sample_rate, subtype="PCM_16")


def _timing(result: SynthesisResult) -> dict[str, Any]:
    return {"ok": result.ok, "error": result.error,
            "first_audio_seconds": _rounded(result.first_audio_seconds),
            "total_seconds": _rounded(result.total_seconds),
            "audio_seconds": round(result.audio_seconds, 3)}


class LlmLoad:
    """Keeps an OpenAI-compatible server streaming tokens while TTS is timed."""

    PROMPT = "請用繁體中文詳細介紹臺灣的十個觀光景點，每個景點寫三句話。"

    def __init__(self, base_url: str, model: str = "default", *, max_tokens: int = 512):
        self.base_url = base_url.rstrip("/")
        self.model, self.max_tokens = model, max_tokens
        self.session = requests.Session()
        self.requests = 0
        self.chunks = 0
        self.errors: list[str] = []
        self._streaming = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _stream_once(self) -> None:
        body = {"model": self.model, "stream": True, "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": self.PROMPT}]}
        with self.session.post(f"{self.base_url}/chat/completions", json=body, stream=True,
                               timeout=(5, 120)) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if self._stop.is_set():
                    return
                if line.startswith(b"data:") and b"[DONE]" not in line:
                    self.chunks += 1
                    self._streaming.set()
        self.requests += 1

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._stream_once()
            except requests.RequestException as exc:
                if len(self.errors) < 5:
                    self.errors.append(f"{type(exc).__name__}: {exc}")
                self._stop.wait(1.0)

    def wait_until_streaming(self, timeout: float = 30.0) -> bool:
        return self._streaming.wait(timeout)

    def __enter__(self):
        self._thread = threading.Thread(target=self._loop, name="llm-load", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self.session.close()

    def summary(self) -> dict[str, Any]:
        return {"url": self.base_url, "model": self.model, "completed_requests": self.requests,
                "chunks": self.chunks, "errors": list(self.errors)}


def _fragment_round(client: ZeroShotClient, fragments: tuple[Sentence, ...], round_number: int,
                    save_dir: Path | None = None) -> list[dict]:
    rows = []
    for fragment in fragments:
        result = client.synthesize(fragment.text, fragment.language)
        rows.append({"sentence_id": fragment.sentence_id, "text": fragment.text,
                     "round": round_number, **_timing(result)})
        if save_dir is not None and result.ok:
            _write_wav(save_dir / f"{fragment.sentence_id}.wav", result.samples, result.sample_rate)
    return rows


def run_engine(args) -> dict:
    sets = load_sentence_sets(args.sentences)
    out_dir: Path = args.out_dir or BAKEOFF_DIR / "runs" / args.engine
    out_dir.mkdir(parents=True, exist_ok=True)
    client = ZeroShotClient(args.url, args.prompt_wav, args.prompt_text)
    health = client.health()
    fragments = sets.first_fragments
    sampler = VramSampler(NvidiaSmi(args.nvidia_smi, args.gpu_index), server_pid=args.server_pid,
                          baseline_mib=args.vram_baseline_mib, interval=args.vram_interval)
    latency: dict[str, list[dict]] = {"cold": [], "warm": [], "contended": []}
    llm_summary = None
    utterances = []
    with sampler:
        for index in range(args.cold_rounds):
            if index:
                time.sleep(args.idle_seconds)
            fragment = fragments[index % len(fragments)]
            result = client.synthesize(fragment.text, fragment.language)
            latency["cold"].append({"sentence_id": fragment.sentence_id, "text": fragment.text,
                                    "first_after_load": index == 0,
                                    "idle_before_seconds": args.idle_seconds if index else 0.0,
                                    **_timing(result)})
        print(f"{args.engine}: cold {len(latency['cold'])} done", flush=True)
        for index in range(args.warmup):
            fragment = fragments[index % len(fragments)]
            client.synthesize(fragment.text, fragment.language)
        for round_number in range(1, args.warm_rounds + 1):
            save = out_dir / "audio" / "fragments" if round_number == 1 else None
            latency["warm"].extend(_fragment_round(client, fragments, round_number, save))
        print(f"{args.engine}: warm {len(latency['warm'])} done", flush=True)
        if args.llm_url:
            with LlmLoad(args.llm_url, args.llm_model) as load:
                if not load.wait_until_streaming():
                    print(f"{args.engine}: LLM produced no tokens; contended phase is invalid", flush=True)
                for round_number in range(1, args.warm_rounds + 1):
                    latency["contended"].extend(_fragment_round(client, fragments, round_number))
            llm_summary = load.summary()
            print(f"{args.engine}: contended {len(latency['contended'])} done", flush=True)
        corpus = sets.sentences
        total = max(args.stability_count, len(corpus))
        for index in range(total):
            sentence = corpus[index % len(corpus)]
            round_number = index // len(corpus) + 1
            result = client.synthesize(sentence.text, sentence.language)
            relative = f"audio/r{round_number}/{sentence.sentence_id}.wav"
            if result.ok:
                _write_wav(out_dir / relative, result.samples, result.sample_rate)
            utterances.append({
                **sentence.to_json(), "round": round_number, "audio": relative if result.ok else None,
                **_timing(result),
                "duration_flags": duration_flags(sentence, result.samples, result.sample_rate)
                if result.ok else ["failed"],
            })
            if (index + 1) % 50 == 0:
                print(f"{args.engine}: {index + 1}/{total} sentences", flush=True)
    run = {
        "engine": args.engine,
        "label": args.label or args.engine,
        "measured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": args.note,
        "url": args.url,
        "server": health,
        "prompt": {"file": Path(args.prompt_wav).name, "text": args.prompt_text},
        "settings": {"cold_rounds": args.cold_rounds, "idle_seconds": args.idle_seconds,
                     "warmup": args.warmup, "warm_rounds": args.warm_rounds,
                     "stability_count": total, "sentences": str(args.sentences)},
        "latency": latency,
        "llm_load": llm_summary,
        "vram": sampler.summary(),
        "utterances": utterances,
    }
    (out_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run


# --- ASR scoring -------------------------------------------------------------


def _sentence_from_row(row: dict) -> Sentence:
    return Sentence(row["id"], row["language"], row["category"], row["text"],
                    tuple(row.get("focus", ())), tuple(row.get("alternatives", ())))


def score_run(run_dir: Path, recognize: Callable[[Path, str], str], *, settings: dict) -> dict:
    """Recognize every saved WAV and store error counts and flags in ``scores.json``."""
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    scored = {}
    for row in run["utterances"]:
        if row["audio"]:
            hypothesis = recognize(run_dir / row["audio"], row["language"])
            scored[row["audio"]] = score_transcript(_sentence_from_row(row), hypothesis)
    scores = {"asr": settings,
              "scored_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "utterances": scored}
    (run_dir / "scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    return scores


def whisper_recognizer(model: str, device: str) -> tuple[Callable[[Path, str], str], dict]:
    import resampy

    from scripts.compare_asr import SAMPLE_RATE, _load_engine, wav_bytes
    from src.asr.base import asr_language

    engine, load_seconds = _load_engine("whisper", argparse.Namespace(
        device=device, whisper_model=model, funasr_model=""))

    def recognize(path: Path, language: str) -> str:
        samples, rate = sf.read(path, dtype="float32", always_2d=False)
        if rate != SAMPLE_RATE:
            samples = resampy.resample(samples, rate, SAMPLE_RATE)
        result = engine.transcribe(wav_bytes(samples), language=asr_language(language))
        return str(result.get("text", "")).strip()

    info = engine.get_info()
    return recognize, {"engine": "whisper", "model": info.get("model_size"), "device": info.get("device"),
                       "compute_type": info.get("compute_type"), "beam_size": 1,
                       "load_seconds": round(load_seconds, 3)}


# --- Report ------------------------------------------------------------------

METRIC = {"zh-TW": "CER", "en-US": "WER"}
DURATION_FLAGS = ("failed", "empty", "too_short", "too_long")
TRANSCRIPT_FLAGS = ("truncated", "hallucinated")


def _latency_summary(rows: list[dict]) -> dict[str, Any]:
    from src.server.reply_streaming.soak import percentile

    good = [row for row in rows if row["ok"] and row["first_audio_seconds"] is not None]
    first = [row["first_audio_seconds"] for row in good]
    total = [row["total_seconds"] for row in good]
    rtf = [row["total_seconds"] / row["audio_seconds"] for row in good if row["audio_seconds"]]
    return {"n": len(good), "failures": len(rows) - len(good),
            "first_audio_p50": percentile(first, 50), "first_audio_p95": percentile(first, 95),
            "total_p50": percentile(total, 50), "total_p95": percentile(total, 95),
            "rtf_p50": percentile(rtf, 50)}


def _meets_target(summary: dict) -> bool | None:
    if not summary["n"]:
        return None
    return (summary["first_audio_p50"] <= TARGET_P50_SECONDS
            and summary["first_audio_p95"] <= TARGET_P95_SECONDS)


def _error_rate(rows: list[dict], scored: dict) -> float | None:
    entries = [scored.get(row["audio"]) for row in rows if row["audio"]]
    if not entries or any(entry is None for entry in entries):
        return None
    tokens = sum(entry["reference_tokens"] for entry in entries)
    return round(sum(entry["edits"] for entry in entries) / tokens, 4) if tokens else None


def _accuracy(rows: list[dict], scored: dict) -> dict[str, Any]:
    first_round = [row for row in rows if row["round"] == 1]
    categories = sorted({row["category"] for row in first_round})
    return {
        "utterances": len(first_round),
        "failed": sum(1 for row in first_round if not row["audio"]),
        "error_rate": _error_rate(first_round, scored),
        "by_category": {category: _error_rate([row for row in first_round if row["category"] == category], scored)
                        for category in categories},
    }


def _stability(rows: list[dict], scored: dict) -> dict[str, Any]:
    counts: dict[str, Any] = {flag: 0 for flag in DURATION_FLAGS}
    complete = all(row["audio"] in scored for row in rows if row["audio"])
    for flag in TRANSCRIPT_FLAGS:
        counts[flag] = 0 if complete else None
    issues = 0
    for row in rows:
        flags = list(row["duration_flags"])
        if row["audio"] and row["audio"] in scored:
            flags += scored[row["audio"]]["flags"]
        for flag in flags:
            if counts.get(flag) is not None:
                counts[flag] += 1
        issues += bool(flags)
    return {"utterances": len(rows), **counts, "transcripts_scored": complete,
            "any_issue": issues, "any_issue_rate": round(issues / len(rows), 4) if rows else None}


def _load_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def build_report(run_dirs: list[Path]) -> dict:
    engines = {}
    for run_dir in run_dirs:
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        scores = _load_json(run_dir / "scores.json") or {}
        scored = scores.get("utterances", {})
        latency = {phase: _latency_summary(rows) for phase, rows in run["latency"].items()}
        cold_first = next((row for row in run["latency"]["cold"] if row.get("first_after_load")), None)
        latency["cold_first_after_load_seconds"] = cold_first["first_audio_seconds"] if cold_first else None
        utterances = run["utterances"]
        engines[run["engine"]] = {
            "label": run["label"],
            "run_dir": str(run_dir.resolve()),
            "measured_at": run["measured_at"],
            "note": run.get("note", ""),
            "server": run["server"],
            "settings": run["settings"],
            "latency": latency,
            "meets_target": {phase: _meets_target(latency[phase]) for phase in ("warm", "contended")},
            "llm_load": run.get("llm_load"),
            "vram": run["vram"],
            "asr": scores.get("asr"),
            "accuracy": {language: {"metric": METRIC[language],
                                    **_accuracy([row for row in utterances if row["language"] == language], scored)}
                         for language in LANGUAGES},
            "stability": _stability(utterances, scored),
            "soak": _load_json(run_dir / "soak-summary.json"),
        }
    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "targets": {"first_audio_p50_seconds": TARGET_P50_SECONDS, "first_audio_p95_seconds": TARGET_P95_SECONDS},
        "definitions": {
            "first_audio": "送出 /inference_zero_shot 到收到第一段 PCM（與應用 `first audio:` 日誌相同）；"
                           "BreezyVoice 不串流，約等於整段合成時間",
            "cold": "第一筆為伺服器載入後第一次合成；其餘每筆前閒置 idle_seconds",
            "warm": "暖機後連續合成第一個片段（約 15 字）",
            "contended": "同上，但 LLM 同時串流生成",
            "vram": "nvidia-smi 量測：delta_peak_mib = 評比期間峰值 − 啟動伺服器前基準",
            "error_rate": "第一輪 Whisper 回辨；zh-TW 為 CER（中文逐字、英文字詞整體）、en-US 為 WER；"
                          "忽略繁簡字形與標點，數字的讀法與寫法視為相同，取最接近的可接受逐字稿",
            "stability": "全部輪次：failed／empty／too_short／too_long 依音訊長度判斷，"
                         "truncated（結尾少 2 個以上單位）／hallucinated（多出 30% 以上或重複片段）依回辨",
        },
        "engines": engines,
    }


# --- Listening page ----------------------------------------------------------


def _audio_src(run_dir: Path, relative: str, out_dir: Path) -> str:
    return urllib.parse.quote(os.path.relpath(run_dir / relative, out_dir).replace(os.sep, "/"))


def _fmt(value: Any, digits: int = 3, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "達標" if value else "未達"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def _summary_rows(report: dict) -> str:
    rows = []
    for name, engine in report["engines"].items():
        latency = engine["latency"]
        stability = engine["stability"]
        soak = engine.get("soak") or {}
        cells = [
            engine["label"],
            f"{_fmt(latency['warm']['first_audio_p50'])} / {_fmt(latency['warm']['first_audio_p95'])}",
            _fmt(engine["meets_target"]["warm"]),
            f"{_fmt(latency['contended']['first_audio_p50'])} / {_fmt(latency['contended']['first_audio_p95'])}",
            f"{_fmt(latency['cold_first_after_load_seconds'])} ; {_fmt(latency['cold']['first_audio_p50'])} / "
            f"{_fmt(latency['cold']['first_audio_p95'])}",
            _fmt(engine["vram"].get("delta_peak_mib"), suffix=" MiB"),
            _fmt(engine["accuracy"]["zh-TW"]["error_rate"], 4),
            _fmt(engine["accuracy"]["en-US"]["error_rate"], 4),
            f"{_fmt(stability['any_issue_rate'], 4)} (n={stability['utterances']})",
            _fmt(soak.get("failure_rate"), 4) if soak else "—",
        ]
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells) + "</tr>")
    return "\n".join(rows)


def _rating(engine: str, sentence_id: str, focus: bool) -> str:
    key = html.escape(f"{engine}:{sentence_id}", quote=True)
    options = "".join(f'<option value="{score}">{score}</option>' for score in range(1, 6))
    select = f'<select data-rate="{key}" aria-label="音質評分"><option value="">評分</option>{options}</select>'
    if focus:
        select += f' <label><input type="checkbox" data-reading="{key}"> 台灣讀音正確</label>'
    return select


def render_listening_page(report: dict, out_dir: Path) -> str:
    engines = report["engines"]
    runs = {name: (Path(engine["run_dir"]),
                   json.loads((Path(engine["run_dir"]) / "run.json").read_text(encoding="utf-8")),
                   (_load_json(Path(engine["run_dir"]) / "scores.json") or {}).get("utterances", {}))
            for name, engine in engines.items()}
    header = "".join(f"<th>{html.escape(engine['label'])}</th>" for engine in engines.values())

    fragment_ids: dict[str, str] = {}
    for _, run, _ in runs.values():
        for row in run["latency"]["warm"]:
            if row["round"] == 1:
                fragment_ids.setdefault(row["sentence_id"], row["text"])
    fragment_rows = []
    for sentence_id, text in fragment_ids.items():
        cells = []
        for name, (run_dir, run, _) in runs.items():
            row = next((r for r in run["latency"]["warm"] if r["round"] == 1 and r["sentence_id"] == sentence_id), None)
            if row and row["ok"]:
                src = _audio_src(run_dir, f"audio/fragments/{sentence_id}.wav", out_dir)
                cells.append(f'<td><audio controls preload="none" src="{src}"></audio>'
                             f'<div class="meta">{_fmt(row["first_audio_seconds"])} s</div>'
                             f"{_rating(name, sentence_id, False)}</td>")
            else:
                cells.append("<td>—</td>")
        fragment_rows.append(f"<tr><th>{html.escape(text)}</th>{''.join(cells)}</tr>")

    sentence_rows = []
    order: dict[str, dict] = {}
    for _, run, _ in runs.values():
        for row in run["utterances"]:
            if row["round"] == 1:
                order.setdefault(row["id"], row)
    for sentence_id, sentence in order.items():
        cells = []
        for name, (run_dir, run, scored) in runs.items():
            row = next((r for r in run["utterances"] if r["round"] == 1 and r["id"] == sentence_id), None)
            if not row or not row["audio"]:
                cells.append(f"<td>失敗 {html.escape(row['error'] if row else '')}</td>")
                continue
            score = scored.get(row["audio"])
            flags = list(row["duration_flags"]) + (score["flags"] if score else [])
            detail = ""
            if score:
                rate = score["edits"] / score["reference_tokens"] if score["reference_tokens"] else 0.0
                detail = (f'<div class="asr">{html.escape(score["hypothesis"])}</div>'
                          f'<div class="meta">{METRIC[row["language"]]} {rate:.3f}</div>')
            flag_html = "".join(f'<span class="flag">{html.escape(flag)}</span>' for flag in flags)
            src = _audio_src(run_dir, row["audio"], out_dir)
            cells.append(f'<td><audio controls preload="none" src="{src}"></audio>{detail}{flag_html}'
                         f"{_rating(name, sentence_id, bool(sentence['focus']))}</td>")
        focus = "、".join(sentence["focus"])
        focus_html = f'<div class="focus">注意讀音：{html.escape(focus)}</div>' if focus else ""
        sentence_rows.append(
            f'<tr><th><div class="cat">{html.escape(sentence["category"])}</div>'
            f"{html.escape(sentence['text'])}{focus_html}</th>{''.join(cells)}</tr>")

    return PAGE_TEMPLATE.format(
        generated=html.escape(report["generated_at"]),
        target_p50=TARGET_P50_SECONDS, target_p95=TARGET_P95_SECONDS,
        summary=_summary_rows(report), header=header,
        fragments="\n".join(fragment_rows), sentences="\n".join(sentence_rows))


PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TTS 評比試聽</title>
<style>
:root {{ --bg: #fbfbf8; --fg: #1d1d1b; --muted: #6b6b66; --line: #deded8; --flag: #b3261e; --accent: #2f5d8a; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #171716; --fg: #ecece6; --muted: #a2a29a; --line: #3a3a36; --flag: #f2a49c; --accent: #9cc2ea; }}
}}
body {{ margin: 0; padding: 16px; background: var(--bg); color: var(--fg);
       font: 15px/1.5 system-ui, "Noto Sans TC", "PingFang TC", sans-serif; }}
h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.1rem; margin: 28px 0 8px; }}
.note, .meta, .cat {{ color: var(--muted); font-size: 0.85rem; }}
.wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
thead th {{ position: sticky; top: 0; background: var(--bg); }}
tbody th {{ font-weight: 500; min-width: 14em; }}
audio {{ width: 220px; max-width: 100%; display: block; }}
.asr {{ font-size: 0.9rem; }}
.flag {{ color: var(--flag); font-size: 0.8rem; margin-right: 6px; }}
.focus {{ color: var(--accent); font-size: 0.85rem; }}
button {{ font: inherit; padding: 6px 12px; }}
</style>
</head>
<body>
<h1>TTS 評比試聽</h1>
<p class="note">產生於 {generated}。目標：第一個片段 P50 ≤ {target_p50} s、P95 ≤ {target_p95} s。
評分只存在這台瀏覽器；完成後按「匯出評分」下載 JSON，交給評比負責人。</p>
<button type="button" id="export">匯出評分</button>
<h2>總覽</h2>
<div class="wrap"><table>
<thead><tr><th>引擎</th><th>暖機首片段 P50 / P95 (s)</th><th>目標</th><th>LLM 串流中 P50 / P95 (s)</th>
<th>冷啟首筆 ; 閒置後 P50 / P95 (s)</th><th>額外顯存</th><th>中文 CER</th><th>英文 WER</th>
<th>截斷／幻覺等問題率</th><th>8 小時失敗率</th></tr></thead>
<tbody>
{summary}
</tbody></table></div>
<h2>第一個片段（約 15 字）</h2>
<div class="wrap"><table><thead><tr><th>文字</th>{header}</tr></thead><tbody>
{fragments}
</tbody></table></div>
<h2>句子（第一輪；下方為 Whisper 回辨）</h2>
<div class="wrap"><table><thead><tr><th>文字</th>{header}</tr></thead><tbody>
{sentences}
</tbody></table></div>
<script>
(function () {{
  var KEY = "nova-tts-bakeoff-ratings";
  var ratings = {{}};
  try {{ ratings = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{ ratings = {{}}; }}
  function save() {{ try {{ localStorage.setItem(KEY, JSON.stringify(ratings)); }} catch (e) {{}} }}
  document.querySelectorAll("select[data-rate]").forEach(function (el) {{
    var key = el.getAttribute("data-rate");
    if (ratings[key] && ratings[key].score) {{ el.value = ratings[key].score; }}
    el.addEventListener("change", function () {{
      ratings[key] = Object.assign(ratings[key] || {{}}, {{ score: el.value }}); save();
    }});
  }});
  document.querySelectorAll("input[data-reading]").forEach(function (el) {{
    var key = el.getAttribute("data-reading");
    if (ratings[key] && ratings[key].taiwan_reading) {{ el.checked = true; }}
    el.addEventListener("change", function () {{
      ratings[key] = Object.assign(ratings[key] || {{}}, {{ taiwan_reading: el.checked }}); save();
    }});
  }});
  document.getElementById("export").addEventListener("click", function () {{
    var blob = new Blob([JSON.stringify(ratings, null, 2)], {{ type: "application/json" }});
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "tts-bakeoff-ratings.json";
    link.click();
  }});
}})();
</script>
</body>
</html>
"""


# --- Soak --------------------------------------------------------------------


def _slope_per_hour(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    hours = [t / 3600.0 for t, _ in points]
    values = [value for _, value in points]
    mean_h, mean_v = sum(hours) / len(hours), sum(values) / len(values)
    spread = sum((h - mean_h) ** 2 for h in hours)
    if not spread:
        return None
    return round(sum((h - mean_h) * (v - mean_v) for h, v in zip(hours, values)) / spread, 3)


def summarize_soak(rows: list[dict]) -> dict[str, Any]:
    from src.server.reply_streaming.soak import percentile

    synth = [row for row in rows if row["type"] == "synthesis"]
    vram = [row for row in rows if row["type"] == "vram"]
    failures = [row for row in synth if not row["ok"]]
    flags: dict[str, int] = {}
    for row in synth:
        for flag in row.get("flags", ()):
            flags[flag] = flags.get(flag, 0) + 1
    hourly = []
    for hour in sorted({int(row["t"] // 3600) for row in synth}):
        bucket = [row for row in synth if int(row["t"] // 3600) == hour]
        first = [row["first_audio_seconds"] for row in bucket if row["ok"] and row["first_audio_seconds"] is not None]
        hourly.append({"hour": hour, "requests": len(bucket),
                       "failures": sum(1 for row in bucket if not row["ok"]),
                       "first_audio_p50": percentile(first, 50), "first_audio_p95": percentile(first, 95)})
    drift = None
    if len(hourly) >= 2 and hourly[0]["first_audio_p50"] is not None and hourly[-1]["first_audio_p50"] is not None:
        drift = round(hourly[-1]["first_audio_p50"] - hourly[0]["first_audio_p50"], 6)
    gpu = [(row["t"], row["gpu_mib"]) for row in vram if row.get("gpu_mib") is not None]
    process = [(row["t"], row["process_mib"]) for row in vram if row.get("process_mib") is not None]
    return {
        "duration_hours": round(max((row["t"] for row in rows), default=0.0) / 3600.0, 3),
        "requests": len(synth),
        "failures": len(failures),
        "failure_rate": round(len(failures) / len(synth), 6) if synth else None,
        "errors": sorted({row.get("error", "") for row in failures})[:10],
        "flags": flags,
        "hourly": hourly,
        "latency_drift_p50_seconds": drift,
        "vram": {
            "gpu_first_mib": gpu[0][1] if gpu else None,
            "gpu_last_mib": gpu[-1][1] if gpu else None,
            "gpu_max_mib": max(value for _, value in gpu) if gpu else None,
            "gpu_growth_mib_per_hour": _slope_per_hour(gpu),
            "process_max_mib": max(value for _, value in process) if process else None,
            "process_growth_mib_per_hour": _slope_per_hour(process),
        },
    }


def run_soak(args) -> dict:
    sets = load_sentence_sets(args.sentences)
    items = [*sets.first_fragments, *sets.sentences]
    client = ZeroShotClient(args.url, args.prompt_wav, args.prompt_text)
    client.health()
    probe = NvidiaSmi(args.nvidia_smi, args.gpu_index)
    out: Path = args.output or BAKEOFF_DIR / "runs" / args.engine / "soak.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    seconds = args.hours * 3600.0
    started = time.monotonic()
    next_vram = started
    index = 0
    with out.open("w", encoding="utf-8") as handle:
        def emit(row: dict) -> None:
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()

        try:
            while time.monotonic() - started < seconds:
                sentence = items[index % len(items)]
                index += 1
                result = client.synthesize(sentence.text, sentence.language)
                emit({"type": "synthesis", "t": round(time.monotonic() - started, 3),
                      "sentence_id": sentence.sentence_id, **_timing(result),
                      "flags": duration_flags(sentence, result.samples, result.sample_rate) if result.ok else []})
                if time.monotonic() >= next_vram:
                    sampler = VramSampler(probe, server_pid=args.server_pid, baseline_mib=None)
                    sampler.sample()
                    emit({"type": "vram", "t": round(time.monotonic() - started, 3),
                          "gpu_mib": sampler.gpu[0] if sampler.gpu else None,
                          "process_mib": sampler.process[0] if sampler.process else None,
                          "errors": sampler.errors})
                    next_vram = time.monotonic() + args.vram_every
                if index % 500 == 0:
                    print(f"{args.engine} soak: {index} requests, "
                          f"{(time.monotonic() - started) / 3600:.2f} h", flush=True)
                if args.interval:
                    time.sleep(args.interval)
        except KeyboardInterrupt:
            print("soak interrupted; summarizing what ran", flush=True)
    summary = {"engine": args.engine, "url": args.url, "planned_hours": args.hours,
               "interval_seconds": args.interval, "server": client.health() if rows else None,
               **summarize_soak(rows)}
    summary_path = out.with_name("soak-summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


# --- CLI ---------------------------------------------------------------------


def _add_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine", required=True, help="short name, e.g. breezyvoice, qwen3-tts, cosyvoice3")
    parser.add_argument("--url", required=True, help="the engine server, e.g. http://127.0.0.1:50000")
    parser.add_argument("--prompt-wav", type=Path, required=True, help="reference voice recording")
    parser.add_argument("--prompt-text", required=True, help="transcript of the reference recording")
    parser.add_argument("--sentences", type=Path, default=DEFAULT_SENTENCES)
    parser.add_argument("--server-pid", type=int, help="server PID for per-process VRAM")
    parser.add_argument("--nvidia-smi", default="nvidia-smi")
    parser.add_argument("--gpu-index", type=int, default=0)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    vram = commands.add_parser("vram", help="print GPU memory in use (MiB)")
    vram.add_argument("--nvidia-smi", default="nvidia-smi")
    vram.add_argument("--gpu-index", type=int, default=0)

    run = commands.add_parser("run", help="measure one running engine server")
    _add_server_args(run)
    run.add_argument("--label", default="", help="display name on the listening page")
    run.add_argument("--out-dir", type=Path, help="default: .scratch/first-audio-latency/tts-bakeoff/runs/<engine>")
    run.add_argument("--vram-baseline-mib", type=int, help="`vram` output taken before the server started")
    run.add_argument("--vram-interval", type=float, default=1.0)
    run.add_argument("--cold-rounds", type=int, default=5,
                     help="first right after server load, then each after --idle-seconds")
    run.add_argument("--idle-seconds", type=float, default=30.0)
    run.add_argument("--warmup", type=int, default=3)
    run.add_argument("--warm-rounds", type=int, default=3, help="passes over the first fragments")
    run.add_argument("--stability-count", type=int, default=500,
                     help="sentences synthesized in total (the corpus repeated); round 1 is scored for error rate")
    run.add_argument("--llm-url", help="OpenAI-compatible base URL kept streaming during the contended phase")
    run.add_argument("--llm-model", default="default")
    run.add_argument("--note", default="")

    score = commands.add_parser("score", help="recognize saved audio with Whisper (stop TTS servers first)")
    score.add_argument("--runs", type=Path, nargs="+", required=True)
    score.add_argument("--asr-model", default="turbo", help="Whisper size; turbo = local large-v3-turbo")
    score.add_argument("--device", default="cuda", choices=("cuda", "cpu"))

    report = commands.add_parser("report", help="write bakeoff.json and the listening page")
    report.add_argument("--runs", type=Path, nargs="+", required=True)
    report.add_argument("--output-dir", type=Path, default=BAKEOFF_DIR)

    soak = commands.add_parser("soak", help="long stability run against one engine server")
    _add_server_args(soak)
    soak.add_argument("--hours", type=float, default=8.0)
    soak.add_argument("--interval", type=float, default=1.0, help="pause between requests (s)")
    soak.add_argument("--vram-every", type=float, default=60.0, help="seconds between VRAM samples")
    soak.add_argument("--output", type=Path, help="default: runs/<engine>/soak.jsonl")

    args = parser.parse_args(argv)
    if args.command == "run":
        for name in ("cold_rounds", "warm_rounds", "stability_count"):
            if getattr(args, name) < 1:
                parser.error(f"--{name.replace('_', '-')} must be positive")
        if args.warmup < 0 or args.idle_seconds < 0:
            parser.error("--warmup and --idle-seconds must not be negative")
    if args.command == "soak" and args.hours <= 0:
        parser.error("--hours must be positive")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.command == "vram":
        print(NvidiaSmi(args.nvidia_smi, args.gpu_index).gpu_used_mib())
    elif args.command == "run":
        run = run_engine(args)
        summary = build_report([args.out_dir or BAKEOFF_DIR / "runs" / args.engine])["engines"][run["engine"]]
        for phase in ("cold", "warm", "contended"):
            print(f"{run['engine']} {phase}: {summary['latency'][phase]}", flush=True)
        print(f"{run['engine']} vram: {summary['vram']}", flush=True)
    elif args.command == "score":
        recognize, settings = whisper_recognizer(args.asr_model, args.device)
        for run_dir in args.runs:
            scores = score_run(run_dir, recognize, settings=settings)
            print(f"{run_dir}: scored {len(scores['utterances'])} clips", flush=True)
    elif args.command == "report":
        report = build_report(args.runs)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "bakeoff.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8")
        (args.output_dir / "index.html").write_text(render_listening_page(report, args.output_dir),
                                                    encoding="utf-8")
        for name, engine in report["engines"].items():
            print(f"{name}: warm={engine['latency']['warm']} target={engine['meets_target']} "
                  f"zh={engine['accuracy']['zh-TW']['error_rate']} en={engine['accuracy']['en-US']['error_rate']} "
                  f"stability={engine['stability']['any_issue_rate']} vram={engine['vram']['delta_peak_mib']}",
                  flush=True)
        print(f"listening page: {args.output_dir / 'index.html'}")
    elif args.command == "soak":
        summary = run_soak(args)
        print(json.dumps({key: summary[key] for key in ("requests", "failures", "latency_drift_p50_seconds", "vram")},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
