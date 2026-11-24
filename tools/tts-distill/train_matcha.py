#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# Adapted from tools/tts-distill/train_matcha.py on the jetson-orin branch.
# Modified by HongXian0903, 2026.

"""Fine-tune Matcha-TTS (the Apache-2.0-labelled base model) on a prepared corpus.

Runs in the training venv (``.local/matcha-train/venv``), started by the training
job (``src/server/tts_training_jobs.py``) as a separate process so that SIGTERM
releases the GPU at once. The job writes the manifest: one JSON object per line
with ``wav`` (a 16 kHz mono WAV prepared by the job), ``phoneme_ids`` (token IDs
of the digit-expanded transcript, tokenised by the job) and ``text``. This script
never tokenises text and never sees a raw digit.

Progress goes to stdout as ``epoch=E step=S/T loss=...`` lines that the job parses.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from torch.utils.data import DataLoader, Dataset

from matcha_arch import SAMPLE_RATE, SEGMENT_FRAMES, VocosMelExtractor, batch_out_size, load_sherpa_checkpoint


class DistilledMatchaDataset(Dataset):
    def __init__(
        self,
        manifest_path: Path,
        mel_mean: float,
        mel_std: float,
        n_vocab: int,
        target_rms: float = 0.11,
        pad_silence_ms: float = 150.0,
    ) -> None:
        self.items = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for item in self.items:
            ids = item["phoneme_ids"]
            if not ids or min(ids) < 1 or max(ids) >= n_vocab:
                raise ValueError(f"token ids outside 1..{n_vocab - 1} for {item['wav']}")
        self.mel_mean = float(mel_mean)
        self.mel_std = float(mel_std)
        self.target_rms = float(target_rms)
        self.pad_samples = max(0, int(round(SAMPLE_RATE * float(pad_silence_ms) / 1000.0)))
        self.extractor = VocosMelExtractor()

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        item = self.items[index]
        wav_np, sr = sf.read(item["wav"], dtype="float32")
        if wav_np.ndim > 1:
            wav_np = wav_np.mean(axis=1)
        if sr != SAMPLE_RATE:
            raise ValueError(f"Expected 16kHz audio, got {sr} for {item['wav']}")
        if self.target_rms > 0 and wav_np.size:
            rms = float(np.sqrt(np.mean(wav_np**2)))
            if rms > 1e-4:
                gain = self.target_rms / rms
                peak_after = float(np.max(np.abs(wav_np))) * gain
                if peak_after > 0.75:
                    gain *= 0.75 / peak_after
                wav_np = wav_np * gain
        if self.pad_samples > 0:
            wav_np = np.pad(wav_np, (self.pad_samples, self.pad_samples), mode="constant")
        with torch.no_grad():
            mel = self.extractor(torch.from_numpy(wav_np))
            mel = (mel - self.mel_mean) / self.mel_std
        return torch.tensor(item["phoneme_ids"], dtype=torch.long), mel


def collate_batch(batch: list[tuple[torch.Tensor, torch.Tensor]]):
    x_lengths = torch.tensor([x.shape[0] for x, _ in batch], dtype=torch.long)
    y_lengths = torch.tensor([m.shape[-1] for _, m in batch], dtype=torch.long)
    max_x = int(x_lengths.max().item())
    # Pad y length to multiple of 4 (UNet downsampling factor = 4)
    max_y = int(math.ceil(int(y_lengths.max().item()) / 4.0) * 4)

    x_pad = torch.zeros(len(batch), max_x, dtype=torch.long)
    y_pad = torch.zeros(len(batch), 80, max_y, dtype=torch.float32)
    for i, (x, m) in enumerate(batch):
        x_pad[i, : x.shape[0]] = x
        y_pad[i, :, : m.shape[-1]] = m
    return x_pad, x_lengths, y_pad, y_lengths


def save_checkpoint(path: Path, model: torch.nn.Module, step: int, loss: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"step": step, "loss": float(loss), "model_state_dict": model.state_dict()}, str(path))


def training_step(model, batch, device, *, full_seq: bool) -> tuple[torch.Tensor, tuple[float, float, float]]:
    """One forward pass; returns the summed loss and its (duration, prior, diffusion) parts.

    ``MatchaTTS.forward`` returns four values ``(dur_loss, prior_loss, diff_loss, attn)``.
    The random crop is sized by the batch's shortest utterance (``batch_out_size``), not by
    the padded batch width, which made short batches fail in the decoder.
    """
    x, x_len, y, y_len = (t.to(device, non_blocking=True) for t in batch)
    out_size = None if full_seq else batch_out_size(y_len, SEGMENT_FRAMES)
    with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
        dur_l, prior_l, diff_l, _attn = model(x, x_len, y, y_len, out_size=out_size)
        loss = dur_l + prior_l + diff_l
    return loss, (float(dur_l), float(prior_l), float(diff_l))


def _freeze(model, args: argparse.Namespace) -> None:
    if args.freeze_encoder:
        for param in model.encoder.parameters():
            param.requires_grad = False
    elif args.freeze_encoder_body:
        for sub_name in ("emb", "prenet", "encoder"):
            sub = getattr(model.encoder, sub_name, None)
            if sub is not None:
                for param in sub.parameters():
                    param.requires_grad = False
    elif args.freeze_emb:
        for param in model.encoder.emb.parameters():
            param.requires_grad = False


def _param_groups(model, args: argparse.Namespace) -> list[dict]:
    enc_params, proj_params, dec_params = [], [], []
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if name.startswith("encoder.proj_"):
            proj_params.append(param)
        elif name.startswith("encoder."):
            enc_params.append(param)
        else:
            dec_params.append(param)

    groups = [{"params": dec_params, "lr": args.lr}]
    if enc_params and args.encoder_lr_scale > 0:
        groups.append({"params": enc_params, "lr": args.lr * args.encoder_lr_scale})
    else:
        for param in enc_params:
            param.requires_grad = False
    proj_scale = args.encoder_lr_scale if args.proj_lr_scale < 0 else args.proj_lr_scale
    if proj_params and proj_scale > 0:
        groups.append({"params": proj_params, "lr": args.lr * proj_scale})
    else:
        for param in proj_params:
            param.requires_grad = False
    return groups


def run_training(model, loader, device, args: argparse.Namespace) -> int:
    """The optimisation loop; returns the number of steps taken."""
    _freeze(model, args)
    optimizer = torch.optim.AdamW(_param_groups(model, args), lr=args.lr, weight_decay=1e-4)
    total_steps = args.max_steps if args.max_steps > 0 else max(1, args.epochs * len(loader))
    warmup_steps = min(200, max(1, total_steps // 10))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda s: min(1.0, (s + 1) / warmup_steps) * 0.5 * (1.0 + math.cos(math.pi * min(s, total_steps) / total_steps)),
    )

    best_loss = float("inf")
    ema_loss: float | None = None
    step = 0
    started = time.perf_counter()
    model.train()
    for epoch in range(args.epochs):
        for batch in loader:
            optimizer.zero_grad(set_to_none=True)
            loss, (dur, prior, diff) = training_step(model, batch, device, full_seq=args.full_seq)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            step += 1
            val = float(loss.item())
            ema_loss = val if ema_loss is None else (0.95 * ema_loss + 0.05 * val)
            if step % 20 == 0 or step == 1 or step == total_steps:
                print(
                    f"epoch={epoch + 1} step={step}/{total_steps} loss={val:.4f} ema={ema_loss:.4f} "
                    f"(dur={dur:.3f} prior={prior:.3f} diff={diff:.3f}) "
                    f"elapsed={time.perf_counter() - started:.1f}s",
                    flush=True,
                )
            if step >= min(200, total_steps // 2) and ema_loss < best_loss:
                best_loss = ema_loss
                save_checkpoint(args.out_dir / "best.pt", model, step, ema_loss)
            if step % args.save_every == 0:
                save_checkpoint(args.out_dir / "last.pt", model, step, ema_loss)
            if args.max_steps > 0 and step >= args.max_steps:
                break
        if args.max_steps > 0 and step >= args.max_steps:
            break

    last_loss = ema_loss if ema_loss is not None else best_loss
    save_checkpoint(args.out_dir / "last.pt", model, step, last_loss)
    if not (args.out_dir / "best.pt").is_file():
        save_checkpoint(args.out_dir / "best.pt", model, step, last_loss)
    print(f"Training complete: steps={step}, best_ema={best_loss:.4f}, out={args.out_dir}", flush=True)
    return step


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-ckpt", type=Path, default=Path(".local/matcha-base/pytorch_model_sherpa.bin"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=35)
    parser.add_argument("--max-steps", type=int, default=0, help="Stop after N steps if > 0")
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--encoder-lr-scale", type=float, default=0.2, help="LR multiplier for text encoder")
    parser.add_argument(
        "--proj-lr-scale",
        type=float,
        default=-1.0,
        help="Optional separate LR multiplier for encoder.proj_m/proj_w (<0 reuses --encoder-lr-scale)",
    )
    parser.add_argument("--freeze-emb", action="store_true", help="Freeze phoneme embedding table to preserve unseen tokens")
    parser.add_argument("--freeze-encoder", action="store_true", help="Freeze the entire text encoder (decoder-only voice adaptation)")
    parser.add_argument(
        "--freeze-encoder-body",
        action="store_true",
        help="Freeze emb, prenet, and 6-layer RoPE transformer while adapting proj_m, proj_w, and decoder",
    )
    parser.add_argument("--full-seq", action="store_true", help="Train on full utterances instead of random crops")
    parser.add_argument("--pad-silence-ms", type=float, default=150.0, help="Digital silence padded at wav boundaries (ms)")
    parser.add_argument("--save-every", type=int, default=250)
    parser.add_argument("--num-workers", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_sherpa_checkpoint(args.base_ckpt, out_size=SEGMENT_FRAMES).to(device)
    n_vocab = int(model.encoder.emb.weight.shape[0])
    params = sum(p.numel() for p in model.parameters())
    print(f"Loaded MatchaTTS ({params / 1e6:.2f}M params) on {device}", flush=True)

    dataset = DistilledMatchaDataset(
        args.manifest,
        mel_mean=float(model.mel_mean.item()),
        mel_std=float(model.mel_std.item()),
        n_vocab=n_vocab,
        pad_silence_ms=args.pad_silence_ms,
    )
    if len(dataset) == 0:
        raise RuntimeError(f"Empty manifest: {args.manifest}")
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        drop_last=len(dataset) >= args.batch_size,
        num_workers=args.num_workers,
        collate_fn=collate_batch,
        pin_memory=device.type == "cuda",
    )
    run_training(model, loader, device, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
