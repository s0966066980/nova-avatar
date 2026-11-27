# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What every processing layer's contract uses."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base of every DTO that crosses a layer boundary.

    Immutable, and unknown fields are rejected so a drifting producer fails
    loudly at the boundary instead of being silently half-read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ServiceHealth(ContractModel):
    """``GET /health`` of a processing-layer service (ADR 0027)."""

    contract_version: str
    engine: str
    ready: bool


class ErrorBody(ContractModel):
    """The JSON body of every non-2xx response; ``detail`` is shown to operators."""

    detail: str


class ServiceError(RuntimeError):
    """A layer refused or failed a request for a reason the operator can act on.

    In-process adapters raise it; over HTTP it is a non-2xx status with an
    ``ErrorBody``. Anything else escaping an adapter is a bug.
    """
