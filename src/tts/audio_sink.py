# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The narrow interface a TTS engine uses to hand audio and events to its owner.

Defined in ``nova_contracts``; see its docstring for the optional members.
"""
from nova_contracts.tts import AudioSink

__all__ = ["AudioSink"]
