# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定：LLM 端點與模型、助手設定與回覆規則。"""
from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from typing import Any, Dict, Optional
from nova_llm.config_section import (
    DEFAULT_RESPONSE_MAX_CHARS,
    EndpointError,
    active_endpoint_name,
    apply_endpoint,
    configured_endpoints,
    default_rules,
    load_system_prompt,
    local_server_settings,
    resolve_endpoint,
    response_token_budget,
    rules_from_config,
    snapshot_from_config,
    validate_response_max_chars,
    validate_rules,
)
from nova_contracts.common import ServiceError
from nova_contracts.llm import LlmEngineSettings, LlmService, LocalModelsQuery, LocalServerQuery
from nova_core.utils.logging import logger
from nova_core.server.runtime_settings import shared
from nova_core.server.runtime_settings.shared import SettingsError


_RULES_LOCK = threading.RLock()


MIN_BOARD_MAX_ITEMS = 1


MAX_BOARD_MAX_ITEMS = 12


def assistant_profile_snapshot(config) -> Dict[str, Any]:
    """Return the profile currently effective for this process, including migration."""
    profile = getattr(config.llm, "assistant_profile", None)
    return {
        "assistant_name": str(getattr(profile, "assistant_name", "") or ""),
        "system_prompt": load_system_prompt(config),
        "restriction_prompt": str(getattr(profile, "restriction_prompt", "") or ""),
        "output_locale": str(getattr(profile, "output_locale", "zh-TW") or "zh-TW"),
        "enforce_output_locale": bool(getattr(profile, "enforce_output_locale", True)),
        "forbidden_self_names": list(getattr(profile, "forbidden_self_names", []) or []),
    }


def validate_assistant_profile(values: Any) -> Dict[str, Any]:
    if not isinstance(values, dict):
        raise SettingsError("助手設定必須是物件")
    name = str(values.get("assistant_name", "") or "").strip()
    prompt = str(values.get("system_prompt", "") or "").strip()
    restrictions = str(values.get("restriction_prompt", "") or "").strip()
    locale = str(values.get("output_locale", "zh-TW") or "zh-TW").strip()
    enabled = values.get("enforce_output_locale", True)
    forbidden = values.get("forbidden_self_names", [])
    if not prompt:
        raise SettingsError("System Prompt 不可為空")
    if len(name) > 200 or len(prompt) > 8000 or len(restrictions) > 8000:
        raise SettingsError("助手名稱、System Prompt 或限制 Prompt 超過長度限制")
    if locale not in {"zh-TW", "en-US"}:
        raise SettingsError("輸出語系目前只支援 zh-TW 或 en-US")
    if not isinstance(enabled, bool):
        raise SettingsError("強制語系正規化必須是布林值")
    if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
        raise SettingsError("禁止自稱名稱必須是字串陣列")
    return {
        "assistant_name": name,
        "system_prompt": prompt,
        "restriction_prompt": restrictions,
        "output_locale": locale,
        "enforce_output_locale": enabled,
        "forbidden_self_names": [item.strip() for item in forbidden if item.strip()][:100],
    }


def ollama_native_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url or "http://localhost:11434"


def _is_embedding_model(name: str, family: str = "") -> bool:
    blob = f"{name} {family}".lower()
    return "embed" in blob or "bert" in blob


def format_bytes(size: Optional[int]) -> str:
    if not size or size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit in {"B", "KB"}:
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""


def resolve_provider(config) -> str:
    """The active endpoint's explicit provider; never guessed from the URL."""
    return resolve_endpoint(config.llm, active_endpoint_name(config.llm)).provider


def endpoint_choices(config) -> list[Dict[str, str]]:
    return [item.public() for item in configured_endpoints(config.llm).values()]


def reply_rules_snapshot(config) -> Dict[str, Any]:
    """Return the currently published Rule snapshot and editable defaults."""
    return {
        "rules": rules_from_config(config),
        "defaults": {"revision": 1, **default_rules()},
        "limits": {"max_rule_chars": 12000, "max_total_chars": 24000},
    }


