# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Optional output scaling after avatar coordinates and transitions resolve."""
import cv2


def output_dimensions(width: int, height: int, max_height: int = 0):
    """Return the encoder dimensions used by the renderer, without upscaling."""
    if not max_height or height <= max_height:
        return width, height
    target_height = max(2, int(max_height) // 2 * 2)
    target_width = max(2, round(width * target_height / height) // 2 * 2)
    return target_width, target_height

def limit_video_height(frame, max_height: int = 0):
    """Shrink only, preserving aspect ratio and even encoder dimensions."""
    height, width = frame.shape[:2]
    if not max_height or height <= max_height:
        return frame
    target_height = max(2, int(max_height) // 2 * 2)
    target_width = max(2, round(width * target_height / height) // 2 * 2)
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
