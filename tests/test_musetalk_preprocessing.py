# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

import cv2
import numpy as np


def test_musetalk_preprocessing_uses_bundled_face_detector_without_mmpose(tmp_path, monkeypatch):
    from src.avatars.musetalk.utils import preprocessing

    frame = np.full((240, 320, 3), (50, 180, 50), np.uint8)
    path = tmp_path / "00000000.png"
    assert cv2.imwrite(str(path), frame)

    class Detector:
        def detect_from_image(self, _image):
            return [np.array([100, 50, 200, 180, 0.99])]

    monkeypatch.setattr(preprocessing, "_face_detector", lambda: Detector())
    monkeypatch.setattr(preprocessing, "_pose_runtime", lambda: None)
    coordinates, frames = preprocessing.get_landmark_and_bbox([str(path)], 0)
    assert len(frames) == 1
    assert coordinates == [(98, 42, 202, 188)]
