# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""In-process adapter that presents a TTS engine as the ``TtsService`` contract."""
from __future__ import annotations

import queue
import threading
from typing import Any, Iterator

import numpy as np
from nova_contracts.tts import SynthesizeRequest

from nova_tts.base import State
from nova_tts.factory import create_tts_engine

_END = object()


def _pcm16(samples: Any) -> bytes:
    array = np.asarray(samples)
    if array.dtype != np.int16:
        array = np.clip(array.astype(np.float32), -1.0, 1.0)
        array = (array * 32767.0).astype(np.int16)
    return array.tobytes()


class _PcmSink:
    """Collects the engine's PCM frames for the request currently being served."""

    def __init__(self) -> None:
        self.frames: "queue.Queue" = queue.Queue()

    def put_audio_frame(self, samples: Any, eventpoint: dict | None = None) -> bool:
        self.frames.put(_pcm16(samples))
        return True


class TtsAdapter:
    def __init__(self, config) -> None:
        self._sink = _PcmSink()
        self._engine = create_tts_engine(config.tts.type, config, self._sink)

    def synthesize(self, request: SynthesizeRequest) -> Iterator[bytes]:
        event = {
            "turn_id": request.turn_id, "generation": request.generation,
            "fragment_sequence": request.fragment_sequence,
        } if request.turn_id else {}
        failure: list[Exception] = []
        finished = False
        self._engine.state = State.RUNNING

        def run() -> None:
            try:
                self._engine.txt_to_audio((request.text, event))
            except Exception as exc:
                failure.append(exc)
            finally:
                self._sink.frames.put(_END)

        threading.Thread(target=run, daemon=True).start()
        try:
            while True:
                frame = self._sink.frames.get()
                if frame is _END:
                    finished = True
                    break
                yield frame
        finally:
            if not finished:
                # The caller stopped early: cancel what the engine is still doing.
                self._engine.flush_talk()
        if failure:
            raise failure[0]

    def flush(self) -> None:
        self._engine.flush_talk()
