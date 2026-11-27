# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The LLM layer's configuration entry points for the core.

The core owns the one configuration file and its ``llm`` section; this module
is how it migrates, validates and exports that section, resolves an
allowlisted endpoint, validates reply rules and response length, and turns
the section into the ``nova_contracts.llm`` settings a request carries.
None of it calls a model.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from nova_contracts.llm import (
    AssistantProfile,
    LlmSession,
    LlmSettings,
    LocalServerSettings,
    ReplyRules,
)
from src.llm.base import (
    DEFAULT_RESPONSE_MAX_CHARS,
    load_system_prompt,
    response_token_budget,
    validate_response_max_chars,
)
from src.llm.endpoints import (
    EndpointError,
    active_endpoint_name,
    apply_endpoint,
    configured_endpoints,
    endpoint_for_url,
    freeze_endpoints,
    resolve_endpoint,
)
from src.llm.rules import (
    MAX_RULE_CHARS,
    MAX_TOTAL_RULE_CHARS,
    default_rules,
    rules_from_config,
    snapshot_from_config,
    validate_rules,
)

__all__ = [
    "DEFAULT_RESPONSE_MAX_CHARS",
    "EndpointError",
    "MAX_RULE_CHARS",
    "MAX_TOTAL_RULE_CHARS",
    "active_endpoint_name",
    "apply_endpoint",
    "configured_endpoints",
    "default_rules",
    "endpoint_for_url",
    "export_config",
    "llm_session",
    "llm_settings",
    "load_system_prompt",
    "local_server_settings",
    "migrate_config",
    "reply_rules",
    "resolve_endpoint",
    "response_token_budget",
    "rules_from_config",
    "snapshot_from_config",
    "validate_config",
    "validate_response_max_chars",
    "validate_rules",
]


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


def reply_rules(config: Any) -> ReplyRules:
    """The published reply rules of ``config``, validated (defaults fill gaps)."""
    snapshot = snapshot_from_config(config)
    return ReplyRules(revision=snapshot.revision, activation=snapshot.activation,
                      speech=snapshot.speech, board=snapshot.board)


def local_server_settings(llm: Any, *, model: Optional[str] = None) -> LocalServerSettings:
    """The owned llama-server the section describes, serving ``model`` (default: its model)."""
    return LocalServerSettings(
        model=model if model is not None else llm.model,
        models_dir=getattr(llm, "llamacpp_dir", "") or "",
        host=getattr(llm, "llamacpp_host", "127.0.0.1") or "127.0.0.1",
        port=int(getattr(llm, "llamacpp_port", 8080) or 8080),
        ctx=int(getattr(llm, "llamacpp_ctx", 8192) or 8192),
        threads=int(getattr(llm, "llamacpp_threads", 0) or 0),
        allow_partial_offload=bool(getattr(llm, "llamacpp_allow_partial_offload", False)),
    )


def llm_settings(config: Any, *, profile: Any = None, locale: Optional[str] = None) -> LlmSettings:
    """The answer model ``config.llm`` names, speaking as ``profile`` (default: its own).

    ``locale`` replaces the profile's output locale: a conversation speaks its
    own language whatever the profile prefers.
    """
    llm = getattr(config, "llm", None) or SimpleNamespace()
    if profile is None:
        profile = getattr(llm, "assistant_profile", None)
    output_locale = locale or str(getattr(profile, "output_locale", "zh-TW") or "zh-TW")
    view = SimpleNamespace(llm=SimpleNamespace(
        assistant_profile=profile, system_prompt=getattr(llm, "system_prompt", "") or ""))
    provider = str(getattr(llm, "provider", "") or "").strip().lower()
    if provider not in ("llamacpp", "ollama", "openai"):
        provider = "openai"
    return LlmSettings(
        provider=provider,
        base_url=getattr(llm, "base_url", "") or "",
        api_key=getattr(llm, "api_key", "") or "",
        model=getattr(llm, "model", "") or "",
        extra_body=dict(getattr(llm, "extra_body", None) or {}),
        response_max_chars=int(getattr(llm, "response_max_chars", DEFAULT_RESPONSE_MAX_CHARS)
                               or DEFAULT_RESPONSE_MAX_CHARS),
        board_max_items=int(getattr(getattr(llm, "board", None), "max_items", 8) or 8),
        system_prompt=load_system_prompt(view),
        assistant_profile=AssistantProfile(
            assistant_name=str(getattr(profile, "assistant_name", "") or ""),
            system_prompt=str(getattr(profile, "system_prompt", "") or ""),
            restriction_prompt=str(getattr(profile, "restriction_prompt", "") or ""),
            output_locale=output_locale,
            enforce_output_locale=bool(getattr(profile, "enforce_output_locale", True)),
            forbidden_self_names=tuple(getattr(profile, "forbidden_self_names", None) or ()),
        ),
        local_server=local_server_settings(llm) if provider == "llamacpp" else None,
    )


def llm_session(config: Any, session_id: int, *, profile: Any = None) -> LlmSession:
    """One conversation as its LLM requests name it, speaking the conversation's language."""
    conversation = getattr(config, "conversation", None)
    return LlmSession(
        session_id=int(session_id or 0),
        profile_id=str(getattr(config, "profile_id", "") or ""),
        settings=llm_settings(config, profile=profile,
                              locale=getattr(conversation, "locale", None)),
        history_max_messages=int(getattr(conversation, "history_max_messages", 20) or 20),
        snapshot=bool(getattr(config, "conversation_snapshot", False)),
    )
