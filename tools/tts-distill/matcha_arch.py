# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Shared Matcha-TTS architecture & Vocos log-mel feature helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import torch
import torchaudio

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEL_MEAN = -2.9522
DEFAULT_MEL_STD = 5.4468


def ensure_matcha_import_path() -> Path:
    matcha_root = _REPO_ROOT / ".local/cosyvoice3/CosyVoice/third_party/Matcha-TTS"
    if str(matcha_root) not in sys.path:
        sys.path.insert(0, str(matcha_root))
    return matcha_root


def _ns(mapping: dict) -> SimpleNamespace:
    return SimpleNamespace(
        **{k: _ns(v) if isinstance(v, dict) else v for k, v in mapping.items()}
    )


def build_sherpa_matcha_model(
    *,
    mel_mean: float = DEFAULT_MEL_MEAN,
    mel_std: float = DEFAULT_MEL_STD,
    out_size: int | None = None,
):
    """Instantiate MatchaTTS matching dengcunqin/matcha_tts_zh_en_20251010."""
    ensure_matcha_import_path()
    from matcha.models.matcha_tts import MatchaTTS

    return MatchaTTS(
        n_vocab=2190,
        n_spks=1,
        spk_emb_dim=64,
        n_feats=80,
        encoder=_ns(
            {
                "encoder_type": "RoPE Encoder",
                "encoder_params": {
                    "n_feats": 80,
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
    """Load either base pytorch_model_sherpa.bin or fine-tuned checkpoint strictly."""
    raw = torch.load(str(ckpt_path), map_location="cpu")
    if isinstance(raw, dict) and "model_state_dict" in raw:
        state = raw["model_state_dict"]
    elif isinstance(raw, dict) and "state_dict" in raw:
        state = raw["state_dict"]
    else:
        state = raw
    cleaned = {k.removeprefix("model."): v for k, v in state.items()}
    mel_mean = float(cleaned.get("mel_mean", DEFAULT_MEL_MEAN))
    mel_std = float(cleaned.get("mel_std", DEFAULT_MEL_STD))
    model = build_sherpa_matcha_model(
        mel_mean=mel_mean,
        mel_std=mel_std,
        out_size=out_size,
    )
    model.load_state_dict(cleaned, strict=True)
    return model


class VocosMelExtractor(torch.nn.Module):
    """16 kHz log-mel extractor aligned with vocos-16khz-univ.onnx."""

    def __init__(self) -> None:
        super().__init__()
        self.mel = torchaudio.transforms.MelSpectrogram(
            sample_rate=16000,
            n_fft=1024,
            hop_length=256,
            win_length=1024,
            n_mels=80,
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
