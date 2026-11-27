# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0
#
# _decode_audio_file and SpeakingAvatar.put_audio_file were moved from
# src/avatars/base.py: derived from Kedreamix/Linly-Talker-Stream
# (Copyright [Linly-talker-stream@kedreamix], Apache-2.0), based on LiveTalking
# (C) 2024 LiveTalking@lipku (Apache-2.0). Modified by HongXian0903, 2026.
# See LICENSE and NOTICE for details.

"""The core's pairing of an avatar renderer with the TTS that feeds it.

The renderer does not own TTS (ADR 0027). The core opens a TTS speech channel
with this object as its audio sink, forwards every 20 ms PCM frame to the
renderer, and answers the TTS's fragment questions from the voice session.
Everything else the core asks of the renderer goes to ``renderer``
(``AvatarRenderer``) explicitly.
"""
# Attribute typos on the renderer must fail type-checking here.
# pyright: reportAttributeAccessIssue=error
from __future__ import annotations

from io import BytesIO
from typing import Any

import numpy as np
import resampy
import soundfile as sf

from nova_contracts.avatar import AvatarRenderer
from nova_contracts.tts import TtsRuntime, strip_visual_markup
from src.tts import config_section as tts_section
from src.utils.logging import logger
from src.vad.audio import AudioTooLongError

SAMPLE_RATE = 16000
# Audio files sent to /humanaudio are decoded only up to this length.
MAX_AUDIO_FILE_SECONDS = 300.0


def _decode_audio_file(byte_stream) -> np.ndarray:
    """Decode to mono float32 PCM at 16 kHz, refusing overlong audio."""
    with sf.SoundFile(byte_stream) as audio_file:
        # Check the header's length before decoding; read at most the limit.
        limit = int(MAX_AUDIO_FILE_SECONDS * audio_file.samplerate)
        if audio_file.frames > limit:
            raise AudioTooLongError(MAX_AUDIO_FILE_SECONDS)
        sample_rate = audio_file.samplerate
        stream = audio_file.read(frames=limit + 1)  # [T*sample_rate,] float64
    if stream.shape[0] > limit:
        raise AudioTooLongError(MAX_AUDIO_FILE_SECONDS)
    logger.info(f'[INFO]put audio stream {sample_rate}: {stream.shape}')
    stream = stream.astype(np.float32)
    if stream.ndim > 1:
        logger.info(f'[WARN] audio has {stream.shape[1]} channels, only use the first.')
        stream = stream[:, 0]
    if sample_rate != SAMPLE_RATE and stream.shape[0] > 0:
        logger.info(f'[WARN] audio sample rate is {sample_rate}, resampling into {SAMPLE_RATE}.')
        stream = resampy.resample(x=stream, sr_orig=sample_rate, sr_new=SAMPLE_RATE)
    return stream


