#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Offline Edge-TTS research teacher synthesis + Whisper QA filter.

RESEARCH / NON-COMMERCIAL ONLY:
Audio synthesized from Microsoft Edge Read Aloud is subject to Microsoft's
online service terms and MUST NOT be used to train models distributed as
commercially licensed weights under Apache-2.0.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from pathlib import Path

import aiohttp
import av
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from audio_qc import process_and_verify_utterance
from lexicon_utils import build_merged_lexicon, load_tokens, text_to_phoneme_ids
from src.tts.edge_connection import EdgeConnectionPool


def _decode_mp3_to_16k_float(mp3_bytes: bytes) -> np.ndarray:
    """Decode Edge MP3 bytes to mono 16 kHz float32 PCM via PyAV."""
    if not mp3_bytes:
        return np.empty(0, dtype=np.float32)
    container = av.open(io.BytesIO(mp3_bytes), format="mp3")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks: list[np.ndarray] = []
    for frame in container.decode(audio=0):
        for resampled in resampler.resample(frame):
            pcm = resampled.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
            if pcm.size:
                chunks.append(pcm)
    for resampled in resampler.resample(None):
        pcm = resampled.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
        if pcm.size:
            chunks.append(pcm)
    container.close()
    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)


async def _synthesize_with_backoff(
    pool: EdgeConnectionPool,
    text: str,
    voice: str,
    *,
    max_attempts: int = 5,
    base_backoff: float = 4.0,
) -> bytes:
    """Stream MP3 audio using EdgeConnectionPool with 429/socket backoff retries."""
    delay = base_backoff
    for attempt in range(1, max_attempts + 1):
        buf = bytearray()
        try:
            async for chunk in pool.stream(text, voice):
                if chunk.get("type") == "audio":
                    buf.extend(chunk["data"])
            if buf:
                return bytes(buf)
        except (
            aiohttp.WSServerHandshakeError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ConnectionError,
            RuntimeError,
        ) as exc:
            status = getattr(exc, "status", None)
            if attempt >= max_attempts:
                raise RuntimeError(
                    f"Edge-TTS failed after {max_attempts} attempts (status={status}): {exc}"
                ) from exc
            wait_s = delay
            headers = getattr(exc, "headers", None) or {}
            if "Retry-After" in headers:
                try:
                    wait_s = max(wait_s, float(headers["Retry-After"]))
                except (TypeError, ValueError):
                    pass
            print(
                f"[retry {attempt}/{max_attempts}] status={status} err={type(exc).__name__}; sleep {wait_s:.1f}s",
                flush=True,
            )
            await asyncio.sleep(wait_s)
            delay = min(60.0, delay * 2.0)
    return b""


async def _run_distill(args) -> int:
    tokens_path = _REPO_ROOT / "models/tts/matcha-icefall-zh-en/tokens.txt"
    zh_lex = _REPO_ROOT / "models/tts/matcha-icefall-zh-en/lexicon.txt"
    tok_to_id = load_tokens(tokens_path)
    merged_lex = build_merged_lexicon(
        zh_lex,
        tokens_path,
        out_path=args.out_dir / "lexicon.txt",
    )

    items = [
        json.loads(line)
        for line in args.corpus.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit > 0:
        items = items[: args.limit]

    wav_dir = args.out_dir / "wav16k"
    wav_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / "manifest.jsonl"
    done_ids: set[str] = set()
    if args.resume and manifest_path.is_file():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["id"])

    whisper = None
    if not args.skip_asr:
        from faster_whisper import WhisperModel

        model_ref = _REPO_ROOT / "models/whisper-small"
        whisper_id = str(model_ref) if model_ref.is_dir() else args.whisper_model
        whisper = WhisperModel(whisper_id, device=args.asr_device, compute_type="float16" if args.asr_device == "cuda" else "int8")

    from opencc import OpenCC

    converter = OpenCC("t2s")
    pool = EdgeConnectionPool(max_idle=1)
    kept = len(done_ids)
    rejected = 0
    mode = "a" if args.resume and manifest_path.is_file() else "w"
    t0 = time.perf_counter()

    try:
        with manifest_path.open(mode, encoding="utf-8") as manifest_out:
            for idx, item in enumerate(items, 1):
                uid = item["id"]
                if uid in done_ids:
                    continue
                phoneme_ids = text_to_phoneme_ids(item["text"], merged_lex, tok_to_id, converter=converter)
                if not phoneme_ids:
                    rejected += 1
                    continue
                mp3_bytes = await _synthesize_with_backoff(
                    pool,
                    item["text"],
                    args.voice,
                )
                wav_16k = _decode_mp3_to_16k_float(mp3_bytes)
                record = process_and_verify_utterance(
                    wav_16k=wav_16k,
                    uid=uid,
                    text=item["text"],
                    language=item.get("language", "zh-TW"),
                    phoneme_ids=phoneme_ids,
                    wav_dir=wav_dir,
                    whisper=whisper,
                    min_asr_sim=args.min_asr_sim,
                    converter=converter,
                )
                if record is None:
                    rejected += 1
                else:
                    manifest_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    manifest_out.flush()
                    kept += 1
                if idx % 20 == 0 or idx == len(items):
                    print(
                        f"[{idx}/{len(items)}] voice={args.voice} kept={kept} rejected={rejected} "
                        f"elapsed={time.perf_counter()-t0:.1f}s",
                        flush=True,
                    )
                if args.delay_seconds > 0:
                    await asyncio.sleep(args.delay_seconds)
    finally:
        await pool.close()

    print(f"Done. kept={kept}, rejected={rejected}, manifest={manifest_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/tts/distill/corpus.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/tts/distill-edgetts"))
    parser.add_argument("--voice", default="zh-TW-HsiaoChenNeural")
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--asr-device", default="cuda", choices=("cuda", "cpu"))
    parser.add_argument("--min-asr-sim", type=float, default=0.65)
    parser.add_argument("--delay-seconds", type=float, default=0.35)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-asr", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run_distill(args))


if __name__ == "__main__":
    raise SystemExit(main())
