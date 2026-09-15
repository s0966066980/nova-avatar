# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""
VAD 端點檢測（流式切句）

與具體引擎解耦：只要傳入任意 BaseVAD 例項，就能把連續音訊切成語音片段。
邏輯是常見的「觸發 + 掛起（hangover）」狀態機：

    連續 speech_start_ms 判定為語音   -> 進入說話狀態，並把前面 speech_pad_ms 的音訊補回來
    連續 min_silence_ms 判定為靜音    -> 結束當前片段，尾部保留 speech_pad_ms
    片段時長 < min_speech_ms          -> 視為噪聲丟棄
    片段時長 >= max_speech_ms         -> 強制切斷，避免一直說不結束
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

import numpy as np

from src.utils.logging import logger
from src.vad.base import AudioLike, BaseVAD, to_int16


@dataclass
class SpeechSegment:
    """一段檢測到的語音"""
    start_ms: int
    end_ms: int
    audio: np.ndarray = field(repr=False)
    sample_rate: int = 16000
    speech_ms: int = 0  # 片段裡真正判定為語音的時長（不含 padding / 中間停頓）

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class VADSegmenter:
    """基於 VAD 的流式端點檢測器"""

    def __init__(
        self,
        vad: BaseVAD,
        speech_start_ms: int = 100,
        min_speech_ms: int = 250,
        min_silence_ms: int = 500,
        speech_pad_ms: int = 150,
        max_speech_ms: int = 15000,
    ):
        """
        Args:
            vad: Silero VAD 引擎例項
            speech_start_ms: 連續多久判定為語音才算開始說話
            min_speech_ms: 片段最短時長，短於它的當噪聲丟棄
            min_silence_ms: 連續多久靜音判定說完了（端點）
            speech_pad_ms: 片段前後各保留多少音訊，避免吃字
            max_speech_ms: 單段最長時長，超過強制切斷（0 表示不限制）
        """
        self.vad = vad
        self.frame_ms = vad.frame_ms
        self.speech_start_ms = int(speech_start_ms)
        self.min_speech_ms = int(min_speech_ms)
        self.min_silence_ms = int(min_silence_ms)
        self.speech_pad_ms = int(speech_pad_ms)
        self.max_speech_ms = int(max_speech_ms)

        self._pad_frames = self._ms_to_frames(self.speech_pad_ms)
        self._start_frames = max(1, self._ms_to_frames(self.speech_start_ms))
        self._silence_frames_needed = max(1, self._ms_to_frames(self.min_silence_ms))

        # 觸發前的回看緩衝：需要同時裝下判定用的幀和補償用的 padding
        self._preroll: deque = deque(maxlen=self._pad_frames + self._start_frames)
        self._pending = np.zeros(0, dtype=np.int16)  # 不足一幀的尾巴
        self._segment: List[np.ndarray] = []
        self._seg_start_frame = 0
        self._frame_index = 0       # 已消費的幀數（= 當前時間軸）
        self._speech_run = 0        # 連續語音幀數
        self._silence_run = 0       # 連續靜音幀數
        self._seg_speech_frames = 0  # 當前片段內的語音幀數（判斷 min_speech_ms 用）
        self._triggered = False

    # ------------------------------------------------------------------ 屬性

    def _ms_to_frames(self, ms: int) -> int:
        return int(math.ceil(max(0, ms) / self.frame_ms))

    @property
    def is_speaking(self) -> bool:
        """當前是否處於說話狀態"""
        return self._triggered

    @property
    def position_ms(self) -> int:
        """已處理的時長（毫秒）"""
        return self._frame_index * self.frame_ms

    # ------------------------------------------------------------------ 主流程

    def reset(self):
        """重置狀態機與引擎狀態（換會話 / 換音訊時呼叫）"""
        self.vad.reset()
        self._preroll.clear()
        self._pending = np.zeros(0, dtype=np.int16)
        self._segment = []
        self._seg_start_frame = 0
        self._frame_index = 0
        self._speech_run = 0
        self._silence_run = 0
        self._seg_speech_frames = 0
        self._triggered = False

    def process(self, audio: AudioLike) -> Iterator[SpeechSegment]:
        """
        送入任意長度的音訊（bytes 或 int16 陣列），產出已經結束的語音片段

        不足一幀的部分會留到下次呼叫，所以可以直接喂 WebRTC / WebSocket 的音訊塊。
        """
        chunk = to_int16(audio)
        if len(self._pending):
            chunk = np.concatenate([self._pending, chunk])

        step = self.vad.frame_samples
        total = (len(chunk) // step) * step
        self._pending = chunk[total:].copy()

        for start in range(0, total, step):
            segment = self._push_frame(chunk[start:start + step])
            if segment is not None:
                yield segment

    def flush(self) -> Iterator[SpeechSegment]:
        """音訊結束時呼叫：把還沒閉合的片段吐出來"""
        if self._triggered:
            segment = self._close_segment(trim_trailing_silence=True)
            if segment is not None:
                yield segment
        self._pending = np.zeros(0, dtype=np.int16)

    # ------------------------------------------------------------------ 狀態機

    def _push_frame(self, frame: np.ndarray) -> Optional[SpeechSegment]:
        is_speech = self.vad.is_speech(frame)
        self._frame_index += 1

        if not self._triggered:
            self._preroll.append(frame)
            self._speech_run = self._speech_run + 1 if is_speech else 0

            if self._speech_run >= self._start_frames:
                self._triggered = True
                self._segment = list(self._preroll)
                self._seg_start_frame = self._frame_index - len(self._segment)
                self._seg_speech_frames = self._speech_run
                self._preroll.clear()
                self._silence_run = 0
                logger.debug(f'[VAD] 檢測到語音開始 @ {self._seg_start_frame * self.frame_ms}ms')
            return None

        self._segment.append(frame)
        if is_speech:
            self._silence_run = 0
            self._seg_speech_frames += 1
        else:
            self._silence_run += 1

        if self._silence_run >= self._silence_frames_needed:
            return self._close_segment(trim_trailing_silence=True)

        if self.max_speech_ms and len(self._segment) * self.frame_ms >= self.max_speech_ms:
            logger.debug('[VAD] 達到 max_speech_ms，強制切斷片段')
            return self._close_segment(trim_trailing_silence=False)

        return None

    def _close_segment(self, trim_trailing_silence: bool) -> Optional[SpeechSegment]:
        """閉合當前片段，太短的直接丟棄"""
        frames = self._segment
        if trim_trailing_silence:
            # 尾部靜音只保留 speech_pad_ms
            drop = max(0, self._silence_run - self._pad_frames)
            if drop:
                frames = frames[:-drop]

        start_frame = self._seg_start_frame
        end_frame = start_frame + len(frames)
        speech_ms = self._seg_speech_frames * self.frame_ms

        self._triggered = False
        self._segment = []
        self._speech_run = 0
        self._silence_run = 0
        self._seg_speech_frames = 0
        self._preroll.clear()

        if not frames:
            return None

        # 只看真正的語音時長，避免 padding 把噪聲墊成「夠長」的片段
        if speech_ms < self.min_speech_ms:
            logger.debug(f'[VAD] 片段語音僅 {speech_ms}ms，短於 min_speech_ms，丟棄')
            return None

        return SpeechSegment(
            start_ms=start_frame * self.frame_ms,
            end_ms=end_frame * self.frame_ms,
            audio=np.concatenate(frames),
            sample_rate=self.vad.sample_rate,
            speech_ms=speech_ms,
        )


def detect_speech_segments(vad: BaseVAD, audio: AudioLike, **kwargs) -> List[SpeechSegment]:
    """
    離線：把一整段音訊切成語音片段（kwargs 透傳給 VADSegmenter）
    """
    segmenter = VADSegmenter(vad, **kwargs)
    segmenter.reset()
    segments = list(segmenter.process(audio))
    segments.extend(segmenter.flush())
    return segments


def extract_speech(vad: BaseVAD, audio: AudioLike, **kwargs) -> Optional[np.ndarray]:
    """
    離線：去掉靜音，只留語音部分（多段會拼接）。沒有檢測到語音時返回 None
    """
    segments = detect_speech_segments(vad, audio, **kwargs)
    if not segments:
        return None
    return np.concatenate([seg.audio for seg in segments])


__all__ = [
    "SpeechSegment",
    "VADSegmenter",
    "detect_speech_segments",
    "extract_speech",
]
