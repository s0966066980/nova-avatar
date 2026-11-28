# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prove the Matcha-TTS training venv works: strict checkpoint load, then CPU steps.

Run with the venv's interpreter (``.local/matcha-train/venv/bin/python``), never
the main project venv; ``services/tts/scripts/setup-matcha-train.sh`` does this last.

1. Build the architecture of ``dengcunqin/matcha_tts_zh_en_20251010`` with the
   upstream ``matcha.models.matcha_tts.MatchaTTS`` and load
   ``pytorch_model_sherpa.bin`` with ``strict=True`` (and ``weights_only=True``,
   so the pickle cannot run code). A missing, unexpected or reshaped key fails
   the run; nothing here loosens that.
2. Run a few optimizer steps on random 16 kHz audio and random token ids, using
   the same 16 kHz log-mel front end as inference. Only the CPU is used.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU only, must be set before torch starts

import torch  # noqa: E402

# The architecture, checkpoint loader and fake batch live with the training scripts, so the
# check exercises exactly what training uses. ``-I`` keeps the script folder off sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "integrations" / "matcha-train" / "scripts"))
from matcha_arch import SEGMENT_FRAMES, fake_batch, load_sherpa_checkpoint  # noqa: E402

DEFAULT_CHECKPOINT = Path(".local/matcha-base/pytorch_model_sherpa.bin")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--steps", type=int, default=3)
    args = parser.parse_args(argv)

    model = load_sherpa_checkpoint(args.checkpoint, out_size=SEGMENT_FRAMES)
    n_vocab = int(model.encoder.emb.weight.shape[0])
    params = sum(p.numel() for p in model.parameters())
    print(f"strict load OK: {params / 1e6:.2f}M parameters, vocabulary {n_vocab}, torch {torch.__version__}")
    if torch.cuda.is_available():
        raise SystemExit("CUDA is visible; this check must run on the CPU only")

    torch.manual_seed(0)
    x, x_len, y, y_len = fake_batch(model, n_vocab)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    model.train()
    for step in range(1, args.steps + 1):
        optimizer.zero_grad(set_to_none=True)
        dur_loss, prior_loss, diff_loss, *_ = model(x, x_len, y, y_len, out_size=SEGMENT_FRAMES)
        loss = dur_loss + prior_loss + diff_loss
        if not torch.isfinite(loss):
            raise SystemExit(f"step {step}: non-finite loss {loss.item()}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        print(f"step {step}: loss {loss.item():.4f} "
              f"(dur {dur_loss.item():.3f} prior {prior_loss.item():.3f} diff {diff_loss.item():.3f})")
    print("CPU training steps OK")


if __name__ == "__main__":
    main()
