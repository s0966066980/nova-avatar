# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Three preset preview sentences for a finished voice model (spec decision 17).

The console's done screen lets the administrator hear a voice model say one of
three sentences the server defines: plain Chinese, Chinese with digits, and
English. A caller names the sentence by its code (``PREVIEW_SENTENCES``) and
never supplies text, so the route cannot be used to speak arbitrary words or to
probe the engine. The voice model is named by its catalog ID, resolved through
``resolve_voice_model`` against the models listed under ``models/tts/``; nothing
is downloaded and the result is a short in-memory WAV, never a file of the model.

Synthesis goes through the live engine's own loader and per-model lock
(``matcha.load_voice_model`` / ``generate_speech``): a voice model already loaded
for a role is not loaded a second time, and a preview takes turns with a spoken
reply instead of running beside it. It runs on the CPU (sherpa-onnx, ``provider="cpu"``).

This is blocking work; async callers use ``asyncio.to_thread`` (CODING_STANDARDS 3).
"""

from __future__ import annotations

import io
import wave
from collections.abc import Callable

import numpy as np

from nova_tts.engines.matcha import (
    VoiceModelUnavailable,
    _build_t2s_converter,
    generate_speech,
    limit_peak,
    load_voice_model,
    resolve_voice_model,
)
from nova_core.utils.logging import logger

# The text of each code. The console shows the same sentences next to its play buttons.
PREVIEW_SENTENCES = {
    "zh": "您好，歡迎光臨，很高興為您服務。",
    "digits": "今天是2026年11月24日，票價是150元。",
    "en": "Welcome to the exhibition hall, how can I help you?",
}
# These sentences take a few seconds; anything longer means something is wrong, and
# bounds the size of the response (about 1 MB at 16 kHz).
MAX_PREVIEW_SECONDS = 30.0


class PreviewError(Exception):
    """Why no preview was produced: a Traditional Chinese message and an HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def synthesize_preview(
    voice_id: object,
    sentence: object,
    *,
    num_threads: int,
    keep_going: Callable[[], bool] | None = None,
) -> bytes:
    """A mono PCM16 WAV of voice model ``voice_id`` speaking the preset ``sentence``.

    ``num_threads`` is the server-wide ``matcha.num_threads``, which keys the shared
    loaded model. ``keep_going`` returning False (a timeout, a gone client) stops the
    generation and raises ``PreviewError`` with status 408. Raises ``PreviewError``
    for an unknown sentence code (400), an unlisted voice model (404), and a model
    that cannot be loaded or speaks nothing or too long (500).
    """
    if not isinstance(sentence, str) or sentence not in PREVIEW_SENTENCES:
        raise PreviewError("sentence 必須是 zh、digits 或 en 其中之一，不接受自訂文字")
    try:
        model = resolve_voice_model(voice_id if isinstance(voice_id, str) else "")
    except VoiceModelUnavailable as exc:
        raise PreviewError(str(exc), status=404) from exc
    try:
        voice = load_voice_model(model, num_threads)
    except VoiceModelUnavailable as exc:
        raise PreviewError(str(exc), status=500) from exc
    except Exception as exc:
        logger.exception("Voice preview could not load %s", model.id)
        raise PreviewError(f"聲線模型「{model.id}」載入失敗：{exc}", status=500) from exc
    try:
        samples, rate = generate_speech(
            voice, PREVIEW_SENTENCES[sentence], converter=_build_t2s_converter(), keep_going=keep_going
        )
    except Exception as exc:
        logger.exception("Voice preview synthesis failed for %s", model.id)
        raise PreviewError(f"試聽合成失敗：{exc}", status=500) from exc
    if keep_going is not None and not keep_going():
        raise PreviewError("試聽已取消或逾時", status=408)
    if not samples.size:
        raise PreviewError("這個聲線模型沒有產生任何音訊", status=500)
    if samples.size > MAX_PREVIEW_SECONDS * rate:
        raise PreviewError(f"試聽音訊超過 {MAX_PREVIEW_SECONDS:.0f} 秒的上限", status=500)
    return _wav_bytes(limit_peak(samples), rate)


def _wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())
    return buffer.getvalue()
