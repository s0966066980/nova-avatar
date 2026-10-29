# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""faster-whisper ASR adapter used by the server-side voice pipeline."""

import math
from io import BytesIO
from pathlib import Path

from typing import Any, BinaryIO, Dict

import numpy as np
import soundfile as sf

from src.utils.logging import logger
from src.asr.base import SPEECH_LANGUAGES, BaseASR

WHISPER_SAMPLE_RATE = 16000


def _decoded_audio(audio_bytes: bytes) -> BinaryIO | np.ndarray:
    """16 kHz audio as a mono float32 waveform; anything else stays an in-memory file."""
    try:
        data, sample_rate = sf.read(BytesIO(audio_bytes), dtype="float32", always_2d=True)
        if sample_rate == WHISPER_SAMPLE_RATE:
            return data.mean(axis=1, dtype=np.float32)
    except (RuntimeError, TypeError, ValueError):
        pass  # not a libsndfile container (e.g. MP3/WebM uploads)
    # faster-whisper decodes and resamples file-like input with PyAV.
    return BytesIO(audio_bytes)


class WhisperASR(BaseASR):
    """
    Whisper ASR 引擎
    
    The public class name remains ``WhisperASR`` for configuration compatibility,
    while inference is provided exclusively by faster-whisper/CTranslate2.
    """
    
    supports_language_options = True

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
        local_name = {'small': 'whisper-small', 'turbo': 'whisper-large-v3-turbo'}.get(self.model_size)
        local = Path(__file__).resolve().parents[3] / 'models' / (local_name or '')
        model_path = str(local) if local_name and (local / 'model.bin').is_file() else self.model_size
        self.model = WhisperModel(
            model_path,
            device=self.device,
            compute_type=self.compute_type,
        )
        self.model_type = "faster-whisper"
        logger.info('[Whisper] faster-whisper 模型載入成功')
    
    def _warm_up(self) -> None:
        # Speech turns detect the language, so the warmup runs detection too.
        wav = BytesIO()
        sf.write(wav, np.zeros(WHISPER_SAMPLE_RATE, dtype=np.float32), WHISPER_SAMPLE_RATE,
                 format="WAV", subtype="PCM_16")
        self.transcribe(wav.getvalue(), language="auto")

    def _transcribe_bytes(self, audio_bytes: bytes, **options) -> Dict[str, Any]:
        """Decode in memory; a per-turn temp file costs latency and touches disk."""
        return self._transcribe(_decoded_audio(audio_bytes), **options)

    def _transcribe(
        self,
        audio: str | BinaryIO | np.ndarray,
        *,
        language: str | None = None,
    ) -> Dict[str, Any]:
        """Recognize a path, file-like object or 16 kHz mono float32 waveform.

        ``"auto"`` detects Chinese or English only (``SPEECH_LANGUAGES``).
        """
        selected_language = self.language if language is None else language
        detect = selected_language == "auto"
        segments, info = self._model_transcribe(audio, None if detect else selected_language)
        probability = getattr(info, "language_probability", None)
        detected = getattr(info, "language", None) if detect else selected_language
        if detect and detected not in SPEECH_LANGUAGES:
            # faster-whisper decodes lazily, so the segments in the wrong
            # language are never generated; only the features are recomputed.
            scores = dict(getattr(info, "all_language_probs", None) or ())
            detected = max(SPEECH_LANGUAGES, key=lambda code: scores.get(code, 0.0))
            probability = scores.get(detected)
            if hasattr(audio, "seek"):
                audio.seek(0)
            segments, _ = self._model_transcribe(audio, detected)
        segment_list = list(segments)
        response = {
            "text": "".join(segment.text for segment in segment_list).strip(),
            "language": detected,
            "language_probability": probability,
            "segments": [
                {"start": segment.start, "end": segment.end, "text": segment.text}
                for segment in segment_list
            ],
        }
        logprobs = [
            float(segment.avg_logprob)
            for segment in segment_list
            if getattr(segment, "avg_logprob", None) is not None
        ]
        if logprobs:
            # Convert average token log-probability to a bounded confidence.
            response["confidence"] = math.exp(min(0.0, sum(logprobs) / len(logprobs)))
        return response

    def _model_transcribe(self, audio: str | BinaryIO | np.ndarray, language: str | None):
        """Start decoding; ``language=None`` detects it from the first 30 s window."""
        return self.model.transcribe(
            audio,
            language=language,
            vad_filter=False,
            # Greedy decoding: utterances are one short sentence, where beam
            # search adds latency without a measurable accuracy gain.
            beam_size=1,
        )

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
