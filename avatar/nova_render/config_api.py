# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What the core's configuration loader may ask of the avatar rendering layer.

``quality_from_model`` pulls in OpenCV, so callers import this module lazily, on
the write path only.
"""
from nova_render.mouth_quality import quality_from_model

__all__ = ["quality_from_model"]
