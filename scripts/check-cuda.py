#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Run CUDA kernels and optionally the actual Nova Avatar inference models."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="Run MuseTalk, Whisper, FunASR and Silero on CUDA")
    parser.add_argument("--output", type=Path, help="Save the verification report as JSON")
    args = parser.parse_args()
    import numpy as np
    import torch
    import torchvision
    import torchaudio
    import ctranslate2

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; install the ARM64 CUDA PyTorch wheel")
    report = {
        "torch": torch.__version__, "torchvision": torchvision.__version__,
        "torchaudio": torchaudio.__version__, "torch_cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
        "ctranslate2": ctranslate2.__version__,
    }
    with torch.inference_mode():
        x = torch.randn(128, 128, device="cuda", dtype=torch.float16)
        y = x @ x
        conv = torch.nn.Conv2d(8, 16, 3, padding=1).half().cuda()
        image = conv(torch.randn(2, 8, 32, 32, device="cuda", dtype=torch.float16))
        torch.cuda.synchronize()
        if not (y.is_cuda and image.is_cuda and torch.isfinite(image).all().item()):
            raise RuntimeError("CUDA matrix multiplication / FP16 convolution failed")
    report["torch_cuda_kernels"] = "passed"
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("CTranslate2 has no CUDA device; run scripts/build-jetson-ctranslate2.sh")
    report["ctranslate2_compute_types"] = sorted(ctranslate2.get_supported_compute_types("cuda"))
    if "float16" not in report["ctranslate2_compute_types"]:
        raise RuntimeError("CTranslate2 CUDA FP16 is unavailable")

    if args.models:
        import soundfile as sf
        from src.avatars.musetalk.avatar import load_model, warm_up
        from src.asr.engines.whisper import WhisperASR
        from src.asr.engines.funasr import FunASR
        from src.vad.engines.silero import SileroVAD

        with torch.inference_mode():
            started = time.perf_counter()
            model = load_model()
            vae, unet, pe, timesteps, audio_processor = model
            for module in (vae.vae, unet.model, pe, audio_processor.whisper):
                tensors = list(module.parameters()) + list(module.buffers())
                if not tensors or any(tensor.device.type != "cuda" for tensor in tensors):
                    raise RuntimeError("A MuseTalk model is on CPU")
            warm_up(2, model)
            audio_processor.audio2feat(np.zeros(16000, dtype=np.float32))
            torch.cuda.synchronize()
            report["musetalk_cuda"] = {"passed": True, "seconds": round(time.perf_counter() - started, 2)}
            del model, vae, unet, pe, timesteps, audio_processor
            torch.cuda.empty_cache()

        config = SimpleNamespace(asr=SimpleNamespace(device="cuda", output_script="traditional-tw"))
        with tempfile.TemporaryDirectory(prefix="nova-cuda-") as directory:
            audio_path = Path(directory) / "silence.wav"
            sf.write(audio_path, np.zeros(16000, dtype=np.float32), 16000)
            for name, engine_class in (("whisper", WhisperASR), ("funasr", FunASR)):
                engine = engine_class(config=config)
                engine.ensure_ready()
                engine._transcribe(str(audio_path))
                if engine.device != "cuda":
                    raise RuntimeError(f"{name} is on CPU")
                if name == "funasr" and next(engine.model.model.parameters()).device.type != "cuda":
                    raise RuntimeError("FunASR model parameters are on CPU")
                if name == "whisper" and engine.model.model.device != "cuda":
                    raise RuntimeError("Whisper CTranslate2 model is on CPU")
                report[f"{name}_cuda"] = "passed"
                del engine
                torch.cuda.empty_cache()
        vad = SileroVAD(device="cuda", use_onnx=False)
        vad._load_model()
        probability = vad._speech_prob(np.zeros(512, dtype=np.int16))
        if next(vad.model.parameters()).device.type != "cuda":
            raise RuntimeError("Silero model is on CPU")
        report["silero_cuda"] = {"passed": True, "silence_probability": probability}
        vad.close()

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
