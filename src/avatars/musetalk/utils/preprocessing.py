# Portions derived from MuseTalk.
# Copyright (c) 2024 Tencent Music Entertainment Group.
# Licensed under the MIT License.
# Modified by HongXian0903 for integration with Nova Avatar, 2026.

from functools import lru_cache
from pathlib import Path
import logging
import numpy as np
import cv2
import pickle
import torch
from tqdm import tqdm

from .face_detection.detection.sfd.sfd_detector import SFDDetector

logger = logging.getLogger(__name__)

# Get the project root directory
musetalk_dir = Path(__file__).resolve().parents[1]
project_root = musetalk_dir.parents[2]


@lru_cache(maxsize=1)
def _face_detector():
    checkpoint = project_root / "models/musetalk/s3fd-619a316812/s3fd-619a316812.pth"
    cached_checkpoint = Path(torch.hub.get_dir()) / "checkpoints/s3fd-619a316812.pth"
    weights = next((candidate for candidate in (checkpoint, cached_checkpoint) if candidate.is_file()), None)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if weights is not None:
        return SFDDetector(device=device, path_to_detector=str(weights))
    return SFDDetector(device=device)


@lru_cache(maxsize=1)
def _pose_runtime():
    """Use the original landmark crop when OpenMMLab is installed."""
    try:
        from mmpose.apis import inference_topdown, init_model
        from mmpose.structures import merge_data_samples
    except ImportError:
        logger.info("mmpose is unavailable; using the bundled face detector for avatar crops")
        return None

    config = musetalk_dir / "utils/dwpose/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py"
    checkpoint = project_root / "models/musetalk/dwpose/dw-ll_ucoco_384.pth"
    try:
        model = init_model(str(config), str(checkpoint), device="cuda" if torch.cuda.is_available() else "cpu")
    except Exception:
        logger.exception("Could not initialize mmpose; using face detector crops")
        return None
    return model, inference_topdown, merge_data_samples

# maker if the bbox is not sufficient 
coord_placeholder = (0.0,0.0,0.0,0.0)

def resize_landmark(landmark, w, h, new_w, new_h):
    w_ratio = new_w / w
    h_ratio = new_h / h
    landmark_norm = landmark / [w, h]
    landmark_resized = landmark_norm * [new_w, new_h]
    return landmark_resized

def read_imgs(img_list):
    frames = []
    print('reading images...')
    for img_path in tqdm(img_list):
        frame = cv2.imread(img_path)
        if frame is None:
            raise ValueError(f"Cannot read avatar frame: {img_path}")
        frames.append(frame)
    return frames

def _landmark_bbox(frame, pose_runtime, upperbondrange):
    if pose_runtime is None:
        return None, None
    model, inference_topdown, merge_data_samples = pose_runtime
    try:
        results = merge_data_samples(inference_topdown(model, frame))
        landmarks = results.pred_instances.keypoints[0][23:91].astype(np.int32)
        half_face = landmarks[29]
        range_minus = int((landmarks[30] - landmarks[29])[1])
        range_plus = int((landmarks[29] - landmarks[28])[1])
        upper = max(0, 2 * int(half_face[1]) + upperbondrange - int(np.max(landmarks[:, 1])))
        box = (
            int(np.min(landmarks[:, 0])), upper,
            int(np.max(landmarks[:, 0])), int(np.max(landmarks[:, 1])),
        )
        if box[0] >= 0 and box[2] > box[0] and box[3] > box[1]:
            return box, (range_minus, range_plus)
    except (IndexError, KeyError, ValueError, AttributeError):
        logger.debug("No usable mmpose landmarks for frame; using face detector crop", exc_info=True)
    return None, None


def _detector_bbox(frame, detector, upperbondrange):
    # SFD expects RGB; OpenCV loads avatar frames as BGR.
    faces = detector.detect_from_image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if len(faces) == 0:
        return coord_placeholder
    x1, y1, x2, y2 = max(faces, key=lambda face: face[4])[:4]
    width, height = x2 - x1, y2 - y1
    frame_height, frame_width = frame.shape[:2]
    box = (
        max(0, round(x1 - width * 0.02)),
        max(0, round(y1 - height * 0.06 + upperbondrange)),
        min(frame_width, round(x2 + width * 0.02)),
        min(frame_height, round(y2 + height * 0.06)),
    )
    return box if box[2] > box[0] and box[3] > box[1] else coord_placeholder


def _process_frames(img_list, upperbondrange):
    frames = read_imgs(img_list)
    coords_list = []
    average_range_minus = []
    average_range_plus = []
    detector = _face_detector()
    pose_runtime = _pose_runtime()
    for frame in tqdm(frames):
        detected = _detector_bbox(frame, detector, upperbondrange)
        if detected == coord_placeholder:
            coords_list.append(coord_placeholder)
            continue
        landmark_box, ranges = _landmark_bbox(frame, pose_runtime, upperbondrange)
        coords_list.append(landmark_box or detected)
        if ranges is not None:
            average_range_minus.append(ranges[0])
            average_range_plus.append(ranges[1])
    return coords_list, frames, average_range_minus, average_range_plus


def _range_text(frame_count, lower_ranges, upper_ranges, upperbondrange):
    lower = int(sum(lower_ranges) / len(lower_ranges)) if lower_ranges else 0
    upper = int(sum(upper_ranges) / len(upper_ranges)) if upper_ranges else 0
    return f"Total frame:「{frame_count}」 Manually adjust range : [ -{lower}~{upper} ] , the current value: {upperbondrange}"


def get_bbox_range(img_list, upperbondrange=0):
    _, frames, lower_ranges, upper_ranges = _process_frames(img_list, upperbondrange)
    return _range_text(len(frames), lower_ranges, upper_ranges, upperbondrange)


def get_landmark_and_bbox(img_list, upperbondrange=0):
    coords_list, frames, lower_ranges, upper_ranges = _process_frames(img_list, upperbondrange)
    print(_range_text(len(frames), lower_ranges, upper_ranges, upperbondrange))
    return coords_list, frames
    

if __name__ == "__main__":
    img_list = ["./results/lyria/00000.png","./results/lyria/00001.png","./results/lyria/00002.png","./results/lyria/00003.png"]
    crop_coord_path = "./coord_face.pkl"
    coords_list,full_frames = get_landmark_and_bbox(img_list)
    with open(crop_coord_path, 'wb') as f:
        pickle.dump(coords_list, f)
        
    for bbox, frame in zip(coords_list,full_frames):
        if bbox == coord_placeholder:
            continue
        x1, y1, x2, y2 = bbox
        crop_frame = frame[y1:y2, x1:x2]
        print('Cropped shape', crop_frame.shape)
        
        #cv2.imwrite(path.join(save_dir, '{}.png'.format(i)),full_frames[i][0][y1:y2, x1:x2])
    print(coords_list)
