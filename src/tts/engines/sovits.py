# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

from __future__ import annotations

from io import BytesIO
from typing import Iterator

import numpy as np
import requests
import resampy
import soundfile as sf

from src.tts.base import BaseTTS, State
from src.utils.logging import logger
import time


class SovitsTTS(BaseTTS):
    def txt_to_audio(self, msg: tuple[str, dict]):
        text, textevent = msg
        emitted = self.stream_tts(
            self.gpt_sovits(
                text=text,
                reffile=self.config.tts.ref_file,
                reftext=self.config.tts.ref_text,
                language="zh",
                server_url=self.config.tts.tts_server,
            ),
            msg,
        )
        if not emitted:
            raise RuntimeError(
                "GPT-SoVITS 沒有產生音訊，請確認服務已在 "
                f"{self.config.tts.tts_server} 啟動，且參考音訊路徑在該主機上可讀"
            )

    def gpt_sovits(
        self, text, reffile, reftext, language, server_url
    ) -> Iterator[bytes]:
        start = time.perf_counter()
        req = {
            "text": text,
            "text_lang": language,
            "ref_audio_path": reffile,
            "prompt_text": reftext or "",
            "prompt_lang": language,
            "media_type": "ogg",
            "streaming_mode": True,
        }
        try:
            res = requests.post(
                f"{server_url}/tts",
                json=req,
                stream=True,
                timeout=10,
            )
            end = time.perf_counter()
            logger.info(f"gpt_sovits Time to make POST: {end-start}s")

            if res.status_code != 200:
                logger.error("GPT-SoVITS HTTP %s: %s", res.status_code, res.text)
                return

            first = True
            for chunk in res.iter_content(chunk_size=None):
                logger.info("chunk len:%d", len(chunk))
                if first:
                    end = time.perf_counter()
                    logger.info(f"gpt_sovits Time to first chunk: {end-start}s")
                    first = False
                if chunk and self.state == State.RUNNING:
                    yield chunk
        except Exception:
            logger.exception("sovits")
            raise RuntimeError(
                f"GPT-SoVITS 無法連線 {server_url}，請先啟動 API（預設埠 9880）"
            ) from None

    def __create_bytes_stream(self, byte_stream: BytesIO) -> np.ndarray:
        stream, sample_rate = sf.read(byte_stream)
        logger.info(f"[INFO]tts audio stream {sample_rate}: {stream.shape}")
        stream = stream.astype(np.float32)

        if stream.ndim > 1:
            logger.info(f"[WARN] audio has {stream.shape[1]} channels, only use the first.")
            stream = stream[:, 0]

        if sample_rate != self.sample_rate and stream.shape[0] > 0:
            logger.info(
                f"[WARN] audio sample rate is {sample_rate}, resampling into {self.sample_rate}."
            )
            stream = resampy.resample(
                x=stream, sr_orig=sample_rate, sr_new=self.sample_rate
            )

        return stream

    def stream_tts(self, audio_stream, msg: tuple[str, dict]) -> bool:
        text, textevent = msg
        first = True
        emitted = False
        for chunk in audio_stream:
            if chunk is not None and len(chunk) > 0:
                byte_stream = BytesIO(chunk)
                stream = self.__create_bytes_stream(byte_stream)
                streamlen = stream.shape[0]
                idx = 0
                while streamlen >= self.chunk:
                    eventpoint = {}
                    if first:
                        eventpoint = {"status": "start", "text": text}
                        eventpoint.update(**textevent)
                        first = False
                    self.parent.put_audio_frame(stream[idx : idx + self.chunk], eventpoint)
                    emitted = True
                    streamlen -= self.chunk
                    idx += self.chunk
        if not emitted:
            return False
        eventpoint = {"status": "end", "text": text}
        eventpoint.update(**textevent)
        self.parent.put_audio_frame(np.zeros(self.chunk, np.float32), eventpoint)
        return True
