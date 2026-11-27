# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Cross-layer contracts: the only types the core and the processing layers share.

One module per processing layer (``stt``, ``llm``, ``tts``, ``avatar``) holds
that layer's Pydantic DTOs, its service Protocol and, for a layer that becomes
a loopback service (ADR 0027), its ``HTTP_API``. ``common`` holds what every
layer uses. Nothing here imports anything heavier than Pydantic.
"""
from typing import Final

# The contract has no semantic version (ADR 0028). A separated service reports
# this value at ``GET /health`` and the core refuses a service that reports a
# different one. Change it in the same PR as any breaking contract change.
CONTRACT_VERSION: Final = "1"

__all__ = ["CONTRACT_VERSION"]