class SpeakingAvatar:
    """What the server calls "the avatar" of a session: renderer plus TTS.

    Renderer state (recording, frame size, role presentation, speaking state)
    is read and written on ``renderer``; this object only passes through the
    session's ``config`` (kept on the renderer) and ``sessionid``.
    """

    def __init__(self, renderer: AvatarRenderer, *, speech: TtsRuntime) -> None:
        self.renderer = renderer
        self._on_fragment_queued = None
        self._on_fragment_failed = None
        self._fragment_playback_committed = None
        self._fragment_playback_ended = None
        self._on_tts_onset_preroll_ms = None
        self._on_tts_retry = None
        self._on_stage_end = None
        self._on_llm_chunk = None
        # The session's speech channel; its engine hands PCM to this object.
        self.tts = speech.open_channel(tts_section.voice(renderer.config.tts), self)
        # MuseTalk briefly holds idle frames while more reply PCM is due.
        renderer.configure_pending_audio(self.tts.has_pending_work)

    @property
    def config(self) -> Any:
        """The session's configuration, kept on the renderer (it reads it per frame)."""
        return self.renderer.config

    @config.setter
    def config(self, config: Any) -> None:
        self.renderer.config = config

    @property
    def sessionid(self) -> int:
        return self.renderer.sessionid

    def configure_media_fence(
        self,
        *,
        media_guard,
        on_stale_drop,
        on_fragment_queued=None,
        on_fragment_failed=None,
        fragment_playback_committed=None,
        fragment_playback_ended=None,
        on_tts_onset_preroll_ms=None,
        on_tts_retry=None,
        on_stage_end=None,
        on_llm_chunk=None,
    ) -> None:
        """Attach the voice session's generation authority to media boundaries.

        The renderer gets the fence it checks at its own stages; the fragment
        callbacks stay here, where the TTS asks for them.
        """
        self._on_fragment_queued = on_fragment_queued
        self._on_fragment_failed = on_fragment_failed
        self._fragment_playback_committed = fragment_playback_committed
        self._fragment_playback_ended = fragment_playback_ended
        self._on_tts_onset_preroll_ms = on_tts_onset_preroll_ms
        self._on_tts_retry = on_tts_retry
        self._on_stage_end = on_stage_end
        self._on_llm_chunk = on_llm_chunk
        self.renderer.configure_media_fence(
            media_guard=media_guard,
            on_stale_drop=on_stale_drop,
            on_stage_end=on_stage_end,
        )

    def put_msg_txt(self, msg, datainfo: dict | None = None) -> None:
        msg = strip_visual_markup(msg)
        if not msg:
            return
        eventpoint = dict(datainfo or {})
        if self._on_fragment_queued is not None and eventpoint.get("turn_id"):
            self._on_fragment_queued(msg, eventpoint)
        self.tts.speak(msg, eventpoint)

    def bind_profile(self, config, avatar) -> None:
        """Swap role assets on the renderer and the voice on the TTS."""
        self.tts.flush()
        self.renderer.bind_profile(config, avatar)
        self.tts.set_voice(tts_section.voice(config.tts))

    def flush_talk(self) -> None:
        """Barge-in: stop TTS first so no new PCM follows the renderer's drain."""
        self.tts.flush()
        self.renderer.flush_talk()

    def render(self, quit_event, loop=None, audio_track=None, video_track=None) -> None:
        """Run TTS for the renderer's lifetime; both stop on ``quit_event``."""
        self.tts.run(quit_event)
        try:
            self.renderer.render(quit_event, loop, audio_track, video_track)
        finally:
            # A renderer that failed before its own cleanup must not leave the
            # TTS thread running for a session that has no output.
            quit_event.set()

    def put_audio_file(self, filebyte, datainfo: dict | None = None) -> None:
        """Play an uploaded audio file in renderer-sized frames.

        Blocks while decoding and while waiting for queue space: call it from
        a worker thread.
        """
        stream = _decode_audio_file(BytesIO(filebyte))
        chunk = self.renderer.chunk
        datainfo = datainfo or {}
        for start in range(0, stream.shape[0] - chunk + 1, chunk):
            self.renderer.put_audio_frame(stream[start:start + chunk], datainfo)

    def notify(self, eventpoint: dict) -> None:
        """The media player played a boundary (speech or fragment start or end)."""
        self.renderer.notify(eventpoint)

    def notify_llm_chunk(self, text: str, eventpoint: dict | None = None) -> None:
        if self._on_llm_chunk is not None:
            self._on_llm_chunk(text, dict(eventpoint or {}))

    # Audio sink: what the TTS layer may call (nova_contracts.tts.AudioSink).

    def put_audio_frame(self, samples, eventpoint: dict) -> bool:
        return self.renderer.put_audio_frame(samples, eventpoint)

    def accepts_media(self, eventpoint, stage: str) -> bool:
        return bool(self.renderer.accepts_media(eventpoint, stage))

    def fragment_playback_committed(self, eventpoint: dict) -> bool:
        checker = self._fragment_playback_committed
        return bool(checker(eventpoint)) if callable(checker) else False

    def fragment_playback_ended(self, eventpoint: dict) -> bool:
        checker = self._fragment_playback_ended
        return bool(checker(eventpoint)) if callable(checker) else True

    def notify_fragment_synthesis_failed(self, eventpoint: dict, reason: str) -> None:
        if callable(self._on_fragment_failed):
            self._on_fragment_failed(dict(eventpoint), str(reason))

    def observe_tts_onset_preroll_ms(self, milliseconds: float) -> None:
        if self._on_tts_onset_preroll_ms is not None:
            self._on_tts_onset_preroll_ms(milliseconds)

    def observe_tts_retry(self, *, after_commit: bool) -> None:
        if self._on_tts_retry is not None:
            self._on_tts_retry(after_commit=after_commit)

    def mark_stage_end(self, stage: str) -> None:
        if self._on_stage_end is not None:
            self._on_stage_end(stage)
