# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Measure real avatar frames through resize, scene composition and H.264.

This excludes mouth inference, media scheduling and browser/network work. It
does not change the running service or capture microphone audio.
"""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import av
import cv2
import numpy as np
from aiortc.codecs.h264 import H264Encoder

from src.avatars.video_output import limit_video_height
from src.config.loader import load_config
from src.scene.service import SceneService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--height', type=int)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('.scratch/console-resolution/output-cost.json'))
    args = parser.parse_args()
    cv2.setNumThreads(1)
    config = load_config('config/config_jetson.yaml')
    paths = sorted((Path('data/avatars') / config.model.avatar_id / 'full_imgs').glob('*.png'))[:22]
    frames = [cv2.imread(str(path)) for path in paths]
    assert frames and all(frame is not None for frame in frames)
    scene = SceneService()
    scene.select(config.stage.background_id, fade_seconds=0)
    results = []
    try:
        for height in ([args.height] if args.height is not None else [1280, 960, 720, 540, 450]):
            encoder = H264Encoder()
            timings = []
            for index, original in enumerate(frames):
                start = time.perf_counter()
                resized = limit_video_height(original, height)
                resize_end = time.perf_counter()
                composed = scene.compose(resized, green_screen=True)
                compose_end = time.perf_counter()
                frame = av.VideoFrame.from_ndarray(composed, format='bgr24')
                frame.pts = index * 3600
                frame.time_base = Fraction(1, 90000)
                encoder.encode(frame)
                end = time.perf_counter()
                if index >= 2:
                    timings.append([(resize_end-start)*1000, (compose_end-resize_end)*1000,
                                    (end-compose_end)*1000, (end-start)*1000])
            data = np.asarray(timings)
            results.append({'max_height': height, 'width': resized.shape[1], 'height': resized.shape[0],
                            'resize_median_ms': round(float(np.median(data[:, 0])), 2),
                            'compose_median_ms': round(float(np.median(data[:, 1])), 2),
                            'encode_median_ms': round(float(np.median(data[:, 2])), 2),
                            'total_median_ms': round(float(np.median(data[:, 3])), 2),
                            'total_p95_ms': round(float(np.percentile(data[:, 3], 95)), 2)})
            print(json.dumps(results[-1]), flush=True)
    finally:
        scene.close()
    report = {'source_dimensions': [frames[0].shape[1], frames[0].shape[0]],
              'running_height_limit': config.video.max_height, 'output_only_frame_budget_ms': 40,
              'measurements': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if args.check:
        assert all(row['total_p95_ms'] < 40 for row in results), 'Output alone exceeded the 25fps frame budget'


if __name__ == '__main__':
    main()
