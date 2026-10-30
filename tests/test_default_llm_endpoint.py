# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""The shipped configuration needs no Ollama on 11434; explicit choices still work."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_config

ROOT = Path(__file__).resolve().parents[1]
OLLAMA_URL = "http://localhost:11434/v1"
# Ticket 04 may switch the default GGUF to Gemma 4 E2B after user acceptance.
DEFAULT_GGUFS = {"Qwen3.5-9B-UD-Q4_K_XL", "gemma-4-E2B_q4_0-it"}


@pytest.fixture
def overrides(monkeypatch):
    """Runtime overrides as the console would have saved them; none by default."""
    saved: dict = {}
    monkeypatch.setattr("src.config.overrides.load_runtime_overrides", lambda: saved)
    return saved


def test_shipped_config_selects_the_managed_llama_server(overrides):
    llm = load_config("config/config.yaml").llm

    assert (llm.endpoint, llm.provider) == ("llamacpp", "llamacpp")
    assert llm.base_url == "http://127.0.0.1:8080/v1"
    assert (llm.llamacpp_host, llm.llamacpp_port) == ("127.0.0.1", 8080)
    assert llm.model in DEFAULT_GGUFS
    assert "11434" not in llm.base_url


def test_ollama_stays_an_explicit_opt_in_endpoint(overrides):
    llm = load_config("config/config.yaml").llm

    assert llm.endpoints["ollama"] == {"provider": "ollama", "base_url": OLLAMA_URL,
                                       "api_key": "ollama"}


def test_saved_ollama_selection_still_uses_ollama(overrides):
    overrides["llm"] = {"endpoint": "ollama", "provider": "ollama", "base_url": OLLAMA_URL,
                        "api_key": "ollama", "model": "qwen3.5:4b"}

    llm = load_config("config/config.yaml").llm

    assert (llm.endpoint, llm.provider, llm.base_url) == ("ollama", "ollama", OLLAMA_URL)
    assert llm.model == "qwen3.5:4b"


def test_pre_allowlist_override_naming_only_the_ollama_url_still_uses_ollama(overrides):
    # Overrides saved before llm.endpoint existed carried only provider/base_url.
    overrides["llm"] = {"provider": "ollama", "base_url": OLLAMA_URL, "model": "qwen3.5:4b"}

    llm = load_config("config/config.yaml").llm

    assert (llm.endpoint, llm.provider, llm.base_url) == ("ollama", "ollama", OLLAMA_URL)


def test_legacy_single_endpoint_ollama_config_is_unchanged(overrides):
    llm = load_config("config/config_musetalk.yaml").llm

    assert (llm.provider, llm.base_url) == ("ollama", OLLAMA_URL)


def test_docs_explain_how_to_disable_the_default_ollama():
    installation = (ROOT / "docs/installation.md").read_text(encoding="utf-8")

    assert "sudo systemctl disable --now ollama" in installation
    assert "11437" in installation
