# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prime the selected local recognizer without creating a voice session."""
from nova_stt.factory import get_asr_engine


def prewarm_asr(config) -> None:
    """Load the configured recognizer and run one inference so the first turn is not slow."""
    engine = get_asr_engine(config.asr.type, model_size=config.asr.model_size, config=config)
    engine.set_language(config.asr.language)
    engine.prewarm()
