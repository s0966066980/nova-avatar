# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""How many stage sessions are connected, for jobs that must not compete with a stage."""
from __future__ import annotations

from src.server.state import state


def count_stage_connections() -> int:
    """Every stage session, including one still connecting (its placeholder is ``None``)."""
    return len(state.avatar_streams)
