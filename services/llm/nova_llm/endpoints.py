# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Config-file allowlist of LLM endpoints.

Profiles, console requests and greeting previews only name an endpoint. The
URL, provider and credential always come from this table together, so a
server key is never sent to a host the administrator did not list in the
configuration file.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Mapping
from urllib.parse import urlsplit

PROVIDERS = ("llamacpp", "ollama", "openai")
_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")
_FIELDS = {"provider", "base_url", "api_key"}


class EndpointError(ValueError):
    pass


@dataclass(frozen=True)
class LLMEndpoint:
    name: str
    provider: str
    base_url: str
    api_key: str = ""

    def public(self) -> Dict[str, str]:
        """Console view of the endpoint; the credential never leaves the server."""
        return {"name": self.name, "provider": self.provider, "base_url": self.base_url}


def normalize_base_url(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise EndpointError("LLM 端點網址不可為空且最長 500 字元")
    url = value.strip().rstrip("/")
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise EndpointError("LLM 端點網址須為 http(s)，且不可包含帳密、查詢參數或片段")
    return url


def _endpoint(name, value: Mapping) -> LLMEndpoint:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise EndpointError(f"LLM 端點名稱不正確：{name!r}")
    if not isinstance(value, Mapping) or set(value) - _FIELDS:
        raise EndpointError(f"LLM 端點 {name} 只能設定 provider、base_url 與 api_key")
    provider = value.get("provider")
    if provider not in PROVIDERS:
        raise EndpointError(f"LLM 端點 {name} 的 provider 必須是 {'、'.join(PROVIDERS)}")
    api_key = value.get("api_key") or ""
    if not isinstance(api_key, str):
        raise EndpointError(f"LLM 端點 {name} 的 api_key 必須是字串")
    return LLMEndpoint(name, provider, normalize_base_url(value.get("base_url")), api_key)


def _legacy_endpoint(llm) -> LLMEndpoint:
    """An install without llm.endpoints keeps using its single configured server."""
    provider = str(getattr(llm, "provider", "") or "").strip().lower()
    provider = provider if provider in PROVIDERS else "openai"
    if provider == "llamacpp":
        from src.llm.llamacpp import openai_base_url

        # llama-server is always started at llamacpp_host:llamacpp_port.
        base_url = openai_base_url(getattr(llm, "llamacpp_host", "127.0.0.1") or "127.0.0.1",
                                   int(getattr(llm, "llamacpp_port", 8080) or 8080))
    else:
        base_url = getattr(llm, "base_url", "")
    return _endpoint(provider, {"provider": provider, "base_url": base_url,
                                "api_key": getattr(llm, "api_key", "") or ""})


def configured_endpoints(llm) -> Dict[str, LLMEndpoint]:
    raw = getattr(llm, "endpoints", None) or {}
    if not isinstance(raw, Mapping):
        raise EndpointError("llm.endpoints 必須是「名稱: 端點設定」的對照表")
    if not raw:
        endpoint = _legacy_endpoint(llm)
        return {endpoint.name: endpoint}
    return {name: _endpoint(name, value) for name, value in raw.items()}


def resolve_endpoint(llm, name) -> LLMEndpoint:
    endpoints = configured_endpoints(llm)
    if not isinstance(name, str) or name not in endpoints:
        raise EndpointError(f"LLM 端點 {name!r} 不在設定檔的 llm.endpoints 中")
    return endpoints[name]


def endpoint_for_url(endpoints: Mapping[str, LLMEndpoint], base_url) -> str:
    """Name of the listed endpoint serving ``base_url``, or "" when none does."""
    try:
        url = normalize_base_url(base_url)
    except EndpointError:
        return ""
    return next((name for name, item in endpoints.items() if item.base_url == url), "")


def active_endpoint_name(llm) -> str:
    endpoints = configured_endpoints(llm)
    selected = getattr(llm, "endpoint", "")
    if selected in endpoints:
        return selected
    return endpoint_for_url(endpoints, getattr(llm, "base_url", "")) or next(iter(endpoints))


def apply_endpoint(llm, name) -> LLMEndpoint:
    """Point ``llm`` at a listed endpoint, replacing URL, provider and key together."""
    endpoint = resolve_endpoint(llm, name)
    llm.endpoint = endpoint.name
    llm.provider = endpoint.provider
    llm.base_url = endpoint.base_url
    llm.api_key = endpoint.api_key
    if endpoint.provider == "llamacpp":
        # The managed llama-server must listen where requests are sent.
        parsed = urlsplit(endpoint.base_url)
        llm.llamacpp_host = parsed.hostname
        llm.llamacpp_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return endpoint


def freeze_endpoints(llm) -> None:
    """Fix the endpoint table at load time and select the active endpoint.

    Later runtime changes to ``llm.base_url`` (for example after starting a
    local server) must not change which hosts are allowed.
    """
    endpoints = configured_endpoints(llm)
    name = active_endpoint_name(llm)
    llm.endpoints = {key: {"provider": item.provider, "base_url": item.base_url,
                           "api_key": item.api_key} for key, item in endpoints.items()}
    apply_endpoint(llm, name)
