# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Who answers a turn: the core's side of the handoff decision.

The decision itself belongs to the LLM layer (``src.llm.handoff``). This module
prepares its input from the role composition (ADR 0023) and turns its answer
into the core's own types: the main avatar and the live members become plain
member dicts, a routing failure becomes a ``ProfileError``, and fixed replies
follow the conversation language.
"""
from __future__ import annotations

from openai import OpenAI

from src.llm import handoff
from src.llm.handoff import CLARIFY, WEATHER_FIELDS, RoutingClients, route_schema
from src.profiles.composition import live_members, main_profile_id
from src.profiles.language import fixed_text
from src.profiles.validation import ProfileError

__all__ = [
    "CLARIFY",
    "WEATHER_FIELDS",
    "RoutingClients",
    "candidates",
    "route_question",
    "route_schema",
    "weather_member",
]


def candidates(library: dict) -> list[str]:
    """Who may answer a turn: the main avatar, then the live members in order."""
    return [main_profile_id(library), *(m["profile_id"] for m in live_members(library))]


def weather_member(library: dict) -> dict | None:
    """The live member holding the weather tool, if any."""
    return next((m for m in live_members(library) if m["tools"]["weather"]["enabled"]), None)


def _members(library: dict) -> list[dict]:
    """The main avatar and live members as the LLM layer's plain member dicts."""
    profiles = {p["id"]: p for p in library["profiles"]}
    composition = library["composition"]
    holder = weather_member(library)
    members = []
    for entry in [composition["main"], *live_members(library)]:
        site = entry["tools"]["weather"] if entry is holder else None
        members.append({
            "id": entry["profile_id"],
            "name": profiles[entry["profile_id"]]["name"],
            "main": entry is composition["main"],
            "description": entry["description"],
            "rules": entry["rules"],
            "weather": None if site is None else {"county": site["county"], "town": site["town"]},
        })
    return members


def route_question(config, library, current_id, text, history, confirmed, *,
                   clients=None, client_factory=OpenAI, explain=False):
    """Who answers ``text``: ``target`` is a candidate's profile id, or None to clarify.

    ``history`` is the current role's recent conversation. The weather fields
    are always present and filled only for the live weather-tool holder.
    ``explain`` (the console's handoff dry run) also returns a short ``reason``.
    """
    try:
        result = handoff.route(
            config, _members(library), current_id, text, history, confirmed,
            clients=clients, client_factory=client_factory, explain=explain,
        )
    except handoff.RoutingError as exc:
        raise ProfileError(str(exc)) from exc
    locale = getattr(getattr(config, "conversation", None), "locale", "zh-TW")
    result["clarification"] = fixed_text(result["clarification"], locale)
    return result
