#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Export fine-tuned Matcha-TTS checkpoint to sherpa-onnx ONNX bundle."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import onnx
import torch

from lexicon_utils import build_merged_lexicon
from matcha_arch import ensure_matcha_import_path, load_sherpa_checkpoint

_REPO_ROOT = Path(__file__).resolve().parents[2]


class _MatchaOnnxWrapper(torch.nn.Module):
    def __init__(self, model: torch.nn.Module, num_ode_steps: int = 3) -> None:
        super().__init__()
        self.model = model
        self.num_ode_steps = int(num_ode_steps)

    def forward(
        self,
        x: torch.Tensor,
        x_length: torch.Tensor,
        noise_scale: torch.Tensor,
        length_scale: torch.Tensor,
    ) -> torch.Tensor:
        out = self.model.synthesise(
            x=x,
            x_lengths=x_length,
            n_timesteps=self.num_ode_steps,
            temperature=noise_scale.squeeze(0),
            length_scale=length_scale.squeeze(0),
        )
        return out["mel"]


def _attach_sherpa_metadata(onnx_path: Path, num_ode_steps: int) -> None:
    model = onnx.load(str(onnx_path))
    meta = {
        "model_type": "matcha-tts",
        "language": "chinese English",
        "voice": "zh en-us",
        "n_speakers": "1",
        "sample_rate": "16000",
        "version": "1",
        "pad_id": "0",
        "use_eos_bos": "1",
        "num_ode_steps": str(num_ode_steps),
        "model_author": "nova-avatar-distilled",
    }
    existing = {p.key: p for p in model.metadata_props}
    for k, v in meta.items():
        if k in existing:
            existing[k].value = v
        else:
            prop = model.metadata_props.add()
            prop.key = k
            prop.value = v
    onnx.save(model, str(onnx_path))


def _verify_sherpa_onnx_bundle(out_dir: Path) -> None:
    try:
        import sherpa_onnx
    except ImportError:
        print("[warn] sherpa_onnx not installed in current Python; verify with .venv/bin/python")
        return

    fsts = [str(out_dir / n) for n in ("phone-zh.fst", "date-zh.fst", "number-zh.fst") if (out_dir / n).is_file()]
    tts = sherpa_onnx.OfflineTts(
        sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                    acoustic_model=str(out_dir / "model.onnx"),
                    vocoder=str(out_dir / "vocos-16khz-univ.onnx"),
                    lexicon=str(out_dir / "lexicon.txt"),
                    tokens=str(out_dir / "tokens.txt"),
                ),
                num_threads=4,
                provider="cpu",
                debug=False,
            ),
            rule_fsts=",".join(fsts),
        )
    )
    for text in (
        "你好，歡迎使用 Nova Avatar 語音合成系統。",
        "今天台北氣溫二十六度，感謝您的收看。",
        "Welcome to Nova Avatar.",
    ):
        audio = tts.generate(text, sid=0, speed=1.0)
        assert len(audio.samples) > 0 and audio.sample_rate == 16000, f"Verification failed on {text}"
        print(f"[verify OK] {text!r} -> {len(audio.samples)/audio.sample_rate:.2f}s @ {audio.sample_rate}Hz")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ckpt",
        type=Path,
        default=Path(".local/matcha-train/best.pt"),
        help="Trained checkpoint or base pytorch_model_sherpa.bin",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/tts/zh-tw-custom"),
    )
    parser.add_argument("--num-ode-steps", type=int, default=3)
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    ensure_matcha_import_path()
    model = load_sherpa_checkpoint(args.ckpt).eval().cpu()
    wrapper = _MatchaOnnxWrapper(model, num_ode_steps=args.num_ode_steps).eval()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = args.output_dir / "model.onnx"

    x = torch.tensor([[0, 120, 0, 250, 0, 310, 0]], dtype=torch.long)
    x_len = torch.tensor([x.shape[1]], dtype=torch.long)
    noise_scale = torch.tensor([0.667], dtype=torch.float32)
    length_scale = torch.tensor([1.0], dtype=torch.float32)

    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (x, x_len, noise_scale, length_scale),
            str(onnx_path),
            dynamo=False,
            opset_version=17,
            input_names=["x", "x_length", "noise_scale", "length_scale"],
            output_names=["mel"],
            dynamic_axes={
                "x": {0: "N", 1: "L"},
                "x_length": {0: "N"},
                "mel": {0: "N", 2: "T"},
            },
        )
    _attach_sherpa_metadata(onnx_path, args.num_ode_steps)

    base_assets = _REPO_ROOT / "models/tts/matcha-icefall-zh-en"
    for name in ("vocos-16khz-univ.onnx", "tokens.txt", "phone-zh.fst", "date-zh.fst", "number-zh.fst"):
        src = base_assets / name
        if src.is_file():
            shutil.copy2(src, args.output_dir / name)

    build_merged_lexicon(
        base_assets / "lexicon.txt",
        args.output_dir / "tokens.txt",
        out_path=args.output_dir / "lexicon.txt",
    )

    print(f"Exported Matcha ONNX bundle -> {args.output_dir}")
    if not args.skip_verify:
        _verify_sherpa_onnx_bundle(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