def apply_reply_rules(config, values: Any, expected_revision: Any = None) -> Dict[str, Any]:
    """Validate, persist and publish all three rules as one version."""
    if not isinstance(values, dict):
        raise SettingsError("Rule 必須是物件")
    with _RULES_LOCK:
        current = snapshot_from_config(config)
        if expected_revision is not None:
            try:
                expected = int(expected_revision)
            except (TypeError, ValueError) as exc:
                raise SettingsError("expected_revision 必須是整數") from exc
            if isinstance(expected_revision, float) and not expected_revision.is_integer():
                raise SettingsError("expected_revision 必須是整數")
            if expected != current.revision:
                raise SettingsError(
                    "Rule 版本已更新，請重新載入後再儲存",
                    status=409,
                    extra={"current": current.as_dict()},
                )
        try:
            checked = validate_rules(values, revision=current.revision + 1)
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc
        rule_config = getattr(config.llm, "reply_rules", None)
        if rule_config is None:
            from nova_core.config.schema import ReplyRulesConfig
            rule_config = ReplyRulesConfig()
            config.llm.reply_rules = rule_config
        rule_config.revision = int(checked["revision"])
        rule_config.activation = str(checked["activation"])
        rule_config.speech = str(checked["speech"])
        rule_config.board = str(checked["board"])
        try:
            shared.persist_runtime_overrides(config)
        except Exception as exc:
            # Restore the in-memory snapshot when persistence fails.
            rule_config.revision = current.revision
            rule_config.activation = current.activation
            rule_config.speech = current.speech
            rule_config.board = current.board
            raise SettingsError(f"儲存 Rule 失敗：{exc}", status=500) from exc
        return {
            "rules": rules_from_config(config),
            "applied_revision": int(checked["revision"]),
        }


def apply_llm_behavior(config, assistant_profile: Any, rules: Any, expected_revision: Any = None,
                       *, llm: LlmService) -> Dict[str, Any]:
    """Save the model-independent persona and Rules together, without loading a model."""
    from nova_core.config.schema import AssistantProfileConfig, ReplyRulesConfig

    profile = validate_assistant_profile(assistant_profile)
    with _RULES_LOCK:
        current = snapshot_from_config(config)
        if expected_revision is not None:
            try:
                expected = int(expected_revision)
            except (TypeError, ValueError) as exc:
                raise SettingsError("expected_revision 必須是整數") from exc
            if isinstance(expected_revision, bool) or (
                isinstance(expected_revision, float) and not expected_revision.is_integer()
            ):
                raise SettingsError("expected_revision 必須是整數")
            if expected != current.revision:
                raise SettingsError("Rule 版本已更新，請重新載入後再儲存", status=409,
                                    extra={"current": current.as_dict()})
        try:
            checked = validate_rules(rules, revision=current.revision)
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc
        if any(checked[field] != getattr(current, field) for field in ("activation", "speech", "board")):
            checked["revision"] = current.revision + 1
        previous_profile = config.llm.assistant_profile
        previous_rules = config.llm.reply_rules
        profile_changed = assistant_profile_snapshot(config) != profile
        config.llm.assistant_profile = AssistantProfileConfig(**profile)
        config.llm.reply_rules = ReplyRulesConfig(**checked)
        try:
            shared.persist_runtime_overrides(config)
        except Exception as exc:
            config.llm.assistant_profile = previous_profile
            config.llm.reply_rules = previous_rules
            raise SettingsError(f"儲存 Prompt 與規則失敗：{exc}", status=500) from exc
        llm.apply_engine(LlmEngineSettings(model=config.llm.model,
                                           system_prompt=profile["system_prompt"],
                                           reset_history=profile_changed))
        return {"assistant_profile": profile, "system_prompt": profile["system_prompt"],
                "rules": checked, "applied_revision": checked["revision"],
                "history_reset": profile_changed}


def validate_board_max_items(value) -> int:
    """驗證單輪看板可顯示的項目數。"""
    if isinstance(value, bool):
        raise ValueError("看板項目上限必須是整數")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("看板項目上限必須是整數") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("看板項目上限必須是整數")
    if not MIN_BOARD_MAX_ITEMS <= normalized <= MAX_BOARD_MAX_ITEMS:
        raise ValueError(
            f"看板項目上限必須介於 {MIN_BOARD_MAX_ITEMS} 到 "
            f"{MAX_BOARD_MAX_ITEMS} 之間"
        )
    return normalized


