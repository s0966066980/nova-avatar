# Derived from Kedreamix/Linly-Talker-Stream (the CosyVoice HTTP client).
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""BreezyVoice (MediaTek Research, Apache-2.0): Taiwanese Mandarin voice cloning.

Runs in the owned CosyVoice server process (``scripts/cosyvoice_fastapi_server.py``),
which adds BreezyVoice's g2pW 注音 frontend. BreezyVoice does not stream: each
playable reply fragment is synthesized whole and returned as 22.05 kHz PCM16.
The reference recording and its transcript come from the voice library.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import numpy as np
import requests
import resampy

from src.tts.base import BaseTTS, State
from src.tts.cosyvoice_runtime import parse_server_url, prepare_prompt_wav, server_url
from src.tts.voice_library import voice_path, voice_transcript
from src.utils.logging import logger


class BreezyVoiceTTS(BaseTTS):
    # PCM16 rate the owned server returns (BreezyVoice is a CosyVoice v1 model).
    SOURCE_SAMPLE_RATE = 22050
    LOG_NAME = "breezyvoice"

    def txt_to_audio(self, msg: tuple[str, dict]):
        text, textevent = msg
        try:
            emitted = self.stream_tts(
                self.synthesize(text, self._prompt_wav(), self._prompt_text(), self._server_url()),
                msg,
            )
            if not emitted:
                raise RuntimeError("BreezyVoice returned no decodable audio")
        except Exception:
            logger.exception("breezyvoice")
            self.notify_fragment_synthesis_failed(textevent, "tts_exhausted_before_audio")
            raise

    def _server_url(self) -> str:
        configured = str(getattr(self.config.tts, "tts_server", "") or "").strip()
        if configured:
            return server_url(*parse_server_url(configured))
        return server_url()

    def _prompt_wav(self) -> str:
        """The library reference; BreezyVoice has no bundled default voice."""
        configured = str(getattr(self.config.tts, "ref_file", "") or "").strip()
        if not configured:
            raise FileNotFoundError("BreezyVoice 需要從音訊庫選擇參考音訊")
        return str(prepare_prompt_wav(voice_path(configured)))

    def _prompt_text(self) -> str:
        """``tts.ref_text`` when set, else the transcript stored with the library voice."""
        configured = str(getattr(self.config.tts, "ref_text", "") or "").strip()
        if configured:
            return configured
        transcript = voice_transcript(getattr(self.config.tts, "ref_file", ""))
        if not transcript:
            raise ValueError("BreezyVoice 需要參考音訊的逐字稿（音訊庫或「參考語音逐字稿」）")
        return transcript

    def _tts_request(self, text: str, prompt_text: str = "") -> tuple[str, dict]:
        return "inference_zero_shot", {"tts_text": text, "prompt_text": prompt_text}

    def synthesize(self, text: str, reffile: str, reftext: str, server_url: str) -> Iterator[bytes]:
        started_at = time.perf_counter()
        endpoint, payload = self._tts_request(text, reftext)
        with Path(reffile).open("rb") as prompt:
            response = requests.post(
                f"{server_url.rstrip('/')}/{endpoint}",
                data=payload,
                files={"prompt_wav": ("prompt.wav", prompt, "application/octet-stream")},
                stream=True,
                timeout=(5, 60),
            )
        if response.status_code != 200:
            raise RuntimeError(f"BreezyVoice HTTP {response.status_code}: {response.text[:300]}")
        first = True
        for chunk in response.iter_content(chunk_size=9600):
            if not chunk or self.state != State.RUNNING:
                continue
            if first:
                logger.info("%s first audio:%.4fs", self.LOG_NAME, time.perf_counter() - started_at)
                first = False
                mark_stage = getattr(self.parent, "mark_stage_end", None)
                if callable(mark_stage):
                    mark_stage("tts_first_encoded")
                    mark_stage("tts_first_pcm")
            yield chunk

    def stream_tts(self, audio_stream, msg: tuple[str, dict]) -> bool:
        text, textevent = msg
        remainder = np.empty(0, dtype=np.float32)
        media_sequence = 0
        emitted = False
        turn_aware = {"turn_id", "generation", "fragment_sequence"}.issubset(textevent or {})
        for chunk in audio_stream:
            if not chunk:
                continue
            stream = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32767.0
            stream = resampy.resample(x=stream, sr_orig=self.SOURCE_SAMPLE_RATE, sr_new=self.sample_rate)
            remainder = np.concatenate((remainder, stream))
            while remainder.size >= self.chunk and self.state == State.RUNNING:
                frame = remainder[: self.chunk].copy()
                remainder = remainder[self.chunk :]
                self._emit_frame(frame, text, textevent, media_sequence=media_sequence,
                                 start=not emitted, final=False, turn_aware=turn_aware)
                emitted = True
                media_sequence += 1
        if remainder.size and self.state == State.RUNNING:
            padded = np.pad(remainder, (0, self.chunk - remainder.size))
            self._emit_frame(padded.astype(np.float32, copy=False), text, textevent,
                             media_sequence=media_sequence, start=not emitted, final=True,
                             turn_aware=turn_aware)
            emitted = True
        elif emitted and self.state == State.RUNNING:
            self._emit_frame(np.zeros(self.chunk, np.float32), text, textevent,
                             media_sequence=media_sequence, start=False, final=True,
                             turn_aware=turn_aware)
        return emitted

    def _emit_frame(
        self,
        samples: np.ndarray,
        text: str,
        textevent: dict,
        *,
        media_sequence: int,
        start: bool,
        final: bool,
        turn_aware: bool,
    ) -> None:
        eventpoint: dict = dict(textevent or {})
        if turn_aware:
            eventpoint["media_sequence"] = media_sequence
            eventpoint["fragment_start"] = start
            eventpoint["fragment_end"] = final
        if start:
            eventpoint.update({"status": "start", "text": text})
        elif final:
            eventpoint.update({"status": "end", "text": text})
        self.parent.put_audio_frame(samples, eventpoint)
