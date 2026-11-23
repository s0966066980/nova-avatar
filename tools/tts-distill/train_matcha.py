#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Fine-tune Matcha-TTS (Apache-2.0 base) on distilled zh-TW + en-US audio."""

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

from matcha_arch import VocosMelExtractor, load_sherpa_checkpoint


class DistilledMatchaDataset(Dataset):
    def __init__(
        self,
        manifest_path: Path,
        mel_mean: float,
        mel_std: float,
        target_rms: float = 0.11,
        pad_silence_ms: float = 150.0,
    ) -> None:
        self.items = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.mel_mean = float(mel_mean)
        self.mel_std = float(mel_std)
        self.target_rms = float(target_rms)
        self.pad_samples = max(0, int(round(16000.0 * float(pad_silence_ms) / 1000.0)))
        self.extractor = VocosMelExtractor()

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        item = self.items[index]
        wav_np, sr = sf.read(item["wav"], dtype="float32")
        if wav_np.ndim > 1:
            wav_np = wav_np.mean(axis=1)
        if sr != 16000:
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
        wav_t = torch.from_numpy(wav_np)
        with torch.no_grad():
            mel = self.extractor(wav_t)
            mel = (mel - self.mel_mean) / self.mel_std
        x = torch.tensor(item["phoneme_ids"], dtype=torch.long)
        return x, mel


def _collate_batch(batch: list[tuple[torch.Tensor, torch.Tensor]]):
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


