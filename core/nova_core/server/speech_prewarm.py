# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prime the local speech-input path (VAD, then STT) without creating a voice session.

The core composes the two: the VAD belongs to the core and the STT layer only
primes its own recognizer.
"""
import numpy as np

from nova_contracts.stt import SttPrepareRequest, SttService
from nova_core.utils.logging import logger
from nova_core.vad.factory import create_vad_from_config


def prewarm_speech_input(config, stt: SttService) -> bool:
    if not config.vad.enabled:
        return True
    vad = None
    try:
        vad = create_vad_from_config(config.vad, config)
        vad.ensure_ready()
        vad.speech_prob(np.zeros(vad.frame_samples, dtype=np.int16))
        stt.prepare(SttPrepareRequest(warm=True))
        return True
    except Exception as exc:
        logger.warning('Speech input prewarm failed type=%s; session preparation may retry',
                       type(exc).__name__)
        return False
    finally:
        if vad is not None:
            vad.close()