async def fetch_ollama_models(base_url: str) -> Dict[str, Any]:
    import aiohttp

    native = ollama_native_url(base_url)
    timeout = aiohttp.ClientTimeout(total=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            models = await _fetch_ollama_tags(session, native)
            if models is None:
                models = await _fetch_openai_models(session, base_url)
            if models is None:
                return {
                    "reachable": False,
                    "models": [],
                    "error": f"無法連線 Ollama（{native}）",
                }
            return {"reachable": True, "models": models, "error": ""}
    except Exception as exc:
        logger.warning(f"列出 Ollama 模型失敗: {exc}")
        return {
            "reachable": False,
            "models": [],
            "error": f"無法連線 Ollama（{native}）",
        }


async def _fetch_ollama_tags(session, native_url: str):
    try:
        async with session.get(f"{native_url}/api/tags") as resp:
            if resp.status != 200:
                return None
            payload = await resp.json()
    except Exception:
        return None

    items = []
    for item in payload.get("models") or []:
        name = item.get("name") or item.get("model")
        if not name or _is_embedding_model(name, (item.get("details") or {}).get("family")):
            continue
        details = item.get("details") or {}
        items.append(
            {
                "name": name,
                "size": item.get("size"),
                "size_label": format_bytes(item.get("size")),
                "family": details.get("family") or "",
                "parameter_size": details.get("parameter_size") or "",
            }
        )
    items.sort(key=lambda m: m["name"].lower())
    return items


async def _fetch_openai_models(session, base_url: str, api_key: str = ""):
    url = (base_url or "").rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    # Only the endpoint's own key, and only to that endpoint's URL.
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    try:
        async with session.get(f"{url}/models", headers=headers) as resp:
            if resp.status != 200:
                return None
            payload = await resp.json()
    except Exception:
        return None

    items = []
    for item in payload.get("data") or []:
        name = item.get("id")
        if name and not _is_embedding_model(name, ""):
            items.append(
                {
                    "name": name,
                    "size": None,
                    "size_label": "",
                    "family": "",
                    "parameter_size": "",
                }
            )
    items.sort(key=lambda m: m["name"].lower())
    return items


OLLAMA_ONLY_REQUEST_FIELDS = frozenset({"options", "keep_alive", "think", "reasoning_effort"})


def apply_llm_model(
    config,
    model: str,
    endpoint: str = "",
    system_prompt: Optional[str] = None,
    response_max_chars: Optional[int] = None,
    reply_mode: Optional[str] = None,
    board_max_items: Optional[int] = None,
    assistant_profile: Optional[Dict[str, Any]] = None,
    semantic_wait_seconds: Optional[float] = None,
    *,
    llm: LlmService,
) -> Dict[str, Any]:
    model = (model or "").strip()
    if not model:
        raise SettingsError("請選擇一個對話模型")
    try:
        target = resolve_endpoint(config.llm, endpoint or active_endpoint_name(config.llm))
    except EndpointError as exc:
        raise SettingsError(str(exc)) from exc
    provider = target.provider
    profile_requested = assistant_profile is not None or system_prompt is not None
    previous_profile = assistant_profile_snapshot(config)
    profile_values = assistant_profile
    if profile_values is None:
        profile_values = {**previous_profile}
        if system_prompt is not None:
            profile_values["system_prompt"] = system_prompt
    next_profile = validate_assistant_profile(profile_values)
    next_system_prompt = next_profile["system_prompt"]
    if not next_system_prompt:
        raise SettingsError("預設 Prompt 不可為空")
    try:
        next_response_max_chars = validate_response_max_chars(
            getattr(config.llm, "response_max_chars", DEFAULT_RESPONSE_MAX_CHARS)
            if response_max_chars is None
            else response_max_chars
        )
    except ValueError as exc:
        raise SettingsError(str(exc)) from exc
    try:
        next_board_max_items = validate_board_max_items(
            getattr(getattr(config.llm, "board", None), "max_items", 8)
            if board_max_items is None
            else board_max_items
        )
    except ValueError as exc:
        raise SettingsError(str(exc)) from exc
    next_max_tokens = response_token_budget(next_response_max_chars)
    next_reply_mode = (
        "streaming" if bool(config.reply_streaming.enabled) else "legacy"
    ) if reply_mode is None else str(reply_mode).strip().lower()
    if next_reply_mode not in {"legacy", "streaming"}:
        raise SettingsError("回覆模式必須是 legacy 或 streaming")
    next_semantic_wait = float(
        getattr(config.reply_streaming, "semantic_wait_seconds", 0.5)
        if semantic_wait_seconds is None
        else semantic_wait_seconds
    )
    if not 0.5 <= next_semantic_wait <= 30.0:
        raise SettingsError("語意等待上限必須介於 0.5 至 30 秒")

    previous = f"{config.llm.endpoint or resolve_provider(config)}/{config.llm.model}"
    # URL, provider and key are taken together from the allowlisted endpoint.
    target_llm = deepcopy(config.llm)
    apply_endpoint(target_llm, target.name)
    base_url, api_key = target.base_url, target.api_key
    if provider == "llamacpp":
        try:
            llm.start_local_server(local_server_settings(target_llm, model=model))
        except ServiceError as exc:
            raise SettingsError(f"無法啟動 llama.cpp：{exc}", status=500) from exc
        extra_body = {}
    elif provider == "openai":
        # Strict OpenAI-compatible APIs reject Ollama's request extensions.
        extra_body = {key: value for key, value in (getattr(config.llm, "extra_body", None) or {}).items()
                      if key not in OLLAMA_ONLY_REQUEST_FIELDS}
    else:
        existing_extra = dict(getattr(config.llm, "extra_body", None) or {})
        options = dict(existing_extra.get("options") or {})
        options.update(
            {
                "num_predict": next_max_tokens,
                "num_ctx": options.get("num_ctx", 2048),
                "temperature": options.get("temperature", 0.6),
            }
        )
        extra_body = {
            "reasoning_effort": "none",
            "think": False,
            "keep_alive": -1,
            **existing_extra,
            "options": options,
        }

    with _RULES_LOCK:
        if not profile_requested:
            next_profile = assistant_profile_snapshot(config)
            next_system_prompt = next_profile["system_prompt"]
        apply_endpoint(config.llm, target.name)
        config.llm.model = model
        config.llm.max_tokens = next_max_tokens
        config.llm.response_max_chars = next_response_max_chars
        config.llm.board.max_items = next_board_max_items
        if profile_requested:
            from nova_core.config.schema import AssistantProfileConfig
            config.llm.assistant_profile = AssistantProfileConfig(**next_profile)
        # Model loading may have overlapped a behavior save. Model-only requests
        # always use the latest published profile instead of an earlier snapshot.
        profile_changed = profile_requested and previous_profile != next_profile
        config.llm.extra_body = extra_body
        config.reply_streaming.enabled = next_reply_mode == "streaming"
        config.reply_streaming.semantic_wait_seconds = next_semantic_wait
        llm.apply_engine(LlmEngineSettings(
            model=model,
            base_url=base_url,
            extra_body=extra_body,
            api_key=api_key or provider,
            max_tokens=next_max_tokens,
            response_max_chars=next_response_max_chars,
            system_prompt=next_system_prompt,
            reset_history=profile_changed,
        ))
        shared.persist_runtime_overrides(config)
    logger.info(f"LLM 已切換: {previous} -> {target.name}/{model} @ {base_url}")
    return {
        "model": model,
        "endpoint": target.name,
        "provider": provider,
        "base_url": base_url,
        "system_prompt": next_system_prompt,
        "assistant_profile": next_profile,
        "history_reset": profile_changed,
        "response_max_chars": next_response_max_chars,
        "board_max_items": next_board_max_items,
        "reply_mode": next_reply_mode,
        "semantic_wait_seconds": next_semantic_wait,
    }


async def _endpoint_catalog(config, endpoint, llm: LlmService) -> Dict[str, Any]:
    """Model discovery for one allowlisted endpoint, chosen by its provider."""
    block = {**endpoint.public(), "id": endpoint.name,
             "label": PROVIDER_LABELS[endpoint.provider], "models": []}
    if endpoint.provider == "llamacpp":
        local = deepcopy(config.llm)
        apply_endpoint(local, endpoint.name)
        # Scanning model folders and probing the server block: keep them off the event loop.
        local_models = await asyncio.to_thread(llm.list_local_models, LocalModelsQuery(
            models_dir=getattr(config.llm, "llamacpp_dir", "") or ""))
        ggufs = [model.model_dump() for model in local_models.models]
        status = (await asyncio.to_thread(llm.local_server_status, LocalServerQuery(
            host=local.llamacpp_host, port=int(local.llamacpp_port)))).model_dump()
        binary = local_models.binary
        return {**block, "reachable": bool(binary) or bool(ggufs),
                "error": "" if (binary or ggufs) else "找不到 llama-server 或 GGUF 模型",
                "models": ggufs, "server_running": status["running"], "binary": status["binary"]}
    if endpoint.provider == "ollama":
        found = await fetch_ollama_models(endpoint.base_url)
    else:
        import aiohttp

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                models = await _fetch_openai_models(session, endpoint.base_url, endpoint.api_key)
        except Exception:
            models = None
        found = {"reachable": models is not None, "models": models or [],
                 "error": "" if models is not None else f"無法列出 {endpoint.name} 的模型"}
    return {**block, "reachable": found.get("reachable", False),
            "error": found.get("error", ""), "models": found.get("models") or []}


PROVIDER_LABELS = {"llamacpp": "llama.cpp", "ollama": "Ollama", "openai": "OpenAI 相容服務"}


async def fetch_llm_catalog(config, *, llm: LlmService) -> Dict[str, Any]:
    endpoints = list(configured_endpoints(config.llm).values())
    blocks = await asyncio.gather(*(_endpoint_catalog(config, item, llm) for item in endpoints))
    providers: Dict[str, Any] = {}
    for block in blocks:
        providers.setdefault(block["provider"], block)
    return {
        "current": {
            "endpoint": active_endpoint_name(config.llm),
            "provider": resolve_provider(config),
            "model": config.llm.model,
            "base_url": config.llm.base_url,
        },
        "endpoints": blocks,
        # First endpoint of each provider, for older console views.
        "providers": providers,
    }
