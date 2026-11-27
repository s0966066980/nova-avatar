#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Build and compare full-quality MuseTalk engines on the deployment GPU."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_engine(trt, onnx_path, engine_path, shapes, args):
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(str(onnx_path)):
        errors = "\n".join(str(parser.get_error(i)) for i in range(parser.num_errors))
        raise RuntimeError(f"ONNX parsing failed:\n{errors}")
    config = builder.create_builder_config()
    config.set_flag(trt.BuilderFlag.FP16)
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, args.workspace_mib * 1024**2)
    config.builder_optimization_level = args.optimization_level
    profile = builder.create_optimization_profile()
    for name, tail in shapes.items():
        profile.set_shape(name, (1, *tail), (args.batch_size, *tail), (args.batch_size, *tail))
    config.add_optimization_profile(profile)
    serialized = builder.build_serialized_network(network, config)
    if serialized is None:
        raise RuntimeError("TensorRT could not build this model on the selected GPU")
    temporary = engine_path.with_suffix(".engine.tmp")
    temporary.write_bytes(bytes(serialized))
    temporary.replace(engine_path)


def compare(torch, original, accelerated, samples, *, image_output, iterations=20):
    for _ in range(5):
        original(*samples)
        accelerated(*samples)
    torch.cuda.synchronize()
    timings = {}
    values = {}
    elapsed = {"pytorch": [], "tensorrt": []}
    functions = [("pytorch", original), ("tensorrt", accelerated)]
    for iteration in range(iterations):
        for name, function in functions[::1 if iteration % 2 == 0 else -1]:
            torch.cuda.synchronize()
            start = time.perf_counter()
            values[name] = function(*samples)
            torch.cuda.synchronize()
            elapsed[name].append((time.perf_counter() - start) * 1000)
    for name, durations in elapsed.items():
        timings[f"{name}_median_ms"] = statistics.median(durations)
    import numpy as np
    if image_output:
        mse = float(np.mean((values["pytorch"].astype(np.float64) - values["tensorrt"]) ** 2))
        timings["psnr_db"] = 10 * math.log10(255**2 / mse) if mse else None
        if mse and timings["psnr_db"] < 35:
            raise RuntimeError(f"VAE numerical comparison below 35 dB: {timings}")
    else:
        expected, actual = values["pytorch"].float(), values["tensorrt"].float()
        error = float(torch.linalg.vector_norm(actual - expected) / torch.linalg.vector_norm(expected).clamp_min(1e-6))
        timings["relative_l2_error"] = error
        if not math.isfinite(error) or error > .02:
            raise RuntimeError(f"UNet numerical comparison exceeds 2%: {timings}")
    timings["speedup"] = timings["pytorch_median_ms"] / timings["tensorrt_median_ms"]
    return timings


