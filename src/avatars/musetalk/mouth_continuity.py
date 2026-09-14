"""Low-cost temporal compositing for MuseTalk mouth transitions.

The controller owns only visual state.  It never waits for audio, touches a
media queue, or runs inference, so it cannot add latency to the audio master.
"""
from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np


class MouthContinuityController:
    """Blend only the mouth ROI when MuseTalk and idle frames meet."""

    def __init__(
        self,
        source_frames: Sequence[np.ndarray],
        masks: Sequence[np.ndarray],
        mask_coords: Sequence[Sequence[int]] | None = None,
        *,
        neutral_frames: Sequence[np.ndarray] | None = None,
        gap_grace_frames: int = 2,
        opening_frames: int = 2,
        closing_frames: int = 4,
        settling_frames: int | None = None,
        align_idle_return: bool = True,
    ) -> None:
        if len(source_frames) != len(masks):
            raise ValueError("source_frames and masks must have the same length")
        if mask_coords is not None and len(mask_coords) != len(masks):
            raise ValueError("mask_coords and masks must have the same length")
        if neutral_frames is not None and len(neutral_frames) != len(source_frames):
            raise ValueError("neutral_frames and source_frames must have the same length")
        self._source_frames = tuple(np.asarray(frame) for frame in source_frames)
        self._masks = tuple(np.asarray(mask) for mask in masks)
        self._mask_coords = tuple(mask_coords) if mask_coords is not None else None
        self._neutral_frames = (
            tuple(np.asarray(frame) for frame in neutral_frames)
            if neutral_frames is not None
            else None
        )
        self._gap_grace_frames = max(0, int(gap_grace_frames))
        self._opening_frames = max(1, int(opening_frames))
        self._settling_enabled = settling_frames is not None
        self._closing_frames = max(
            1,
            int(closing_frames if settling_frames is None else settling_frames),
        )
        self._align_idle_return = bool(align_idle_return)
        self._full_masks = tuple(self._build_full_mask(index) for index in range(len(masks)))
        self._mouth_boxes = tuple(self._mouth_box(mask) for mask in self._full_masks)
        self.reset()

    def reset(self) -> None:
        self._previous_frame: np.ndarray | None = None
        self._previous_box: tuple[int, int, int, int] | None = None
        self._previous_is_speech = False
        self._generation = None
        self._gap_remaining = 0
        self._transition_origin: np.ndarray | None = None
        self._transition_origin_box: tuple[int, int, int, int] | None = None
        self._transition_target: np.ndarray | None = None
        self._transition_step = 0
        self._transition_total = 0
        self._transition_follows_target = False
        self._transition_easing = "linear"

    def compose(
        self,
        target_frame: np.ndarray,
        *,
        index: int,
        is_speech: bool,
        eventpoint: dict | None,
        transition_frames: int | None = None,
    ) -> np.ndarray:
        """Return a frame with a bounded, mask-only temporal transition."""
        target = np.asarray(target_frame)
        if target.ndim != 3 or target.shape[2] != 3 or not self._source_frames:
            return target.copy()
        index %= len(self._source_frames)

        generation = (
            eventpoint.get("generation")
            if isinstance(eventpoint, dict)
            else None
        )
        if (
            generation is not None
            and self._generation is not None
            and generation != self._generation
        ):
            self.reset()
        if generation is not None:
            self._generation = generation

        mask = self._full_masks[index]
        box = self._mouth_boxes[index]
        if mask.shape != target.shape[:2] or box is None:
            return target.copy()

        if self._previous_frame is None or self._previous_frame.shape != target.shape:
            output = target.copy()
            self._remember(output, is_speech, box)
            return output

        if is_speech:
            if not self._previous_is_speech:
                self._start_transition(target, self._opening_frames)
            output = self._transition_or_target(target, mask, box)
            self._gap_remaining = 0
            self._remember(output, True, box)
            return output

        if self._previous_is_speech:
            self._gap_remaining = self._gap_grace_frames
            total_frames = self._closing_frames if transition_frames is None else max(1, int(transition_frames))
            self._start_transition(
                self._neutral_target(index, target),
                total_frames,
                follows_target=self._settling_enabled,
                easing="smoothstep" if self._settling_enabled else "linear",
            )

        if self._gap_remaining > 0:
            self._gap_remaining -= 1
            output = self._blend_mouth(
                self._align_previous_mouth(self._previous_frame, self._previous_box, target, box),
                target,
                mask,
                0.0,
                box=box,
            )
        else:
            output = self._transition_or_target(target, mask, box)
        self._remember(output, False, box)
        return output

    def _remember(
        self,
        frame: np.ndarray,
        is_speech: bool,
        box: tuple[int, int, int, int],
    ) -> None:
        self._previous_frame = frame.copy()
        self._previous_box = box
        self._previous_is_speech = bool(is_speech)

    def _start_transition(
        self,
        target: np.ndarray,
        total: int,
        *,
        follows_target: bool = False,
        easing: str = "linear",
    ) -> None:
        self._transition_origin = (
            self._previous_frame.copy()
            if self._previous_frame is not None
            else target.copy()
        )
        self._transition_origin_box = self._previous_box
        self._transition_target = target.copy()
        self._transition_step = 0
        self._transition_total = max(1, int(total))
        self._transition_follows_target = bool(follows_target)
        self._transition_easing = easing

    def _transition_or_target(
        self,
        target: np.ndarray,
        mask: np.ndarray,
        box: tuple[int, int, int, int],
    ) -> np.ndarray:
        if self._transition_origin is None or self._transition_target is None:
            return target.copy()
        if self._transition_step >= self._transition_total:
            self._transition_origin = None
            self._transition_origin_box = None
            self._transition_target = None
            return target.copy()
        self._transition_step += 1
        progress = self._transition_step / self._transition_total
        alpha = (
            progress * progress * (3.0 - 2.0 * progress)
            if self._transition_easing == "smoothstep"
            else progress
        )
        transition_target = (
            target if self._transition_follows_target else self._transition_target
        )
        output = self._blend_mouth(
            self._align_previous_mouth(
                self._transition_origin,
                self._transition_origin_box,
                target,
                box,
            ),
            transition_target,
            mask,
            alpha,
            base_frame=target,
            box=box,
        )
        if self._transition_step >= self._transition_total:
            self._transition_origin = None
            self._transition_origin_box = None
            self._transition_target = None
        return output

    @staticmethod
    def _mouth_box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
        ys, xs = np.nonzero(np.asarray(mask) > 0)
        if not len(xs) or not len(ys):
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1

    def _align_previous_mouth(
        self,
        previous: np.ndarray,
        previous_box: tuple[int, int, int, int] | None,
        target: np.ndarray,
        current_box: tuple[int, int, int, int],
    ) -> np.ndarray:
        """Move a previous mouth patch into the current idle-frame mouth box.

        Invalid or implausibly large transforms deliberately fall back to the
        current target. That prevents a stale mouth from being warped across a
        cut or a bad mask while preserving the audio-first rendering path.
        """
        if not self._align_idle_return:
            return previous
        if previous_box is None or previous.shape != target.shape:
            return target
        px0, py0, px1, py1 = previous_box
        cx0, cy0, cx1, cy1 = current_box
        previous_width, previous_height = px1 - px0, py1 - py0
        current_width, current_height = cx1 - cx0, cy1 - cy0
        if min(previous_width, previous_height, current_width, current_height) <= 0:
            return target
        previous_center_x = (px0 + px1) / 2.0
        previous_center_y = (py0 + py1) / 2.0
        current_center_x = (cx0 + cx1) / 2.0
        current_center_y = (cy0 + cy1) / 2.0
        shift_ratio = np.hypot(
            current_center_x - previous_center_x,
            current_center_y - previous_center_y,
        ) / previous_width
        scale = np.sqrt(
            (current_width / previous_width) * (current_height / previous_height)
        )
        if not np.isfinite(shift_ratio) or not np.isfinite(scale):
            return target
        if shift_ratio > 0.25 or not 0.85 <= scale <= 1.15:
            return target
        patch = previous[py0:py1, px0:px1]
        if patch.shape[:2] != (previous_height, previous_width):
            return target
        try:
            aligned_patch = cv2.resize(
                patch,
                (current_width, current_height),
                interpolation=cv2.INTER_LINEAR,
            )
        except cv2.error:
            return target
        aligned = target.copy()
        aligned[cy0:cy1, cx0:cx1] = aligned_patch
        return aligned

    @staticmethod
    def _blend_mouth(
        previous: np.ndarray,
        target: np.ndarray,
        mask: np.ndarray,
        alpha: float,
        *,
        base_frame: np.ndarray | None = None,
        box: tuple[int, int, int, int] | None = None,
    ) -> np.ndarray:
        output = (base_frame if base_frame is not None else target).copy()
        if box is None:
            ys, xs = np.nonzero(np.asarray(mask) > 0)
            if not len(xs) or not len(ys):
                return output
            box = (
                int(xs.min()),
                int(ys.min()),
                int(xs.max()) + 1,
                int(ys.max()) + 1,
            )
        x0, y0, x1, y1 = box
        mask_roi = np.asarray(mask[y0:y1, x0:x1])
        active = mask_roi > 0
        weights = mask_roi.astype(np.float32, copy=False)
        if weights.max(initial=0.0) > 1.0:
            weights /= 255.0
        weights = np.clip(weights * float(alpha), 0.0, 1.0)
        if not np.any(active):
            return output
        old = previous[y0:y1, x0:x1].astype(np.float32, copy=False)
        new = target[y0:y1, x0:x1].astype(np.float32, copy=False)
        mixed = old * (1.0 - weights[..., None]) + new * weights[..., None]
        output_roi = output[y0:y1, x0:x1]
        output_roi[active] = np.clip(mixed[active], 0, 255).astype(output.dtype)
        return output

    def _neutral_target(self, index: int, target: np.ndarray) -> np.ndarray:
        if self._neutral_frames is None:
            return target
        neutral = self._neutral_frames[index]
        if neutral.shape != target.shape:
            return target
        return neutral

    def _build_full_mask(self, index: int) -> np.ndarray:
        mask = self._masks[index]
        source = self._source_frames[index]
        if mask.shape[:2] == source.shape[:2]:
            return self._feather(mask)
        if self._mask_coords is None:
            return np.zeros(source.shape[:2], dtype=np.float32)
        coords = tuple(int(value) for value in self._mask_coords[index])
        if len(coords) != 4:
            return np.zeros(source.shape[:2], dtype=np.float32)
        x0, y0, x1, y1 = coords
        x0 = max(0, min(source.shape[1], x0))
        x1 = max(x0, min(source.shape[1], x1))
        y0 = max(0, min(source.shape[0], y0))
        y1 = max(y0, min(source.shape[0], y1))
        canvas = np.zeros(source.shape[:2], dtype=np.uint8)
        if x1 > x0 and y1 > y0:
            resized = cv2.resize(mask, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
            if resized.ndim == 3:
                resized = resized[..., 0]
            canvas[y0:y1, x0:x1] = np.asarray(resized, dtype=np.uint8)
        return self._feather(canvas)

    @staticmethod
    def _feather(mask: np.ndarray) -> np.ndarray:
        values = np.asarray(mask, dtype=np.float32)
        if values.ndim == 3:
            values = values[..., 0]
        maximum = float(values.max()) if values.size else 0.0
        if maximum > 1.0:
            values /= 255.0
        return np.clip(values, 0.0, 1.0)
