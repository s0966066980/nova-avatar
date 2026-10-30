# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Field checks shared by the profile library and the role composition."""
from __future__ import annotations

import re

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}")


class ProfileError(ValueError):
    """A refused profile request; ``extra`` is merged into the JSON error body."""

    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def text(value, label, limit=12000, *, empty=True, field=None):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        extra = {"field": field} if field else {}
        raise ProfileError(f"{label} 格式或長度不正確", **extra)
    return value.strip()


def identifier(value, label="角色識別碼"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProfileError(f"{label} 不正確")
    return value


def obj(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ProfileError(f"{label} 含未知欄位或格式不正確")
    return value


def revision(value, label="設定版本"):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProfileError(f"{label}不正確")
    return value
