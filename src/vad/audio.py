# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""
VAD 用到的音訊解碼 / 重取樣工具

瀏覽器上傳的一般是 webm/opus 或 mp4/aac，soundfile 讀不了，
這裡統一用 soundfile 優先、PyAV（aiortc already 依賴）兜底解碼成單聲道 16-bit PCM。
"""

from __future__ import annotations

from io import BytesIO
from typing import Optional, Tuple

import numpy as np

from src.utils.logging import logger


def resample_int16(pcm: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """把 int16 PCM 從 src_sr 重取樣到 dst_sr"""
    if src_sr == dst_sr or len(pcm) == 0:
        return pcm

    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(int(src_sr), int(dst_sr))
    resampled = resample_poly(pcm.astype(np.float32), dst_sr // g, src_sr // g)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def to_mono_int16(data: np.ndarray) -> np.ndarray:
    """多聲道 → 單聲道，任意 dtype → int16"""
    arr = np.asarray(data)
    if arr.ndim > 1:
        arr = arr.astype(np.float32).mean(axis=1)
    if arr.dtype == np.int16:
        return arr
    if np.issubdtype(arr.dtype, np.floating):
        return np.clip(arr * 32768.0, -32768, 32767).astype(np.int16)
    return arr.astype(np.int16)


def _decode_with_soundfile(data: bytes) -> Optional[Tuple[np.ndarray, int]]:
    try:
        import soundfile as sf

        audio, sr = sf.read(BytesIO(data), always_2d=True)
        return to_mono_int16(audio), int(sr)
    except Exception as e:
        logger.debug(f'[VAD] soundfile 解碼失敗（可能是 webm/opus）: {e}')
        return None


def _decode_with_av(data: bytes, target_sr: int) -> Optional[Tuple[np.ndarray, int]]:
    try:
        import av
        from av.audio.resampler import AudioResampler

        chunks = []
        with av.open(BytesIO(data)) as container:
            resampler = AudioResampler(format='s16', layout='mono', rate=target_sr)
            for frame in container.decode(audio=0):
                for out in _resample_frames(resampler, frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in _resample_frames(resampler, None):
                chunks.append(out.to_ndarray().reshape(-1))

        if not chunks:
            return None
        return np.concatenate(chunks).astype(np.int16), target_sr
    except Exception as e:
        logger.warning(f'[VAD] PyAV 解碼失敗: {e}')
        return None


def _resample_frames(resampler, frame):
    """相容 PyAV 不同版本：resample 可能返回單幀或幀列表"""
    out = resampler.resample(frame)
    if out is None:
        return []
    if isinstance(out, (list, tuple)):
        return list(out)
    return [out]


def decode_audio(data: bytes, target_sr: int = 16000) -> np.ndarray:
    """
    把任意音訊位元組解碼成 target_sr 的單聲道 int16 PCM

    Args:
        data: 音訊檔案位元組（wav/webm/mp3/mp4...）
        target_sr: 目標取樣率

    Returns:
        np.int16 單聲道 PCM

    Raises:
        ValueError: 所有解碼方式都失敗
    """
    result = _decode_with_soundfile(data)
    if result is None:
        result = _decode_with_av(data, target_sr)
    if result is None:
        raise ValueError('[VAD] 音訊解碼失敗：soundfile 與 PyAV 均無法讀取')

    pcm, sr = result
    return resample_int16(pcm, sr, target_sr)


def pcm16_to_wav_bytes(pcm: np.ndarray, sample_rate: int = 16000) -> bytes:
    """int16 PCM → wav 檔案位元組（供 ASR 引擎直接讀取）"""
    import soundfile as sf

    buffer = BytesIO()
    sf.write(buffer, np.asarray(pcm, dtype=np.int16), sample_rate, format='WAV', subtype='PCM_16')
    return buffer.getvalue()


__all__ = [
    "decode_audio",
    "pcm16_to_wav_bytes",
    "resample_int16",
    "to_mono_int16",
]