def enable_engines(report, config_path):
    """Enable only measured engines, preserving all private runtime settings."""
    import os
    import shutil
    import tempfile
    import yaml
    from src.config.loader import load_config
    from src.config.overrides import RUNTIME_OVERRIDES_FILE

    config = load_config(str(config_path))
    batch = str(config.model.batch_size)
    paths = {}
    for component, result in report["components"].items():
        measured = result["batches"].get(batch)
        if measured is None or measured["speedup"] <= 1:
            raise RuntimeError(f"{component} has no verified speedup at the configured batch {batch}; not enabling")
        path = Path(result["engine"]).resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest() != result["sha256"]:
            raise RuntimeError(f"{component} engine changed after verification")
        paths[f"{component}_engine_path"] = str(path)
    destination = RUNTIME_OVERRIDES_FILE
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_load(destination.read_text()) or {} if destination.exists() else {}
    payload.setdefault("model", {}).setdefault("musetalk", {}).update(paths)
    if destination.exists():
        report_dir = Path(next(iter(paths.values()))).parent
        backup = report_dir / ("runtime_overrides-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".yaml.bak")
        shutil.copyfile(destination, backup)
        backup.chmod(0o600)
        print(f"Private settings backup: {backup}")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Enabled verified engines in {destination}; restart the backend to apply.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/tensorrt/musetalk")
    parser.add_argument("--components", nargs="+", choices=("unet", "vae"), default=["unet", "vae"])
    parser.add_argument("--batch-size", type=int, default=8, help="Maximum/optimal batch; the engine also supports batches 1 through this value")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--workspace-mib", type=int, default=1024)
    parser.add_argument("--optimization-level", type=int, choices=range(6), default=2)
    parser.add_argument("--verify-only", action="store_true", help="Recheck existing engines without rebuilding")
    parser.add_argument("--enable", action="store_true", help="Save measured engine paths in local runtime overrides")
    parser.add_argument("--config", type=Path, default=ROOT / "config/config.yaml")
    args = parser.parse_args()
    if args.batch_size < 1 or args.workspace_mib < 1:
        parser.error("batch-size and workspace-mib must be positive")
    try:
        import tensorrt as trt
        import onnx  # noqa: F401 -- required by the PyTorch ONNX exporter
    except ImportError as exc:
        parser.error(f"Optional build dependency missing: {exc.name}; see docs/x86-performance.md")
    import torch
    if not torch.cuda.is_available():
        parser.error("CUDA is required to build and compare MuseTalk engines")
    torch.cuda.set_device(args.device)
    # Model feature loading still uses paths relative to the repository.
    import os
    args.output_dir = args.output_dir.resolve()
    args.config = args.config.resolve()
    os.chdir(ROOT)
    from src.config.loader import load_config
    configured_batch = load_config(str(args.config)).model.batch_size
    if args.enable and configured_batch > args.batch_size:
        parser.error(f"Configured batch {configured_batch} exceeds the engine maximum; pass --batch-size {configured_batch}")
    from src.avatars.musetalk.avatar import load_model
    from src.avatars.musetalk.inference_optimization import TensorRTUNet
    from src.avatars.musetalk.vae_acceleration import TensorRTVAEDecoder
    vae, unet, *_ = load_model()

    class UNetExport(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = unet.model

        def forward(self, sample, encoder_hidden_states):
            return self.model(sample, 0, encoder_hidden_states=encoder_hidden_states, return_dict=False)[0]

    class VAEExport(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = vae.vae

        def forward(self, latents):
            return self.model.decode(latents / vae.scaling_factor, return_dict=False)[0]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "gpu": torch.cuda.get_device_name(args.device), "torch": torch.__version__,
        "cuda": torch.version.cuda, "tensorrt": trt.__version__, "batch_size": args.batch_size,
        "measured_at": datetime.now(timezone.utc).isoformat(), "iterations": 20, "warmup": 5,
        "components": {},
    }
    torch.manual_seed(0)
    with torch.inference_mode():
        for component in args.components:
            onnx_path = args.output_dir / f"{component}.onnx"
            engine_path = args.output_dir / f"{component}-fp16.engine"
            shapes = ({"sample": (8, 32, 32), "encoder_hidden_states": (50, 384)}
                      if component == "unet" else {"latents": (4, 32, 32)})
            samples = tuple(torch.randn(1, *tail, device="cuda", dtype=torch.float16) for tail in shapes.values())
            module = UNetExport() if component == "unet" else VAEExport()
            output_name = "latent" if component == "unet" else "decoded"
            candidate = engine_path if args.verify_only else engine_path.with_suffix(".candidate.engine")
            if not args.verify_only:
                print(f"Exporting/building {component}; output {engine_path}", flush=True)
                torch.onnx.export(
                    module.eval(), samples, str(onnx_path), opset_version=17, dynamo=False,
                    input_names=list(shapes), output_names=[output_name],
                    dynamic_axes={name: {0: "batch"} for name in (*shapes, output_name)},
                )
                build_engine(trt, onnx_path, candidate, shapes, args)
            adapter = TensorRTUNet(unet.model, candidate) if component == "unet" else TensorRTVAEDecoder(vae, candidate)
            batches = {}
            sizes = {1, min(4, args.batch_size), args.batch_size}
            if 1 <= configured_batch <= args.batch_size:
                sizes.add(configured_batch)
            for size in sorted(sizes):
                inputs = tuple(torch.randn(size, *tail, device="cuda", dtype=torch.float16) for tail in shapes.values())
                if component == "unet":
                    original = lambda x, y: unet.model(x, 0, encoder_hidden_states=y).sample
                    accelerated = lambda x, y: adapter(x, 0, encoder_hidden_states=y).sample
                else:
                    original, accelerated = vae.decode_latents, adapter.decode_latents
                batches[str(size)] = compare(torch, original, accelerated, inputs, image_output=component == "vae")
                if adapter._failed:
                    raise RuntimeError(f"{component} fell back to PyTorch; this is not an engine benchmark")
            report["components"][component] = {
                "engine": str(engine_path), "batches": batches,
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }
            if not args.verify_only:
                candidate.replace(engine_path)
            print(f"Verified {component}: {json.dumps(batches)}", flush=True)
    report_path = args.output_dir / "comparison.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    print(f"Comparison saved to {report_path}. Set engine paths only after reviewing the results.")
    if args.enable:
        enable_engines(report, args.config)


if __name__ == "__main__":
    main()
