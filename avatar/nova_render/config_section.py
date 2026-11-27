# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The avatar rendering layer's configuration entry points for the core's config loader."""
from __future__ import annotations

from typing import Any

# Sections of avatar engines removed in 2026; saved settings may still carry them.
REMOVED_ENGINE_SECTIONS = ("ernerf", "talkinggaussian", "wav2lip")


def migrate_config(section: dict[str, Any]) -> dict[str, Any]:
    """Return a saved ``model`` section without the sections of removed engines."""
    return {key: value for key, value in section.items() if key not in REMOVED_ENGINE_SECTIONS}


def export_config(model: Any) -> dict[str, Any]:
    """Mouth-quality values of the ``model`` section to persist."""
    # Loading a configuration is also used by offline release checks; keep the
    # OpenCV-dependent quality code on the write path that needs it.
    from nova_render.mouth_quality import quality_from_model

    return quality_from_model(model)
