# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
"""Minimal real-model probe for concurrent microphone endpoint detectors."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from src.config.schema import VADConfig
from src.vad.service import create_segmenter

segments = [create_segmenter(VADConfig()) for _ in range(2)]
for segment in segments:
    segment.vad.ensure_ready()
print('shared_engine', segments[0].vad is segments[1].vad, flush=True)
barrier = Barrier(2)

def run(segment):
    barrier.wait()
    for index in range(2000):
        if index % 5 == 0:
            segment.reset()
        list(segment.process(np.zeros(512, dtype=np.int16)))
    return True

with ThreadPoolExecutor(max_workers=2) as pool:
    print(list(pool.map(run, segments)), flush=True)
