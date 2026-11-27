# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""
VAD 引擎基類
所有 VAD（語音活動檢測）引擎的統一抽象介面

統一約定：
- 內部幀格式固定為單聲道 16-bit PCM（np.int16），取樣率由 sample_rate 指定
- Silero 把 frame_ms 歸一化為 512/256 取樣點，呼叫方只管按 frame_samples 切幀
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, Union

import numpy as np

from src.utils.logging import logger

AudioLike = Union[bytes, bytearray, memoryview, np.ndarray]


def to_int16(data: AudioLike) -> np.ndarray:
    """把 bytes / float 陣列統一轉成 np.int16 單聲道陣列"""
    if isinstance(data, (bytes, bytearray, memoryview)):
        return np.frombuffer(bytes(data), dtype=np.int16)

    arr = np.asarray(data)
    if arr.ndim > 1:  # 多聲道取平均降成單聲道
        arr = arr.mean(axis=1)
    if arr.dtype == np.int16:
        return arr
    if np.issubdtype(arr.dtype, np.floating):
        return np.clip(arr * 32768.0, -32768, 32767).astype(np.int16)
    return arr.astype(np.int16)


class BaseVAD(ABC):
    """
    所有 VAD 引擎的基類

    統一介面：
    - speech_prob: 單幀語音機率
    - is_speech:   單幀是否為語音
    - frames:      把整段 PCM 切成引擎要求的定長幀
    - reset:       重置引擎內部狀態（流式場景切換會話時呼叫）
    """

    # 引擎支援的取樣率
    SUPPORTED_SAMPLE_RATES: tuple = (8000, 16000, 32000, 48000)
    # 引擎預設幀長（毫秒）
    DEFAULT_FRAME_MS: int = 30

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 0,
        threshold: float = 0.5,
        config=None,
        **kwargs,
    ):
        """
        Args:
            sample_rate: 取樣率，必須在 SUPPORTED_SAMPLE_RATES 內
            frame_ms: 期望幀長（毫秒），0 表示用引擎預設值；會被引擎歸一化
            threshold: 判定為語音的機率閾值
            config: 全域性配置物件（可選）
        """
        if sample_rate not in self.SUPPORTED_SAMPLE_RATES:
            raise ValueError(
                f'[VAD] {self.__class__.__name__} 不支援取樣率 {sample_rate}，'
                f'支援: {list(self.SUPPORTED_SAMPLE_RATES)}'
            )

        self.sample_rate = sample_rate
        self.threshold = float(threshold)
        self.config = config
        self.frame_ms = self._normalize_frame_ms(int(frame_ms) or self.DEFAULT_FRAME_MS)
        self._initialized = False

        logger.info(
            f'[VAD] 初始化 {self.__class__.__name__}: '
            f'{self.sample_rate}Hz / {self.frame_ms}ms / threshold={self.threshold}'
        )

    # ------------------------------------------------------------------ 幀引數

    def _normalize_frame_ms(self, frame_ms: int) -> int:
        """把期望幀長歸一化成引擎支援的幀長（子類可覆蓋）"""
        return frame_ms

    @property
    def frame_samples(self) -> int:
        """一幀的取樣點數"""
        return int(self.sample_rate * self.frame_ms / 1000)

    @property
    def frame_bytes(self) -> int:
        """一幀的位元組數（16-bit PCM）"""
        return self.frame_samples * 2

    # ------------------------------------------------------------------ 子類實現

    @abstractmethod
    def _load_model(self):
        """載入模型 / 建立檢測器（子類實現，延遲到首次使用時呼叫）"""

    @abstractmethod
    def _speech_prob(self, frame: np.ndarray) -> float:
        """
        單幀語音機率（子類實現）

        Args:
            frame: np.int16 陣列，長度 == frame_samples

        Returns:
            0.0 ~ 1.0 的語音機率
        """

    # ------------------------------------------------------------------ 統一入口

    def ensure_ready(self):
        """延遲載入模型，避免啟動時白白佔資源"""
        if not self._initialized:
            self._load_model()
            self._initialized = True

    def speech_prob(self, frame: AudioLike) -> float:
        """計算單幀語音機率，幀長必須等於 frame_samples"""
        self.ensure_ready()
        arr = to_int16(frame)
        if len(arr) != self.frame_samples:
            raise ValueError(
                f'[VAD] 幀長不匹配: 期望 {self.frame_samples} 取樣點，實際 {len(arr)}'
            )
        return float(self._speech_prob(arr))

    def is_speech(self, frame: AudioLike) -> bool:
        """單幀是否為語音"""
        return self.speech_prob(frame) >= self.threshold

    def frames(self, audio: AudioLike) -> Iterator[np.ndarray]:
        """
        把整段 PCM 按 frame_samples 切幀，不足一幀的尾巴直接丟棄

        Args:
            audio: bytes(16-bit PCM) 或 numpy 陣列
        """
        arr = to_int16(audio)
        step = self.frame_samples
        total = (len(arr) // step) * step
        for start in range(0, total, step):
            yield arr[start:start + step]

    def reset(self):
        """重置內部狀態（無狀態引擎可不實現）"""

    def close(self):
        """釋放資源（子類按需覆蓋）"""
        self._initialized = False

    def get_info(self) -> Dict[str, Any]:
        """獲取引擎資訊"""
        return {
            "engine": self.__class__.__name__,
            "type": getattr(self, "ENGINE_TYPE", ""),
            "sample_rate": self.sample_rate,
            "frame_ms": self.frame_ms,
            "frame_samples": self.frame_samples,
            "threshold": self.threshold,
            "initialized": self._initialized,
        }


__all__ = ["BaseVAD", "to_int16", "AudioLike"]
