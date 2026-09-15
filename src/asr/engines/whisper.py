# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""faster-whisper ASR adapter used by the server-side voice pipeline."""

from typing import Dict, Any

from src.utils.logging import logger
from src.asr.base import BaseASR


class WhisperASR(BaseASR):
    """
    Whisper ASR 引擎
    
    The public class name remains ``WhisperASR`` for configuration compatibility,
    while inference is provided exclusively by faster-whisper/CTranslate2.
    """
    
    def __init__(self, config=None, model_size: str = "base"):
        """
        初始化 Whisper ASR
        
        Args:
            config: 配置物件
            model_size: 模型大小 ('tiny', 'base', 'small', 'medium', 'large')
        """
        super().__init__(config)
        
        self.model_size = model_size
        configured_device = getattr(getattr(config, "asr", None), "device", "auto")
        if configured_device == "auto":
            try:
                import torch
                configured_device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                configured_device = "cpu"
        self.device = configured_device
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        self.model = None
        self.model_type = None
        
        logger.info(f'[Whisper] 模型大小: {model_size}, 裝置: {self.device}')
    
    def _load_model(self):
        """載入 Whisper 模型"""
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError('請安裝 faster-whisper：uv pip install "faster-whisper>=1.1"') from exc

        logger.info(
            f'[Whisper] 正在載入 faster-whisper: {self.model_size} '
            f'({self.device}/{self.compute_type})'
        )
        self.model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        self.model_type = "faster-whisper"
        logger.info('[Whisper] faster-whisper 模型載入成功')
    
    def _transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        使用 Whisper 識別音訊
        
        Args:
            audio_path: 音訊檔案路徑
            
        Returns:
            識別結果字典
        """
        language = None if self.language == "auto" else self.language
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            vad_filter=False,
            beam_size=5,
        )
        segment_list = list(segments)
        return {
            "text": "".join(segment.text for segment in segment_list).strip(),
            "language": getattr(info, "language", self.language),
            "segments": [
                {"start": segment.start, "end": segment.end, "text": segment.text}
                for segment in segment_list
            ],
        }
    
    def get_info(self) -> Dict[str, Any]:
        """獲取引擎資訊"""
        info = super().get_info()
        info.update({
            "model_size": self.model_size,
            "model_type": self.model_type,
            "device": self.device,
            "compute_type": self.compute_type,
        })
        return info
