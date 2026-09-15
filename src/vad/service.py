# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""
VAD 服務層：把「上傳的音訊位元組」變成「只含語音的音訊位元組」

給 /asr 這類介面用，好處有兩個：
1. 全是靜音 / 噪聲時直接短路，不用白跑一次 ASR
2. 掐掉前後靜音，Whisper 之類模型不容易幻聽出多餘文本，延遲也更低
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.utils.logging import logger
from src.vad.audio import decode_audio, pcm16_to_wav_bytes
from src.vad.factory import get_vad_engine_from_config
from src.vad.segmenter import detect_speech_segments


@dataclass
class VADOutcome:
    """VAD 預處理結果"""
    audio_bytes: bytes          # 交給 ASR 的音訊（VAD 關閉或失敗時就是原始音訊）
    has_speech: bool = True     # 是否檢測到語音；VAD 未生效時按 True 處理
    enabled: bool = False       # VAD 是否真的跑了
    engine: str = ""
    segments: int = 0
    speech_ms: int = 0
    total_ms: int = 0
    error: str = ""

    @property
    def trimmed_ms(self) -> int:
        return max(0, self.total_ms - self.speech_ms)


def _segmenter_kwargs(vad_config) -> dict:
    return {
        "speech_start_ms": getattr(vad_config, "speech_start_ms", 100),
        "min_speech_ms": getattr(vad_config, "min_speech_ms", 250),
        "min_silence_ms": getattr(vad_config, "min_silence_ms", 500),
        "speech_pad_ms": getattr(vad_config, "speech_pad_ms", 150),
        "max_speech_ms": getattr(vad_config, "max_speech_ms", 15000),
    }


def preprocess_audio_bytes(audio_bytes: bytes, vad_config=None, config=None) -> VADOutcome:
    """
    用 VAD 預處理上傳的音訊

    Args:
        audio_bytes: 原始音訊檔案位元組（wav/webm/mp4...）
        vad_config: config.vad（None 或 enabled=False 時原樣返回）
        config: 全域性配置物件（可選，透傳給引擎）

    Returns:
        VADOutcome；任何異常都會降級成「原樣返回 + error 欄位」，不影響 ASR 主流程
    """
    if vad_config is None or not getattr(vad_config, "enabled", False):
        return VADOutcome(audio_bytes=audio_bytes, enabled=False)

    engine_type = getattr(vad_config, "type", "silero")
    try:
        sample_rate = int(getattr(vad_config, "sample_rate", 16000))
        pcm = decode_audio(audio_bytes, sample_rate)
        total_ms = int(len(pcm) * 1000 / sample_rate)

        vad = get_vad_engine_from_config(vad_config, config=config)
        vad.reset()
        segments = detect_speech_segments(vad, pcm, **_segmenter_kwargs(vad_config))

        if not segments:
            logger.info(f'[VAD] {engine_type}: {total_ms}ms 音訊中未檢測到語音')
            return VADOutcome(
                audio_bytes=audio_bytes,
                has_speech=False,
                enabled=True,
                engine=engine_type,
                total_ms=total_ms,
            )

        speech = np.concatenate([seg.audio for seg in segments])
        speech_ms = int(len(speech) * 1000 / sample_rate)
        logger.info(
            f'[VAD] {engine_type}: {len(segments)} 段語音，'
            f'{speech_ms}ms / {total_ms}ms（裁掉 {total_ms - speech_ms}ms 靜音）'
        )
        return VADOutcome(
            audio_bytes=pcm16_to_wav_bytes(speech, sample_rate),
            has_speech=True,
            enabled=True,
            engine=engine_type,
            segments=len(segments),
            speech_ms=speech_ms,
            total_ms=total_ms,
        )

    except Exception as e:
        # VAD 只是前置最佳化，壞了也不能擋住語音識別，這裡降級並把原因帶出去
        logger.warning(f'[VAD] {engine_type} 預處理失敗，退回原始音訊: {e}')
        return VADOutcome(
            audio_bytes=audio_bytes,
            has_speech=True,
            enabled=False,
            engine=engine_type,
            error=str(e),
        )


def create_segmenter(vad_config, config=None):
    """
    按配置建立一個流式端點檢測器（給 WebSocket / WebRTC 音軌這類即時場景用）

    用法：
        segmenter = create_segmenter(state.config.vad)
        for seg in segmenter.process(pcm_chunk):
            ...  # seg.audio 是一整句話
    """
    from src.vad.segmenter import VADSegmenter

    vad = get_vad_engine_from_config(vad_config, config=config)
    return VADSegmenter(vad, **_segmenter_kwargs(vad_config))


__all__ = ["VADOutcome", "preprocess_audio_bytes", "create_segmenter"]
