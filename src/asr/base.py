# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""
ASR 引擎基類
所有 ASR 引擎的統一抽象介面
"""

from __future__ import annotations

import os
import tempfile
import time
from threading import RLock
import numpy as np
import soundfile as sf
from io import BytesIO
from typing import Dict, Any
from abc import ABC, abstractmethod

from src.utils.logging import logger

# Conversation locale -> recognizer language. A fixed language skips Whisper's
# per-turn language detection; the conversation already says which to expect.
_LOCALE_LANGUAGES = {"zh-TW": "zh", "en-US": "en"}


def asr_language(locale: str) -> str:
    """Recognizer language for a conversation locale."""
    try:
        return _LOCALE_LANGUAGES[locale]
    except KeyError:
        raise ValueError(f"不支援的語系: {locale}") from None


class BaseASR(ABC):
    """
    所有 ASR 引擎的基類
    
    統一介面：
    - transcribe: 識別音訊位元組資料
    - set_language: 設定識別語言
    - get_info: 獲取引擎資訊
    """
    
    def __init__(self, config=None):
        """
        初始化 ASR 引擎
        
        Args:
            config: 配置物件（可選）
        """
        self.config = config
        self.language = "zh"  # 預設中文
        self._initialized = False
        self._ready_lock = RLock()
        self._prewarmed = False
        
        logger.info(f'[ASR] 初始化 {self.__class__.__name__}')
    
    @abstractmethod
    def _load_model(self):
        """載入 ASR 模型（子類實現）"""
        pass
    
    @abstractmethod
    def _transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        識別音訊檔案（子類實現）
        
        Args:
            audio_path: 音訊檔案路徑
            
        Returns:
            Dict 包含:
                - text: 識別的文本
                - language: 檢測到的語言（可選）
                - confidence: 置信度（可選）
        """
        pass
    
    def transcribe(self, audio_bytes: bytes, *, language: str | None = None) -> Dict[str, Any]:
        """
        識別音訊位元組資料（統一入口）
        
        Args:
            audio_bytes: 音訊檔案的位元組資料
            
        Returns:
            Dict 包含識別結果
        """
        # 延遲載入模型，避免啟動時耗時/佔用視訊記憶體
        self.ensure_ready()
        
        options = {"language": language} if getattr(self, "supports_language_options", False) else {}
        result = self._transcribe_bytes(audio_bytes, **options)
        logger.info(
            "[ASR] transcription completed language=%s",
            result.get("language", "unknown"),
        )
        return result

    def _transcribe_bytes(self, audio_bytes: bytes, **options) -> Dict[str, Any]:
        """Recognize encoded audio; engines that decode in memory override this."""
        # 統一轉成臨時檔案，方便不同引擎複用檔案介面
        temp_audio_path = None
        try:
            temp_audio_path = self._save_temp_audio(audio_bytes)
            return self._transcribe(temp_audio_path, **options)
        finally:
            # 清理臨時檔案
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.unlink(temp_audio_path)
                except Exception as e:
                    logger.warning(f'[ASR] 清理臨時檔案失敗: {e}')
    
    def _save_temp_audio(self, audio_bytes: bytes) -> str:
        """
        儲存臨時音訊檔案並轉換為 wav 格式
        
        Args:
            audio_bytes: 音訊位元組資料
            
        Returns:
            臨時檔案路徑
        """
        try:
            # 嘗試讀取音訊並轉換為 wav
            audio_stream = BytesIO(audio_bytes)
            data, samplerate = sf.read(audio_stream)
            
            # 建立臨時 wav 檔案
            temp_fd, temp_path = tempfile.mkstemp(suffix='.wav')
            os.close(temp_fd)
            
            sf.write(temp_path, data, samplerate)
            logger.debug(f'[ASR] 音訊已儲存: {temp_path}, 取樣率: {samplerate}Hz')
            return temp_path

        except Exception as e:
            logger.warning(f'[ASR] 音訊格式轉換失敗，儲存原始格式: {e}')
            # 如果轉換失敗，直接儲存原始位元組
            temp_fd, temp_path = tempfile.mkstemp(suffix='.webm')
            os.close(temp_fd)
            
            with open(temp_path, 'wb') as f:
                f.write(audio_bytes)
            
            return temp_path

    def ensure_ready(self) -> None:
        """Load the recognizer once so connection setup can fail before listening starts."""
        with self._ready_lock:
            if not self._initialized:
                self._load_model()
                self._initialized = True

    def prewarm(self) -> None:
        """Run the real inference path once; no utterance or history is created."""
        with self._ready_lock:
            self.ensure_ready()
            if self._prewarmed:
                return
            started = time.perf_counter()
            self._warm_up()
            # Failed warmups remain retryable at session preparation.
            self._prewarmed = True
            logger.info('[ASR] inference prewarm ready engine=%s elapsed=%.3fs',
                        type(self).__name__, time.perf_counter() - started)

    def _warm_up(self) -> None:
        wav = BytesIO()
        sf.write(wav, np.zeros(16000, dtype=np.float32), 16000,
                 format="WAV", subtype="PCM_16")
        self.transcribe(wav.getvalue())
    
    def transcribe_text(self, audio_bytes: bytes) -> str:
        """
        簡化介面：只返回識別的文本
        
        Args:
            audio_bytes: 音訊檔案的位元組資料
            
        Returns:
            識別的文本字串
        """
        result = self.transcribe(audio_bytes)
        return result.get("text", "")
    
    def set_language(self, language: str):
        """
        設定識別語言
        
        Args:
            language: 語言程式碼（如 'zh', 'en', 'auto'）
        """
        self.language = language
        logger.info(f'[ASR] 語言設定為: {language}')
    
    def get_info(self) -> Dict[str, Any]:
        """
        獲取 ASR 引擎資訊
        
        Returns:
            Dict 包含引擎資訊
        """
        return {
            "engine": self.__class__.__name__,
            "language": self.language,
            "initialized": self._initialized
        }


__all__ = ["BaseASR"]
