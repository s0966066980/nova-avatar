# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prime the selected local speech path without creating a voice session."""
import numpy as np
from src.asr.factory import get_asr_engine
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
        engine = get_asr_engine(config.asr.type, model_size=config.asr.model_size, config=config)
        engine.set_language(config.asr.language)
        engine.prewarm()
        return True
    except Exception as exc:
        logger.warning('Speech input prewarm failed type=%s; session preparation may retry',
                       type(exc).__name__)
        return False
    finally:
        if vad is not None:
            vad.close()
