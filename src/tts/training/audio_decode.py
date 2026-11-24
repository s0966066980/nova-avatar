# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Decode an upload to 16 kHz mono float samples and explain QC rejections.

The quality rules themselves (silence trimming, 0.5 to 15 seconds, RMS,
loudness calibration) are ``audio_quality.assess_audio``, shared with the Edge
teacher; this module only turns an uploaded file into the samples it expects and
words its verdict for the administrator in Traditional Chinese.

Decoding names its FFmpeg demuxer from the file's magic bytes
(``src.utils.audio_container``), because letting FFmpeg probe could follow
playlist formats to other files on the host. It is CPU work that can take longer
than 50 ms: async callers run it in ``asyncio.to_thread`` (CODING_STANDARDS 3).
"""

from __future__ import annotations

import io

import numpy as np

from src.tts.training.audio_quality import (
    MAX_SECONDS,
    MIN_SECONDS,
    REASON_CLIPPED,
    REASON_SILENT,
    REASON_TOO_LONG,
    REASON_TOO_QUIET,
    REASON_TOO_SHORT,
    SAMPLE_RATE,
)
from src.tts.training.corpus import CorpusError
from src.utils.audio_container import HEADER_BYTES, demuxer_for

# A recording this much longer than a training line is refused before it is
# decoded in full, so a 20 MB upload cannot become hours of samples in memory.
MAX_DECODE_SECONDS = 60.0
SUPPORTED_FORMATS = "WAV、MP3、FLAC、OGG、M4A、WebM"

_REASON_MESSAGES = {
    REASON_SILENT: "音檔幾乎沒有聲音",
    REASON_TOO_SHORT: f"音檔太短，修剪頭尾靜音後至少需要 {MIN_SECONDS:g} 秒",
    REASON_TOO_LONG: f"音檔太長，修剪頭尾靜音後不可超過 {MAX_SECONDS:g} 秒；請切成較短的句子再上傳",
    REASON_TOO_QUIET: "音檔音量太小，請提高錄音音量後重新上傳",
    REASON_CLIPPED: "音檔有破音（削波），請降低錄音音量後重新上傳",
}


def quality_message(reasons: tuple[str, ...]) -> str:
    """The rejection reasons of ``assess_audio`` as one Traditional Chinese sentence."""
    return "；".join(_REASON_MESSAGES.get(reason, "音檔品質不合格") for reason in reasons)


def decode_to_16k_mono(data: bytes) -> np.ndarray:
    """Decode audio bytes to mono float32 samples at 16 kHz, or raise ``CorpusError``."""
    import av

    demuxer = demuxer_for(bytes(data[:HEADER_BYTES]))
    if demuxer is None:
        raise CorpusError(f"不是支援的音檔，請上傳 {SUPPORTED_FORMATS}", status=415)
    try:
        container = av.open(io.BytesIO(data), format=demuxer)
    except Exception as exc:
        raise CorpusError(f"無法解析音檔，請上傳 {SUPPORTED_FORMATS}", status=422) from exc
    limit = int(MAX_DECODE_SECONDS * SAMPLE_RATE)
    too_long = CorpusError(
        f"音檔太長，每句不可超過 {MAX_SECONDS:g} 秒；請切成較短的句子再上傳", status=422
    )
    try:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None or not stream.rate:
            raise CorpusError("檔案沒有可用的音訊軌", status=422)
        if container.duration and container.duration / 1_000_000 > MAX_DECODE_SECONDS + 0.5:
            raise too_long
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        chunks: list[np.ndarray] = []
        total = 0

        def keep(frames) -> None:
            nonlocal total
            for frame in frames:
                part = frame.to_ndarray().reshape(-1).astype(np.int16)
                total += part.size
                if total > limit:
                    raise too_long
                chunks.append(part)

        for frame in container.decode(stream):
            keep(resampler.resample(frame))
        keep(resampler.resample(None))
    except CorpusError:
        raise
    except Exception as exc:
        raise CorpusError(f"無法解碼音檔，請上傳 {SUPPORTED_FORMATS}", status=422) from exc
    finally:
        container.close()
    if not chunks:
        raise CorpusError("音檔沒有任何聲音資料", status=422)
    return np.concatenate(chunks).astype(np.float32) / 32768.0
