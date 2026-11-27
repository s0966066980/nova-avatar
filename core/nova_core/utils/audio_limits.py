# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Errors shared by every layer that accepts audio from outside."""
from __future__ import annotations


class AudioTooLongError(ValueError):
    """The audio is longer than the caller allows."""

    def __init__(self, limit_seconds: float):
        self.limit_seconds = float(limit_seconds)
        super().__init__(f'音訊長度超過 {self.limit_seconds:g} 秒上限')
