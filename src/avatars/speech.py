# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What the avatar renderer needs from whatever speaks for it (defined in ``nova_contracts``).

The core builds the speech source (today a TTS engine) and hands the renderer a
factory for it; the renderer never imports the TTS layer.
"""
from nova_contracts.avatar import SpeechFactory, SpeechSource

__all__ = ["SpeechFactory", "SpeechSource"]
