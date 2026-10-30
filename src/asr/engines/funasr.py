# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""FunASR engine: Fun-ASR-Nano-2512 through the owned loopback service.

The model runs in its own venv (``src/asr/fun_asr_nano_service.py``); this
engine starts the service when it loads and sends 16 kHz mono PCM16 audio.
Chinese, English and mixed speech are recognized; the service converts the
Simplified output to Taiwan Traditional unless ``output_script`` is ``simplified``.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict

import numpy as np
import soundfile as sf

from src.asr import fun_asr_nano_service as service
from src.asr.base import BaseASR
from src.utils.logging import logger

SAMPLE_RATE = 16000
FUNASR_OUTPUT_SCRIPTS = frozenset({"traditional-tw", "simplified"})
FUNASR_DEVICES = frozenset({"auto", "cpu", "cuda"})
FUNASR_LANGUAGES = frozenset({"auto", "zh", "en"})


def _resampled_pcm16(audio_bytes: bytes) -> bytes:
    """Decode any container PyAV reads into 16 kHz mono PCM16."""
    import av

    chunks = []
    with av.open(BytesIO(audio_bytes)) as container:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            raise ValueError("沒有音訊軌")
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            chunks.extend(converted.to_ndarray().reshape(-1) for converted in resampler.resample(frame))
        chunks.extend(converted.to_ndarray().reshape(-1) for converted in resampler.resample(None))
    if not chunks:
        return b""
    return np.concatenate(chunks).astype("<i2").tobytes()


def pcm16_16k(audio_bytes: bytes) -> bytes:
    """16 kHz mono PCM16 for the service; the voice session already sends 16 kHz WAV."""
    try:
        data, rate = sf.read(BytesIO(audio_bytes), dtype="int16", always_2d=True)
    except (RuntimeError, TypeError, ValueError):
        return _resampled_pcm16(audio_bytes)  # not a libsndfile container (e.g. WebM)
    if rate != SAMPLE_RATE:
        return _resampled_pcm16(audio_bytes)
    mono = data[:, 0] if data.shape[1] == 1 else data.mean(axis=1)
    return np.asarray(mono, dtype="<i2").tobytes()


class FunASR(BaseASR):
    """Fun-ASR-Nano-2512 (Tongyi Lab, Apache-2.0) served from its own venv."""

    supports_language_options = True

    def __init__(self, config=None, model_name: str = service.DEFAULT_MODEL):
        super().__init__(config)
        asr = getattr(config, "asr", None)
        self.model_name = service.resolve_model(model_name)
        self.output_script = str(getattr(asr, "output_script", "traditional-tw") or "traditional-tw")
        if self.output_script not in FUNASR_OUTPUT_SCRIPTS:
            raise ValueError(f"不支援的 FunASR 輸出文字: {self.output_script}")
        self.device = str(getattr(asr, "device", "auto") or "auto").lower()
        if self.device not in FUNASR_DEVICES:
            raise ValueError(f"不支援的 FunASR 裝置: {self.device}")
        self.url = ""
        logger.info('[FunASR] 模型: %s, 裝置: %s', self.model_name, self.device)

    def _load_model(self):
        self.url = service.ensure_server(model=self.model_name, device=self.device)

    def _transcribe_bytes(self, audio_bytes: bytes, **options) -> Dict[str, Any]:
        language = options.get("language") or self.language
        if language not in FUNASR_LANGUAGES:
            language = "auto"
        return service.recognize(self.url, pcm16_16k(audio_bytes), language=language,
                                 script=self.output_script)

    def _transcribe(self, audio_path: str, **options) -> Dict[str, Any]:
        return self._transcribe_bytes(Path(audio_path).read_bytes(), **options)

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "model_name": self.model_name,
            "device": self.device,
            "server": self.url,
        })
        return info
