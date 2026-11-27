# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The identity of one unit of work inside a reply turn."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnEnvelope:
    turn_id: str
    generation: int
    stage: str
    sequence: int
