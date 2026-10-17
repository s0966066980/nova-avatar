#!/usr/bin/env python3
# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Compare CPU chroma compositing with a trusted local Git revision."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="73e7b74e7997042e9139eaea74428ca61abb0e3f")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 3:
        parser.error("iterations must be at least 3")
    import cv2
    import numpy as np
    from src.scene.service import chroma_composite
    source = subprocess.run(
        ["git", "show", f"{args.baseline_ref}:src/scene/service.py"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    namespace = {"__name__": "_nova_compositor_baseline"}
    exec(compile(source, "<trusted-git-baseline>", "exec"), namespace)
    baseline = namespace["chroma_composite"]
    results = []
    for width, height in ((1080, 1920), (720, 1280)):
        yy, xx = np.mgrid[:height, :width]
        person = ((xx - width / 2) / (width * 380 / 1080)) ** 2 + ((yy - height) / (height * 1400 / 1920)) ** 2 < 1
        foreground = np.full((height, width, 3), (60, 200, 80), np.uint8)
        foreground[person] = (120, 110, 150)
        background = np.full_like(foreground, 150)
        if not np.array_equal(baseline(foreground, background), chroma_composite(foreground, background)):
            raise RuntimeError("Portrait fixture changed pixels relative to the baseline")
        functions = {"baseline": baseline, "current": chroma_composite}
        timings = {name: [] for name in functions}
        for _ in range(3):
            for function in functions.values():
                function(foreground, background)
        for iteration in range(args.iterations):
            order = ("baseline", "current") if iteration % 2 == 0 else ("current", "baseline")
            for name in order:
                start = time.perf_counter()
                functions[name](foreground, background)
                timings[name].append((time.perf_counter() - start) * 1000)
        before, after = (statistics.median(timings[name]) for name in ("baseline", "current"))
        results.append({
            "width": width, "height": height, "iterations": args.iterations,
            "opencv_threads": cv2.getNumThreads(), "baseline_median_ms": before,
            "current_median_ms": after, "speedup": before / after, "pixel_equal": True,
        })
    report = {"baseline_ref": args.baseline_ref, "scope": "CPU portrait fixture; excludes inference, encoding and transport", "measurements": results}
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
