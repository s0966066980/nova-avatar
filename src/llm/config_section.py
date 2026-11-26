# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's configuration entry points for the core's config loader.

``migrate_config`` brings a saved ``llm`` section under the current fields,
``validate_config`` fixes the endpoint table of the built section, and
``export_config`` gives the layer-derived values the runtime overrides persist.
"""
from __future__ import annotations

from typing import Any

from src.llm.endpoints import freeze_endpoints
from src.llm.rules import rules_from_config


def migrate_config(section: dict[str, Any]) -> dict[str, Any]:
    """Return a saved ``llm`` section with retired fields removed or moved."""
    migrated = dict(section)
    # The keyword reply router was removed (ADR-0012); older files may still name it.
    migrated.pop("response_router", None)
    if not isinstance(migrated.get("assistant_profile"), dict):
        prompt = str(migrated.get("system_prompt", "") or "").strip()
        if prompt:
            # One-way Phase-1 migration for existing runtime_overrides.yaml files.
            # The next console save persists this value under assistant_profile.
            migrated["assistant_profile"] = {"system_prompt": prompt}
    return migrated


def validate_config(llm: Any) -> None:
    """Fix the endpoint table at load time and select the active endpoint."""
    freeze_endpoints(llm)


def export_config(config: Any) -> dict[str, Any]:
    """Values of the ``llm`` section that the layer derives for persistence."""
    return {"reply_rules": rules_from_config(config)}
