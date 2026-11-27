# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The string rule for an avatar id, shared by the core and every processing layer."""
from __future__ import annotations

import re

AVATAR_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


def is_safe_avatar_id(avatar_id: str) -> bool:
    """Whether ``avatar_id`` is safe to use as one path segment or settings key."""
    return bool(avatar_id) and bool(re.fullmatch(AVATAR_ID_PATTERN, avatar_id))
