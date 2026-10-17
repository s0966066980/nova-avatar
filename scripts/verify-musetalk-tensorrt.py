#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Verify the configured production loader with avatar latents and Whisper features.

Measures UNet + full VAE + pixel transfer together; this is not WebRTC FPS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/config.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/tensorrt/musetalk")
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    args.config, args.output_dir = args.config.resolve(), args.output_dir.resolve()
    os.chdir(ROOT)
    import cv2
    import numpy as np
    import torch
    import tensorrt as trt
    from src.config.loader import load_config
    from src.avatars.factory import prepare_avatar_model
    from src.avatars.musetalk.inference_optimization import TensorRTUNet
    from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder

    config = load_config(str(args.config))
    if config.model.type != "musetalk":
        parser.error("Select a MuseTalk avatar before verification")
    model, avatar = prepare_avatar_model(config)
    vae, unet, pe, timesteps, processor = model
    if not isinstance(vae, TensorRTVAEDecoder) or not isinstance(unet.model, TensorRTUNet):
        raise RuntimeError("Both configured engines must load through the production factory")
    original_vae, original_unet = vae.original, unet.model.original
    # A deterministic audio fixture exercises the same Whisper feature path
    # without requiring a microphone, remote TTS, LLM, or user recording.
    t = np.arange(16000, dtype=np.float32) / 16000
    audio = (.15 * np.sin(2 * np.pi * 220 * t) + .05 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "gpu": torch.cuda.get_device_name(), "torch": torch.__version__,
        "cuda": torch.version.cuda, "tensorrt": trt.__version__,
        "avatar_id": config.model.avatar_id, "iterations": args.iterations, "warmup": 5,
        "audio_fixture": "deterministic 220/440 Hz harmonic, mono 16 kHz",
        "scope": "Whisper features prepared once; timed UNet + full VAE + CPU BGR pixels",
        "batches": {},
    }
    with torch.inference_mode():
        feature_array = processor.audio2feat(audio)
        for size in sorted({1, min(4, config.model.batch_size), config.model.batch_size}):
            features = processor.feature2chunks(feature_array, fps=25, batch_size=size)
            features = pe(torch.from_numpy(np.asarray(features)).to(device=unet.device, dtype=torch.float16))
            latents = torch.cat([avatar[4][i % len(avatar[4])] for i in range(size)])
            latents = latents.to(device=unet.device, dtype=torch.float16)

            def original():
                pred = original_unet(latents, timesteps, encoder_hidden_states=features).sample
                return original_vae.decode_latents(pred)

            def accelerated():
                pred = unet.model(latents, timesteps, encoder_hidden_states=features).sample
                return vae.decode_latents(pred)

            functions = [("pytorch", original), ("tensorrt", accelerated)]
            for _ in range(5):
                original()
                accelerated()
            timings = {name: [] for name, _ in functions}
            values = {}
            for iteration in range(args.iterations):
                for name, function in functions[::1 if iteration % 2 == 0 else -1]:
                    torch.cuda.synchronize()
                    start = time.perf_counter()
                    values[name] = function()
                    torch.cuda.synchronize()
                    timings[name].append(1000 * (time.perf_counter() - start))
            if vae._failed or unet.model._failed:
                raise RuntimeError("TensorRT execution fell back; verification failed")
            mse = float(np.mean((values["pytorch"].astype(np.float64) - values["tensorrt"]) ** 2))
            psnr = 10 * math.log10(255**2 / mse) if mse else None
            if not math.isfinite(mse) or (psnr is not None and psnr < 35):
                raise RuntimeError(f"Combined avatar output quality below 35 dB: {psnr}")
            result = {f"{name}_median_ms": statistics.median(durations) for name, durations in timings.items()}
            result.update(psnr_db=psnr, speedup=result["pytorch_median_ms"] / result["tensorrt_median_ms"])
            report["batches"][str(size)] = result
            # Crops allow inspection of actual avatar outputs; never served as
            # video or included in the runtime rendering path.
            cv2.imwrite(str(args.output_dir / f"avatar-batch{size}-comparison.png"), np.concatenate([values["pytorch"][0], values["tensorrt"][0]], axis=1))
            print(f"Avatar batch {size}: {json.dumps(result)}", flush=True)
    report["fallback"] = False
    report["torch_peak_allocated_mib"] = round(torch.cuda.max_memory_allocated() / 1024**2, 1)
    report["memory_note"] = "PyTorch allocator only; TensorRT allocations excluded"
    path = args.output_dir / "avatar-verification.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Production loader and avatar verification passed: {path}")


if __name__ == "__main__":
    main()
