# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""BreezyVoice (MediaTek Research, Apache-2.0): Taiwanese Mandarin voice cloning.

Runs in the owned CosyVoice server process (``scripts/cosyvoice_fastapi_server.py``),
which adds BreezyVoice's g2pW 注音 frontend. BreezyVoice does not stream: each
playable reply fragment is synthesized whole and returned as 22.05 kHz PCM16.
The reference recording and its transcript come from the voice library.
"""

from __future__ import annotations

from src.tts.cosyvoice_runtime import prepare_prompt_wav
from src.tts.engines.cosyvoice import CosyVoiceTTS
from src.tts.voice_library import voice_path, voice_transcript


class BreezyVoiceTTS(CosyVoiceTTS):
    SOURCE_SAMPLE_RATE = 22050
    LOG_NAME = "breezyvoice"

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
