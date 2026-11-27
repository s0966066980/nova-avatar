# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's tools as the core calls them; their modules are internal.

The weather tool queries CWA for a place the handoff decision accepted and
turns the result into the answer's tool facts. Its cache is shared by every
conversation; the place itself belongs to one conversation (CONTEXT.md).
"""
from nova_llm.tools.weather import CwaWeather, WeatherQuery, weather_prompt

__all__ = ["CwaWeather", "WeatherQuery", "weather_prompt"]
