# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prove the Matcha-TTS training venv works: strict checkpoint load, then CPU steps.

Run with the venv's interpreter (``.local/matcha-train/venv/bin/python``), never
the main project venv; ``scripts/setup-matcha-train.sh`` does this last.

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
from pathlib import Path
from types import SimpleNamespace

os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU only, must be set before torch starts

import torch  # noqa: E402
import torchaudio  # noqa: E402

SAMPLE_RATE = 16000
N_FEATS = 80
SEGMENT_FRAMES = 172  # the random-crop length used for training (multiple of 4)
DEFAULT_CHECKPOINT = Path(".local/matcha-base/pytorch_model_sherpa.bin")


def _namespace(mapping: dict) -> SimpleNamespace:
    return SimpleNamespace(**{k: _namespace(v) if isinstance(v, dict) else v for k, v in mapping.items()})


def build_model(n_vocab: int, mel_mean: float, mel_std: float):
    """Instantiate the sherpa-onnx variant of Matcha-TTS (RoPE encoder, snakebeta decoder)."""
    from matcha.models.matcha_tts import MatchaTTS

    encoder = _namespace({
        "encoder_type": "RoPE Encoder",
        "encoder_params": {
            "n_feats": N_FEATS, "n_channels": 192, "filter_channels": 768, "filter_channels_dp": 256,
            "n_heads": 2, "n_layers": 6, "kernel_size": 3, "p_dropout": 0.1, "window_size": 4, "prenet": True,
        },
        "duration_predictor_params": {"filter_channels_dp": 256, "kernel_size": 3, "p_dropout": 0.1},
    })
    return MatchaTTS(
        n_vocab=n_vocab, n_spks=1, spk_emb_dim=64, n_feats=N_FEATS,
        encoder=encoder,
        decoder={
            "channels": [256, 256], "dropout": 0.05, "attention_head_dim": 64,
            "n_blocks": 1, "num_mid_blocks": 2, "num_heads": 2, "act_fn": "snakebeta",
        },
        cfm=_namespace({"name": "CFM", "solver": "euler", "sigma_min": 1e-4}),
        data_statistics={"mel_mean": mel_mean, "mel_std": mel_std},
        out_size=SEGMENT_FRAMES, prior_loss=True,
    )


def load_checkpoint(path: Path):
    """Strictly load a base checkpoint; return ``(model, n_vocab)``."""
    raw = torch.load(str(path), map_location="cpu", weights_only=True)
    state = {key.removeprefix("model."): value for key, value in raw.items()}
    n_vocab = int(state["encoder.emb.weight"].shape[0])
    model = build_model(n_vocab, float(state["mel_mean"]), float(state["mel_std"]))
    model.load_state_dict(state, strict=True)
    return model, n_vocab


def fake_batch(model, n_vocab: int, batch: int = 2, seconds: float = 3.0, tokens: int = 24):
    """Random audio through the inference-time log-mel front end, plus random token ids.

    The clip must give at least ``SEGMENT_FRAMES`` frames: ``out_size`` crops each
    utterance to that length and the upstream model fails on shorter ones, so
    real training shrinks ``out_size`` to the batch's shortest length.
    """
    mel_transform = torchaudio.transforms.MelSpectrogram(
        sample_rate=SAMPLE_RATE, n_fft=1024, hop_length=256, win_length=1024, n_mels=N_FEATS,
        f_min=0.0, f_max=8000.0, power=1.0, center=True, norm=None, mel_scale="htk",
    )
    wav = torch.randn(batch, int(SAMPLE_RATE * seconds)) * 0.1
    mel = torch.log(torch.clamp(mel_transform(wav), min=1e-7))
    mel = (mel - float(model.mel_mean)) / float(model.mel_std)
    frames = mel.shape[-1] // 4 * 4  # the U-Net downsamples by 4
    mel = mel[..., :frames]
    x = torch.randint(1, n_vocab, (batch, tokens))
    return (
        x, torch.full((batch,), tokens, dtype=torch.long),
        mel, torch.full((batch,), frames, dtype=torch.long),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--steps", type=int, default=3)
    args = parser.parse_args(argv)

    model, n_vocab = load_checkpoint(args.checkpoint)
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
