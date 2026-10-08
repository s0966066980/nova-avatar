# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Bound output size after avatar coordinates and transitions are resolved."""
import cv2


def output_dimensions(width: int, height: int, max_height: int = 0):
    """Return the encoder dimensions used by the renderer, without upscaling."""
    if not max_height or height <= max_height:
        return width, height
    target_height = max(2, int(max_height) // 2 * 2)
    target_width = max(2, round(width * target_height / height) // 2 * 2)
    return target_width, target_height


def limit_video_height(frame, max_height: int = 0):
    """Shrink only, keeping the source aspect ratio and even encoder dimensions."""
    height, width = frame.shape[:2]
    if not max_height or height <= max_height:
        return frame
    target_width, target_height = output_dimensions(width, height, max_height)
    # Exact 2:1 area reductions use OpenCV's fast integer path. Start there
    # before a fractional reduction so filtering the full portrait costs less.
    # Keep area filtering at every step to avoid aliasing hair and green edges.
    reduced = frame
    while (
        height % 2 == 0 and width % 2 == 0
        and target_height <= height // 2 and target_width <= width // 2
    ):
        width, height = width // 2, height // 2
        reduced = cv2.resize(reduced, (width, height), interpolation=cv2.INTER_AREA)
    if (width, height) == (target_width, target_height):
        return reduced
    return cv2.resize(reduced, (target_width, target_height), interpolation=cv2.INTER_AREA)
