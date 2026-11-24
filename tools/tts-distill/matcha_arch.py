# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# Adapted from tools/tts-distill/matcha_arch.py on the jetson-orin branch.
# Modified by HongXian0903, 2026.

"""Shared Matcha-TTS architecture and Vocos log-mel feature helpers.

Runs in the training venv (``.local/matcha-train/venv``, see
``scripts/setup-matcha-train.sh``), where the upstream ``matcha-tts`` package
(MIT, Shivam Mehta) is installed. The hyper-parameters are those of the base
model ``dengcunqin/matcha_tts_zh_en_20251010`` (``pytorch_model_sherpa.bin``).
Checkpoints are always loaded with ``weights_only=True`` and ``strict=True``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import torch
import torchaudio

SAMPLE_RATE = 16000
N_FEATS = 80
# Frames of the random crop used for training; the decoder U-Net downsamples by 4.
SEGMENT_FRAMES = 172
DEFAULT_MEL_MEAN = -2.9522
DEFAULT_MEL_STD = 5.4468


def _ns(mapping: dict) -> SimpleNamespace:
    return SimpleNamespace(**{k: _ns(v) if isinstance(v, dict) else v for k, v in mapping.items()})


def build_sherpa_matcha_model(
    *,
    n_vocab: int,
    mel_mean: float = DEFAULT_MEL_MEAN,
    mel_std: float = DEFAULT_MEL_STD,
    out_size: int | None = None,
):
    """Instantiate MatchaTTS matching dengcunqin/matcha_tts_zh_en_20251010."""
    from matcha.models.matcha_tts import MatchaTTS

    return MatchaTTS(
        n_vocab=n_vocab,
        n_spks=1,
        spk_emb_dim=64,
        n_feats=N_FEATS,
        encoder=_ns(
            {
                "encoder_type": "RoPE Encoder",
                "encoder_params": {
                    "n_feats": N_FEATS,
                    "n_channels": 192,
                    "filter_channels": 768,
                    "filter_channels_dp": 256,
                    "n_heads": 2,
                    "n_layers": 6,
                    "kernel_size": 3,
                    "p_dropout": 0.1,
                    "window_size": 4,
                    "prenet": True,
                },
                "duration_predictor_params": {
                    "filter_channels_dp": 256,
                    "kernel_size": 3,
                    "p_dropout": 0.1,
                },
            }
        ),
        decoder={
            "channels": [256, 256],
            "dropout": 0.05,
            "attention_head_dim": 64,
            "n_blocks": 1,
            "num_mid_blocks": 2,
            "num_heads": 2,
            "act_fn": "snakebeta",
        },
        cfm=_ns({"name": "CFM", "solver": "euler", "sigma_min": 1e-4}),
        data_statistics={"mel_mean": float(mel_mean), "mel_std": float(mel_std)},
        out_size=out_size,
        prior_loss=True,
    )


def load_sherpa_checkpoint(ckpt_path: Path, *, out_size: int | None = None):
    """Strictly load the base ``pytorch_model_sherpa.bin`` or a fine-tuned checkpoint.

    A fine-tuned checkpoint is the dict written by ``train_matcha`` (``model_state_dict``).
    The vocabulary size is read from the embedding table, so a base model with another
    token count is refused by ``strict=True`` rather than silently resized.
    """
    raw = torch.load(str(ckpt_path), map_location="cpu", weights_only=True)
    if isinstance(raw, dict) and "model_state_dict" in raw:
        state = raw["model_state_dict"]
    elif isinstance(raw, dict) and "state_dict" in raw:
        state = raw["state_dict"]
    else:
        state = raw
    cleaned = {k.removeprefix("model."): v for k, v in state.items()}
    model = build_sherpa_matcha_model(
        n_vocab=int(cleaned["encoder.emb.weight"].shape[0]),
        mel_mean=float(cleaned.get("mel_mean", DEFAULT_MEL_MEAN)),
        mel_std=float(cleaned.get("mel_std", DEFAULT_MEL_STD)),
        out_size=out_size,
    )
    model.load_state_dict(cleaned, strict=True)
    return model


def batch_out_size(y_lengths: torch.Tensor, segment: int = SEGMENT_FRAMES) -> int | None:
    """The ``out_size`` (random-crop length) that is safe for a batch of mel lengths.

    The upstream model crops every utterance to ``out_size`` frames and fails on one that
    is shorter, so the crop shrinks to the batch's *shortest* utterance, rounded down to a
    multiple of 4 (the U-Net downsampling factor). A batch too short to crop sensibly
    (under 32 frames) trains on the full utterances (``None``).
    """
    shortest = int(y_lengths.min().item())
    size = min(segment, shortest // 4 * 4)
    return size if size >= 32 else None


def fake_batch(model, n_vocab: int, batch: int = 2, seconds: float = 3.0, tokens: int = 24):
    """Random audio through the inference-time log-mel front end, plus random token ids."""
    extractor = VocosMelExtractor()
    wav = torch.randn(batch, int(SAMPLE_RATE * seconds)) * 0.1
    mel = (extractor(wav) - float(model.mel_mean)) / float(model.mel_std)
    frames = mel.shape[-1] // 4 * 4
    return (
        torch.randint(1, n_vocab, (batch, tokens)),
        torch.full((batch,), tokens, dtype=torch.long),
        mel[..., :frames],
        torch.full((batch,), frames, dtype=torch.long),
    )


class VocosMelExtractor(torch.nn.Module):
    """16 kHz log-mel extractor aligned with vocos-16khz-univ.onnx."""

    def __init__(self) -> None:
        super().__init__()
        self.mel = torchaudio.transforms.MelSpectrogram(
            sample_rate=SAMPLE_RATE,
            n_fft=1024,
            hop_length=256,
            win_length=1024,
            n_mels=N_FEATS,
            f_min=0.0,
            f_max=8000.0,
            power=1.0,
            center=True,
            norm=None,
            mel_scale="htk",
        )

    def forward(self, wav_16k: torch.Tensor) -> torch.Tensor:
        # Returns unnormalized log-mel shape (80, T) or (B, 80, T)
        spec = self.mel(wav_16k)
        return torch.log(torch.clamp(spec, min=1e-7))
