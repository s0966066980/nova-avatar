#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Offline Fun-CosyVoice3-0.5B teacher synthesis + Whisper QA filter."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
import torchaudio

from audio_qc import process_and_verify_utterance
from lexicon_utils import build_merged_lexicon, load_tokens, text_to_phoneme_ids

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PROMPT_WAV = Path("data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.wav")
_DEFAULT_PROMPT_TXT = Path("data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.txt")


def _load_prompt_paths(prompt_wav: Path, prompt_txt: Path) -> tuple[Path, Path]:
    if prompt_wav.is_file() and prompt_txt.is_file():
        return prompt_wav, prompt_txt
    fallback_wav = _REPO_ROOT / ".scratch/tts-eval/prompts/ref_tw_yunjhe.wav"
    fallback_txt = _REPO_ROOT / ".scratch/tts-eval/prompts/ref_tw_yunjhe.txt"
    if fallback_wav.is_file() and fallback_txt.is_file():
        print(
            f"[warn] Primary prompt not found ({prompt_wav}); falling back to {fallback_wav}",
            flush=True,
        )
        return fallback_wav, fallback_txt
    raise FileNotFoundError(
        f"Missing prompt wav/txt ({prompt_wav}, {prompt_txt}). "
        "Provide --prompt-wav and --prompt-txt."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/tts/distill/corpus.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/tts/distill"))
    parser.add_argument("--prompt-wav", type=Path, default=_DEFAULT_PROMPT_WAV)
    parser.add_argument("--prompt-txt", type=Path, default=_DEFAULT_PROMPT_TXT)
    parser.add_argument(
        "--cosyvoice-dir",
        type=Path,
        default=Path(".local/cosyvoice3/model"),
    )
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--min-asr-sim", type=float, default=0.65)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-asr", action="store_true")
    args = parser.parse_args()

    prompt_wav, prompt_txt = _load_prompt_paths(args.prompt_wav, args.prompt_txt)
    prompt_text_body = prompt_txt.read_text(encoding="utf-8").strip()
    full_prompt = f"You are a helpful assistant.<|endofprompt|>{prompt_text_body}"

    cosy_root = _REPO_ROOT / ".local/cosyvoice3/CosyVoice"
    sys.path.insert(0, str(cosy_root))
    sys.path.insert(0, str(cosy_root / "third_party/Matcha-TTS"))

    # Avoid torchcodec dependency inside torchaudio.load
    def _sf_load(path, *_, **__):
        data, sr = sf.read(str(path), dtype="float32")
        t = torch.from_numpy(data)
        if t.ndim == 1:
            t = t.unsqueeze(0)
        else:
            t = t.t()
        return t, sr

    torchaudio.load = _sf_load
    from cosyvoice.cli.cosyvoice import AutoModel

    tokens_path = _REPO_ROOT / "models/tts/matcha-icefall-zh-en/tokens.txt"
    zh_lex = _REPO_ROOT / "models/tts/matcha-icefall-zh-en/lexicon.txt"
    tok_to_id = load_tokens(tokens_path)
    merged_lex = build_merged_lexicon(
        zh_lex,
        tokens_path,
        out_path=args.out_dir / "lexicon.txt",
    )

    items = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
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

    cosyvoice = AutoModel(model_dir=str(args.cosyvoice_dir), fp16=True, load_trt=False)
    cosyvoice.add_zero_shot_spk(full_prompt, str(prompt_wav), "tw_teacher")

    whisper = None
    if not args.skip_asr:
        from faster_whisper import WhisperModel

        whisper = WhisperModel(args.whisper_model, device="cuda", compute_type="float16")

    kept = len(done_ids)
    rejected = 0
    mode = "a" if args.resume and manifest_path.is_file() else "w"
    t0 = time.perf_counter()
    with manifest_path.open(mode, encoding="utf-8") as manifest_out:
        for idx, item in enumerate(items, 1):
            uid = item["id"]
            if uid in done_ids:
                continue
            phoneme_ids = text_to_phoneme_ids(item["text"], merged_lex, tok_to_id)
            if not phoneme_ids:
                rejected += 1
                continue

            chunks = [
                out["tts_speech"].detach().cpu().squeeze(0)
                for out in cosyvoice.inference_zero_shot(
                    tts_text=item["text"],
                    prompt_text="",
                    prompt_wav="",
                    zero_shot_spk_id="tw_teacher",
                    stream=False,
                    text_frontend=True,
                )
            ]
            if not chunks:
                rejected += 1
                continue
            wav_t = torch.cat(chunks, dim=-1)
            sr = int(cosyvoice.sample_rate)
            if sr != 16000:
                wav_t = torchaudio.functional.resample(wav_t, sr, 16000)
            record = process_and_verify_utterance(
                wav_16k=wav_t.numpy(),
                uid=uid,
                text=item["text"],
                language=item.get("language", "zh-TW"),
                phoneme_ids=phoneme_ids,
                wav_dir=wav_dir,
                whisper=whisper,
                min_asr_sim=args.min_asr_sim,
            )
            if record is None:
                rejected += 1
                continue

            manifest_out.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest_out.flush()
            kept += 1
            if idx % 25 == 0 or idx == len(items):
                print(
                    f"[{idx}/{len(items)}] kept={kept} rejected={rejected} elapsed={time.perf_counter()-t0:.1f}s",
                    flush=True,
                )

    print(f"Done. kept={kept}, rejected={rejected}, manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
