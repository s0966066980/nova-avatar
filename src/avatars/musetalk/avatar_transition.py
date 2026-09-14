"""Visual-only, cursor-preserving MuseTalk speech-to-idle transitions."""
from __future__ import annotations

from enum import Enum
from threading import RLock
from typing import Sequence

import cv2
import numpy as np

from src.utils.logging import logger


class TransitionState(str, Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    SETTLING = "settling"
    PHASE_MATCHING = "phase_matching"
    CROSSFADING = "crossfading"


class AvatarTransitionController:
    """Plan settling against upcoming frames without changing the frame cursor."""

    def __init__(self, source_frames: Sequence[np.ndarray], masks: Sequence[np.ndarray],
                 mask_coords: Sequence[Sequence[int]] | None,
                 face_coords: Sequence[Sequence[int]] | None, *, mouth_controller=None,
                 enabled=True, fps=25, settling_min_frames=4, settling_max_frames=6,
                 phase_matching_enabled=True, phase_temporal_penalty=0.015,
                 micro_crossfade_enabled=True, micro_crossfade_frames=2,
                 micro_crossfade_fullframe_max_diff=18.0, opening_frames=2):
        if not source_frames or len(source_frames) != len(masks):
            raise ValueError("source_frames and masks must be non-empty and equal length")
        self._source_frames = tuple(np.asarray(f) for f in source_frames)
        self._masks = tuple(np.asarray(m) for m in masks)
        self._mask_coords = tuple(mask_coords) if mask_coords is not None else None
        self._face_coords = tuple(face_coords) if face_coords is not None else None
        self._mouth_controller = mouth_controller
        self.enabled = bool(enabled)
        self.fps = max(1, int(fps))
        self.settling_min_frames = max(1, int(settling_min_frames))
        self.settling_max_frames = max(self.settling_min_frames, int(settling_max_frames))
        self.phase_matching_enabled = bool(phase_matching_enabled)
        self.phase_temporal_penalty = float(phase_temporal_penalty)
        self.micro_crossfade_enabled = bool(micro_crossfade_enabled)
        self.micro_crossfade_frames = max(0, int(micro_crossfade_frames))
        self.micro_crossfade_fullframe_max_diff = float(micro_crossfade_fullframe_max_diff)
        self.opening_frames = max(1, int(opening_frames))
        self._full_masks = tuple(self._build_full_mask(i) for i in range(len(self._source_frames)))
        self._source_pose_descriptors = tuple(self._descriptor(f, i) for i, f in enumerate(self._source_frames))
        self._lock = RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.state = TransitionState.IDLE
            self._previous_is_speech = False
            self._previous_output = self._last_speech_frame = self._crossfade_origin = None
            self._last_speech_index = self._last_source_index = None
            self._playback_direction = 1
            self._settling_step = self._settling_total = self._crossfade_step = 0
            self._planned_idle_index = self._planned_idle_offset = self._planned_match_score = None
            self._generation = None
            if self._mouth_controller is not None:
                self._mouth_controller.reset()

    def _reset_visual_transition(self) -> None:
        self.state = TransitionState.IDLE
        self._previous_is_speech = False
        self._previous_output = self._last_speech_frame = self._crossfade_origin = None
        self._last_speech_index = None
        self._settling_step = self._settling_total = self._crossfade_step = 0
        self._planned_idle_index = self._planned_idle_offset = self._planned_match_score = None
        if self._mouth_controller is not None:
            self._mouth_controller.reset()

    def compose(self, target_frame: np.ndarray, *, index: int, is_speech: bool,
                frame_type: int, eventpoint: dict | None) -> np.ndarray:
        with self._lock:
            target = np.asarray(target_frame)
            if not self.enabled or target.ndim != 3 or target.shape[2] != 3:
                return target.copy()
            self._handle_generation(eventpoint)
            index %= len(self._source_frames)
            self._update_playback_direction(index)
            if not is_speech and frame_type > 1:
                self._reset_visual_transition()
                return target.copy()
            if is_speech:
                cancelled = self.state in (TransitionState.SETTLING, TransitionState.CROSSFADING)
                output = self._mouth(target, index, True, eventpoint)
                if cancelled:
                    logger.info("[AvatarTransition] transition cancelled by new speech")
                self.state = TransitionState.SPEAKING
                self._last_speech_frame, self._last_speech_index = output.copy(), index
                self._previous_output, self._previous_is_speech = output.copy(), True
                return output
            if self._previous_is_speech:
                planned, candidate, score = self._plan_idle_return(
                    self._last_speech_frame,
                    self._last_speech_index,
                    index,
                )
                self._settling_total, self._settling_step = planned, 0
                self._planned_idle_index, self._planned_idle_offset, self._planned_match_score = candidate, planned, score
                self.state = TransitionState.SETTLING
                logger.info("[AvatarTransition] SPEAKING -> SETTLING idx=%s planned=%s target=%s score=%.3f", index, planned, candidate, score)
                output = self._mouth(target, index, False, eventpoint, planned)
            elif self.state == TransitionState.CROSSFADING:
                output = self._apply_micro_crossfade(self._mouth(target, index, False, eventpoint), index)
            else:
                output = self._mouth(target, index, False, eventpoint)
            if self.state == TransitionState.SETTLING:
                self._settling_step += 1
                if self._settling_step >= self._settling_total:
                    if self.micro_crossfade_enabled and self.micro_crossfade_frames:
                        self.state, self._crossfade_origin, self._crossfade_step = TransitionState.CROSSFADING, output.copy(), 0
                        logger.info("[AvatarTransition] SETTLING -> CROSSFADING")
                    else:
                        self.state = TransitionState.IDLE
            self._previous_is_speech, self._previous_output = False, output.copy()
            return output

    def _mouth(self, frame, index, speech, eventpoint, transition_frames=None):
        if self._mouth_controller is None:
            return np.asarray(frame).copy()
        return self._mouth_controller.compose(frame, index=index, is_speech=speech,
                                              eventpoint=eventpoint, transition_frames=transition_frames)

    def _handle_generation(self, eventpoint):
        generation = eventpoint.get("generation") if isinstance(eventpoint, dict) else None
        if generation is not None and self._generation is not None and generation != self._generation:
            self._reset_visual_transition()
        if generation is not None:
            self._generation = generation

    def _update_playback_direction(self, index):
        previous, size = self._last_source_index, len(self._source_frames)
        if previous is not None:
            if index > previous:
                self._playback_direction = 1
            elif index < previous:
                self._playback_direction = -1
            elif index == 0:
                self._playback_direction = 1
            elif index == size - 1:
                self._playback_direction = -1
        self._last_source_index = index

    @staticmethod
    def _next_pingpong_index(index, direction, size):
        if size <= 1:
            return 0, 1
        next_index = index + direction
        if next_index >= size:
            return size - 1, -1
        if next_index < 0:
            return 0, 1
        return next_index, direction

    def _future_index(self, index, steps):
        direction = self._playback_direction
        for _ in range(max(0, steps)):
            index, direction = self._next_pingpong_index(index, direction, len(self._source_frames))
        return index

    def _plan_idle_return(self, speech_frame, speech_index, first_idle_index):
        fallback = self.settling_min_frames
        if speech_frame is None or not self.phase_matching_enabled:
            return fallback, self._future_index(first_idle_index, fallback - 1), float("inf")
        self.state = TransitionState.PHASE_MATCHING
        reference_index = first_idle_index if speech_index is None else speech_index
        descriptor = self._descriptor(speech_frame, reference_index)
        best = (float("inf"), fallback, self._future_index(first_idle_index, fallback - 1))
        for total in range(self.settling_min_frames, self.settling_max_frames + 1):
            candidate = self._future_index(first_idle_index, total - 1)
            score = float(np.mean(np.abs(descriptor - self._source_pose_descriptors[candidate])))
            score += (total - self.settling_min_frames) * self.phase_temporal_penalty
            if score < best[0]:
                best = score, total, candidate
        return best[1], best[2], best[0]

    def _pose_roi(self, index, width, height):
        coords = self._face_coords[index] if self._face_coords is not None else None
        if coords is None or len(coords) != 4:
            return 0, 0, width, height
        x0, y0, x1, y1 = (int(v) for v in coords)
        if x1 <= x0 or y1 <= y0:
            return 0, 0, width, height
        fw, fh = x1 - x0, y1 - y0
        return max(0, int(x0 - fw * .6)), max(0, int(y0 - fh * .25)), min(width, int(x1 + fw * .6)), min(height, int(y1 + fh * 1.2))

    def _descriptor(self, frame, index):
        image = np.asarray(frame)
        x0, y0, x1, y1 = self._pose_roi(index, image.shape[1], image.shape[0])
        crop = image[y0:y1, x0:x1] if x1 > x0 and y1 > y0 else image
        gray = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
        mask = cv2.resize(self._full_masks[index][y0:y1, x0:x1], (64, 64), interpolation=cv2.INTER_AREA) if x1 > x0 and y1 > y0 else 0
        weights = 1.0 - .9 * np.clip(mask, 0, 1)
        mean = float((gray * weights).sum() / max(weights.sum(), 1.0))
        std = float(np.sqrt((((gray - mean) ** 2 * weights).sum() / max(weights.sum(), 1.0))) + 1e-6)
        return ((gray - mean) / std) * weights

    def _apply_micro_crossfade(self, target, index):
        origin = self._crossfade_origin
        if origin is None or origin.shape != target.shape:
            self.state = TransitionState.IDLE
            return target.copy()
        self._crossfade_step += 1
        t = min(1., self._crossfade_step / self.micro_crossfade_frames)
        alpha = t * t * (3. - 2. * t)
        a, b = cv2.resize(origin, (96, 96)), cv2.resize(target, (96, 96))
        mad = float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))
        if mad <= self.micro_crossfade_fullframe_max_diff:
            output = cv2.addWeighted(origin, 1. - alpha, target, alpha, 0)
        else:
            mask = self._full_masks[index][..., None] * alpha
            output = target.copy()
            active = mask[..., 0] > 0
            mixed = origin.astype(np.float32) * (1. - mask) + target.astype(np.float32) * mask
            output[active] = np.clip(mixed[active], 0, 255).astype(output.dtype)
        if self._crossfade_step >= self.micro_crossfade_frames:
            output, self.state, self._crossfade_origin = target.copy(), TransitionState.IDLE, None
            logger.info("[AvatarTransition] CROSSFADING -> IDLE")
        return output

    def _build_full_mask(self, index):
        source, mask = self._source_frames[index], self._masks[index]
        if mask.shape[:2] == source.shape[:2]:
            return self._feather(mask)
        canvas = np.zeros(source.shape[:2], dtype=np.uint8)
        if self._mask_coords is not None and len(self._mask_coords[index]) == 4:
            x0, y0, x1, y1 = (int(v) for v in self._mask_coords[index])
            x0, x1 = max(0, x0), min(source.shape[1], x1)
            y0, y1 = max(0, y0), min(source.shape[0], y1)
            if x1 > x0 and y1 > y0:
                resized = cv2.resize(mask, (x1 - x0, y1 - y0))
                canvas[y0:y1, x0:x1] = resized[..., 0] if resized.ndim == 3 else resized
        return self._feather(canvas)

    @staticmethod
    def _feather(mask):
        values = np.asarray(mask, dtype=np.float32)
        if values.ndim == 3:
            values = values[..., 0]
        if values.size and values.max() > 1:
            values /= 255.
        return np.clip(values, 0., 1.)
