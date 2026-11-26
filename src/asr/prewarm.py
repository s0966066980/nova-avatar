# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Prime the selected speech recognizer without creating a voice session."""
from src.asr.factory import get_asr_engine


def prewarm_recognizer(config) -> None:
    """Load the configured recognizer and run one inference; raises on failure."""
    engine = get_asr_engine(config.asr.type, model_size=config.asr.model_size, config=config)
    engine.set_language(config.asr.language)
    engine.prewarm()
