# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The one rule for what may be used as an avatar id (it becomes a directory name)."""
from __future__ import annotations

import re

AVATAR_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


def is_safe_avatar_id(avatar_id: str) -> bool:
    return bool(avatar_id) and bool(re.fullmatch(AVATAR_ID_PATTERN, avatar_id))
