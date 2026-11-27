# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prime the speech input path (VAD, then the recognizer) at startup.

The core composes the two: the STT layer prewarms only its recognizer and does
not know about the VAD.
"""
import numpy as np

from src.asr.prewarm import prewarm_asr
from src.utils.logging import logger
from src.vad.factory import create_vad_from_config


def prewarm_speech_input(config) -> bool:
    if not config.vad.enabled:
        return True
    vad = None
    try:
        vad = create_vad_from_config(config.vad, config)
        vad.ensure_ready()
        vad.speech_prob(np.zeros(vad.frame_samples, dtype=np.int16))
        prewarm_asr(config)
        return True
    except Exception as exc:
        logger.warning('Speech input prewarm failed type=%s; session preparation may retry',
                       type(exc).__name__)
        return False
    finally:
        if vad is not None:
            vad.close()
