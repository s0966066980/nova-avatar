#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
# Adapted from tools/tts-distill/export_matcha_onnx.py on the jetson-orin branch.
# Modified by HongXian0903, 2026.

"""Export a fine-tuned Matcha-TTS checkpoint to a sherpa-onnx voice-model bundle.

Runs in the training venv. It writes ``model.onnx`` (with the sherpa-onnx metadata) and
copies what the engine needs from the read-only base bundle (``models/tts/matcha-icefall-zh-en/``:
vocoder, ``tokens.txt`` and the rule FSTs) into ``--output-dir``. The lexicon is the merged
lexicon the training job tokenised the corpus with (``--lexicon``); without it one is built
from the base bundle. ``--output-dir`` is a staging folder: the job installs it into
``models/tts/<id>/`` atomically, and writes ``voice.json`` there. Loading the bundle in
sherpa-onnx is checked by the job afterwards, in the main environment.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import onnx
import torch

from lexicon_utils import build_merged_lexicon
from matcha_arch import load_sherpa_checkpoint

BASE_ASSETS = ("vocos-16khz-univ.onnx", "tokens.txt", "phone-zh.fst", "date-zh.fst", "number-zh.fst")


class MatchaOnnxWrapper(torch.nn.Module):
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


def attach_sherpa_metadata(onnx_path: Path, num_ode_steps: int) -> None:
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
        "model_author": "nova-avatar-trained",
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


def export_bundle(
    ckpt: Path,
    output_dir: Path,
    base_assets: Path,
    *,
    num_ode_steps: int = 3,
    lexicon: Path | None = None,
) -> None:
    model = load_sherpa_checkpoint(ckpt).eval().cpu()
    wrapper = MatchaOnnxWrapper(model, num_ode_steps=num_ode_steps).eval()

    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / "model.onnx"

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
    attach_sherpa_metadata(onnx_path, num_ode_steps)

    for name in BASE_ASSETS:
        source = base_assets / name
        if source.is_file():
            shutil.copy2(source, output_dir / name)
    if lexicon is not None:
        shutil.copy2(lexicon, output_dir / "lexicon.txt")
    else:
        build_merged_lexicon(
            base_assets / "lexicon.txt", output_dir / "tokens.txt", out_path=output_dir / "lexicon.txt"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, required=True, help="Trained checkpoint or base pytorch_model_sherpa.bin")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-assets", type=Path, default=Path("models/tts/matcha-icefall-zh-en"))
    parser.add_argument("--lexicon", type=Path, default=None, help="Merged lexicon used for training")
    parser.add_argument("--num-ode-steps", type=int, default=3)
    args = parser.parse_args(argv)

    export_bundle(
        args.ckpt, args.output_dir, args.base_assets, num_ode_steps=args.num_ode_steps, lexicon=args.lexicon
    )
    print(f"Exported Matcha ONNX bundle -> {args.output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
