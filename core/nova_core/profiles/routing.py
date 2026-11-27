# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The core's side of a handoff decision: the role composition becomes the LLM layer's request.

The LLM layer decides (``LlmService.route_handoff``); the composition, the
site's default location and the conversation's confirmed place stay with the
core and are sent on every request (ADR 0027).
"""
from __future__ import annotations

from nova_contracts.common import ServiceError
from nova_contracts.llm import ChatMessage, HandoffRequest, LlmService, RoleCandidate
from src.llm.config_section import llm_settings
from src.profiles.composition import live_members, main_profile_id
from src.profiles.language import fixed_text
from src.profiles.validation import ProfileError


def candidates(library: dict) -> list[str]:
    """Who may answer a turn: the main avatar, then the live members in order."""
    return [main_profile_id(library), *(m["profile_id"] for m in live_members(library))]


def weather_member(library: dict) -> dict | None:
    """The live member holding the weather tool, if any."""
    return next((m for m in live_members(library) if m["tools"]["weather"]["enabled"]), None)


def role_candidates(library: dict) -> list[RoleCandidate]:
    """The main avatar and live members, each with its description and handoff rules."""
    profiles = {p["id"]: p for p in library["profiles"]}
    main = library["composition"]["main"]
    holder = weather_member(library)
    result = []
    for entry in [main, *live_members(library)]:
        site = entry["tools"]["weather"] if entry is holder else None
        result.append(RoleCandidate(
            id=entry["profile_id"], name=profiles[entry["profile_id"]]["name"], main=entry is main,
            description=entry["description"], rules=entry["rules"],
            weather_site=None if site is None else {"county": site["county"], "town": site["town"]}))
    return result


def route_question(config, library, current_id, text, history, confirmed, *, llm: LlmService,
                   explain=False):
    """Who answers ``text``: ``target`` is a candidate's profile id, or None to clarify.

    ``history`` is the current role's recent conversation and ``confirmed``
    the place this conversation last confirmed; neither outlives it.
    """
    locale = getattr(getattr(config, "conversation", None), "locale", "zh-TW")
    try:
        decision = llm.route_handoff(HandoffRequest(
            settings=llm_settings(config), locale=locale, question=text,
            candidates=tuple(role_candidates(library)), current_role=current_id,
            history=tuple(ChatMessage(role=m["role"], content=m["content"]) for m in history),
            confirmed=dict(confirmed), explain=explain))
    except ServiceError as exc:
        raise ProfileError(str(exc)) from exc
    result = decision.model_dump()
    if result["reason"] is None:
        del result["reason"]
    result["clarification"] = fixed_text(result["clarification"], locale)
    return result
