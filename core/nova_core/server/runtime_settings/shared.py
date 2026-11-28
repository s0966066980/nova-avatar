# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Settings plumbing shared by every settings module."""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from nova_core.config.overrides import persist_runtime_overrides  # noqa: F401  (tests patch it here)

_SWITCH_LOCK = threading.Lock()


class SettingsError(Exception):
    def __init__(self, message: str, status: int = 400, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra or {}
