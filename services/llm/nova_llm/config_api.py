# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""What the core's configuration loader may ask of the LLM layer."""
from nova_llm.endpoints import freeze_endpoints
from nova_llm.rules import rules_from_config

__all__ = ["freeze_endpoints", "rules_from_config"]