def _save_checkpoint(path: Path, model: torch.nn.Module, step: int, loss: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "step": step,
            "loss": float(loss),
            "model_state_dict": model.state_dict(),
        },
        str(path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/tts/distill/manifest.jsonl"))
    parser.add_argument(
        "--base-ckpt",
        type=Path,
        default=Path(".local/matcha-base/pytorch_model_sherpa.bin"),
    )
    parser.add_argument("--out-dir", type=Path, default=Path(".local/matcha-train"))
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
    parser.add_argument("--full-seq", action="store_true", help="Train on full utterances instead of 172-frame random crops")
    parser.add_argument("--pad-silence-ms", type=float, default=150.0, help="Digital silence padded at wav boundaries (ms)")
    parser.add_argument("--encoder-anchor", type=float, default=0.0, help="L2-SP weight anchoring encoder prenet/transformer to base checkpoint")
    parser.add_argument("--dur-bounds-weight", type=float, default=0.0, help="Hinge penalty weight keeping speech phoneme durations within [min, max] frames")
    parser.add_argument("--dur-min-frames", type=float, default=4.5, help="Minimum target frames per non-punctuation phoneme when --dur-bounds-weight > 0")
    parser.add_argument("--dur-max-frames", type=float, default=22.0, help="Maximum target frames per non-punctuation phoneme when --dur-bounds-weight > 0")
    parser.add_argument("--save-every", type=int, default=250)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="Verify strict load and 2 CUDA steps")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_sherpa_checkpoint(args.base_ckpt, out_size=172).to(device)
    param_count = sum(p.numel() for p in model.parameters())
    print(f"Loaded MatchaTTS ({param_count/1e6:.2f}M params) on {device}")

    if args.dry_run:
        bs = min(args.batch_size, 4)
        x = torch.randint(1, 2180, (bs, 32), device=device)
        x_len = torch.full((bs,), 32, dtype=torch.long, device=device)
        y = torch.randn(bs, 80, 180, device=device)
        y_len = torch.full((bs,), 180, dtype=torch.long, device=device)
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
        for s in range(2):
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
                dur_l, prior_l, diff_l = model(x, x_len, y, y_len, out_size=172)
                loss = dur_l + prior_l + diff_l
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            print(f"dry-run step={s+1} loss={float(loss.item()):.4f}")
        return 0

    dataset = DistilledMatchaDataset(
        args.manifest,
        mel_mean=float(model.mel_mean.item()),
        mel_std=float(model.mel_std.item()),
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
        collate_fn=_collate_batch,
        pin_memory=device.type == "cuda",
    )

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

    param_groups = [{"params": dec_params, "lr": args.lr}]
    if enc_params and args.encoder_lr_scale > 0:
        enc_group: dict = {"params": enc_params, "lr": args.lr * args.encoder_lr_scale}
        if args.encoder_anchor > 0:
            enc_group["weight_decay"] = 0.0
        param_groups.append(enc_group)
    elif enc_params:
        for param in enc_params:
            param.requires_grad = False

    proj_scale = args.encoder_lr_scale if args.proj_lr_scale < 0 else args.proj_lr_scale
    if proj_params and proj_scale > 0:
        param_groups.append({"params": proj_params, "lr": args.lr * proj_scale})
    elif proj_params:
        for param in proj_params:
            param.requires_grad = False

    anchor_pairs: list[tuple[torch.nn.Parameter, torch.Tensor]] = []
    if args.encoder_anchor > 0:
        anchor_pairs = [
            (param, param.detach().clone())
            for name, param in model.named_parameters()
            if param.requires_grad and name.startswith(("encoder.prenet.", "encoder.encoder."))
        ]

    optimizer = torch.optim.AdamW(param_groups, lr=args.lr, weight_decay=1e-4)
    total_steps = args.max_steps if args.max_steps > 0 else max(1, args.epochs * len(loader))
    warmup_steps = min(200, max(1, total_steps // 10))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda s: min(1.0, (s + 1) / warmup_steps) * 0.5 * (1.0 + math.cos(math.pi * min(s, total_steps) / total_steps)),
    )

    best_loss = float("inf")
    ema_loss: float | None = None
    step = 0
    t0 = time.perf_counter()
    captured_logw: list[torch.Tensor] = []
    if args.dur_bounds_weight > 0:
        model.encoder.register_forward_hook(
            lambda _mod, _inp, out: captured_logw.append(out[1])
        )
    min_logw = math.log(max(1.0, args.dur_min_frames))
    max_logw = math.log(max(args.dur_min_frames + 1.0, args.dur_max_frames))

    model.train()
    for epoch in range(args.epochs):
        for x, x_len, y, y_len in loader:
            x = x.to(device, non_blocking=True)
            x_len = x_len.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)
            y_len = y_len.to(device, non_blocking=True)
            seg_len = None if args.full_seq else min(172, int(y.shape[-1] // 4) * 4)

            optimizer.zero_grad(set_to_none=True)
            captured_logw.clear()
            with torch.amp.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
                dur_l, prior_l, diff_l = model(
                    x, x_len, y, y_len, out_size=seg_len if (seg_len is None or seg_len >= 32) else None
                )
                loss = dur_l + prior_l + diff_l
                if captured_logw:
                    logw_pred = captured_logw[-1].float()
                    speech_mask = (x >= 15).unsqueeze(1).to(logw_pred.dtype)
                    short_pen = torch.relu(min_logw - logw_pred) ** 2
                    long_pen = torch.relu(logw_pred - max_logw) ** 2
                    bound_l = ((short_pen + long_pen) * speech_mask).sum() / speech_mask.sum().clamp_min(1.0)
                    loss = loss + args.dur_bounds_weight * bound_l
                if anchor_pairs:
                    reg = sum(((p.float() - ref) ** 2).sum() for p, ref in anchor_pairs)
                    loss = loss + 0.5 * args.encoder_anchor * reg
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            step += 1
            val = float(loss.item())
            ema_loss = val if ema_loss is None else (0.95 * ema_loss + 0.05 * val)
            if step % 20 == 0 or step == 1:
                print(
                    f"epoch={epoch+1} step={step}/{total_steps} loss={val:.4f} ema={ema_loss:.4f} "
                    f"(dur={float(dur_l):.3f} prior={float(prior_l):.3f} diff={float(diff_l):.3f}) "
                    f"elapsed={time.perf_counter()-t0:.1f}s",
                    flush=True,
                )
            if step >= min(200, total_steps // 2) and ema_loss < best_loss:
                best_loss = ema_loss
                _save_checkpoint(args.out_dir / "best.pt", model, step, ema_loss)
            if step % args.save_every == 0:
                _save_checkpoint(args.out_dir / "last.pt", model, step, ema_loss)
            if args.max_steps > 0 and step >= args.max_steps:
                break
        if args.max_steps > 0 and step >= args.max_steps:
            break

    last_loss = ema_loss if ema_loss is not None else best_loss
    _save_checkpoint(args.out_dir / "last.pt", model, step, last_loss)
    if not (args.out_dir / "best.pt").is_file():
        _save_checkpoint(args.out_dir / "best.pt", model, step, last_loss)
    print(f"Training complete: steps={step}, best_ema={best_loss:.4f}, out={args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
