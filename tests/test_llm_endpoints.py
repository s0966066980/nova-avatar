# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""LLM endpoints are a config-file allowlist; profiles and requests only name them."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml

from src.config.schema import Config
from src.profiles.store import ProfileError, ProfileStore, profile_config, validate_profile
from src.server.state import state
from tests.access_helpers import access_client, same_origin

SERVER_KEY = "server-only-test-credential"
REMOTE_KEY = "remote-endpoint-credential"
ATTACKER_URL = "http://attacker.example/v1"


def _config(endpoints=None):
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    config.llm.provider = "llamacpp"
    config.llm.base_url = "http://127.0.0.1:8080/v1"
    config.llm.api_key = SERVER_KEY
    config.llm.model = "local.gguf"
    config.llm.assistant_profile.system_prompt = "接待規則"
    if endpoints is not None:
        config.llm.endpoints = endpoints
    return config


@pytest.fixture
def no_rag(monkeypatch):
    monkeypatch.setattr("src.profiles.store.avatar_settings",
                        lambda _: {"enabled": False, "dataset_ids": []})


def _ai_greeting(profile):
    profile = deepcopy(profile)
    profile["greeting"] = dict(mode="ai", scripts=[], scripts_en=[], prompt="打招呼",
                               min_chars=1, max_chars=60)
    return profile


class RecordingClient:
    """An AsyncOpenAI stand-in that records where a request would have gone."""

    calls: list[dict] = []

    def __init__(self, **kwargs):
        RecordingClient.calls.append(kwargs)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="歡迎光臨"))])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def test_existing_install_without_endpoints_keeps_its_current_server():
    from src.llm.endpoints import configured_endpoints

    endpoints = configured_endpoints(_config().llm)
    assert list(endpoints) == ["llamacpp"]
    endpoint = endpoints["llamacpp"]
    assert (endpoint.provider, endpoint.base_url, endpoint.api_key) == (
        "llamacpp", "http://127.0.0.1:8080/v1", SERVER_KEY)


@pytest.mark.parametrize("bad", [
    {"provider": "anthropic", "base_url": "http://gpu.lan:8000/v1"},
    {"provider": "openai", "base_url": "http://user:secret@gpu.lan/v1"},
    {"provider": "openai", "base_url": "ftp://gpu.lan/v1"},
    {"provider": "openai", "base_url": "http://gpu.lan/v1?token=1"},
    {"provider": "openai", "base_url": "http://gpu.lan/v1", "extra": 1},
])
def test_invalid_endpoint_definitions_are_rejected(bad):
    from src.llm.endpoints import EndpointError, configured_endpoints

    with pytest.raises(EndpointError):
        configured_endpoints(_config({"bad": bad}).llm)


def test_provider_is_explicit_and_not_guessed_from_the_port():
    from src.llm.endpoints import apply_endpoint

    config = _config({"gpu": {"provider": "openai", "base_url": "http://gpu.lan:11434/v1"},
                      "ollama": {"provider": "ollama", "base_url": "http://ollama.lan:9000/v1"}})
    apply_endpoint(config.llm, "gpu")
    assert config.llm.provider == "openai"
    apply_endpoint(config.llm, "ollama")
    assert (config.llm.provider, config.llm.base_url) == ("ollama", "http://ollama.lan:9000/v1")


def test_profile_uses_named_endpoint_and_its_own_key_only(no_rag, tmp_path):
    config = _config({"local": {"provider": "llamacpp", "base_url": "http://127.0.0.1:8080/v1",
                                "api_key": SERVER_KEY},
                      "remote": {"provider": "openai", "base_url": "https://llm.example/v1",
                                 "api_key": REMOTE_KEY},
                      "keyless": {"provider": "ollama", "base_url": "http://ollama.lan:11434/v1"}})
    store = ProfileStore(tmp_path / "profiles.yaml")
    library = store.initialize(config)
    main = library["profiles"][0]
    assert main["llm"]["endpoint"] == "local"
    assert "base_url" not in main["llm"] and "provider" not in main["llm"]
    main["llm"]["endpoint"] = "remote"
    applied = profile_config(config, main)
    assert (applied.llm.provider, applied.llm.base_url, applied.llm.api_key) == (
        "openai", "https://llm.example/v1", REMOTE_KEY)
    main["llm"]["endpoint"] = "keyless"
    assert profile_config(config, main).llm.api_key == ""


@pytest.mark.parametrize("change", [
    lambda llm: llm.update(endpoint="not-configured"),
    lambda llm: llm.update(endpoint=""),
    lambda llm: llm.update(base_url=ATTACKER_URL),
    lambda llm: llm.update(provider="openai"),
])
def test_store_rejects_profiles_that_do_not_name_a_configured_endpoint(no_rag, tmp_path, change):
    store = ProfileStore(tmp_path / "profiles.yaml")
    library = store.initialize(_config())
    before = store.path.read_bytes()
    change(library["profiles"][0]["llm"])
    with pytest.raises(ProfileError):
        store.save(library, expected_revision=library["revision"])
    assert store.path.read_bytes() == before


def _legacy_library(store, config, base_url):
    library = store.initialize(config)
    raw = deepcopy(library)
    for profile in raw["profiles"]:
        llm = profile["llm"]
        llm.pop("endpoint")
        llm.update(provider="llamacpp", base_url=base_url)
    store.path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return raw


def test_legacy_profiles_map_to_the_endpoint_with_the_same_url(no_rag, tmp_path):
    config = _config()
    store = ProfileStore(tmp_path / "profiles.yaml")
    raw = _legacy_library(store, config, "http://127.0.0.1:8080/v1/")
    migrated = store.initialize(config)
    assert [p["llm"]["endpoint"] for p in migrated["profiles"]] == ["llamacpp", "llamacpp"]
    assert migrated["revision"] == raw["revision"] + 1
    assert "base_url" not in store.path.read_text("utf-8")
    assert profile_config(config, migrated["profiles"][0]).llm.base_url == "http://127.0.0.1:8080/v1"


def test_legacy_profile_with_unlisted_url_is_refused_on_apply(no_rag, tmp_path):
    config = _config()
    store = ProfileStore(tmp_path / "profiles.yaml")
    _legacy_library(store, config, ATTACKER_URL)
    before = store.path.read_bytes()
    library = store.initialize(config)
    # The admin can still open the library and pick an endpoint in the console.
    assert library["profiles"][0]["llm"]["endpoint"] == ""
    assert store.path.read_bytes() == before
    with pytest.raises(ProfileError, match="LLM 端點"):
        profile_config(config, library["profiles"][0])


@pytest.fixture
def greeting_route(no_rag, tmp_path, monkeypatch):
    config = _config()
    library = ProfileStore(tmp_path / "profiles.yaml").initialize(config)
    monkeypatch.setattr(state, "config", config)
    async def close():
        return None

    monkeypatch.setattr(state, "roles", SimpleNamespace(enabled=False, close=close), raising=False)
    monkeypatch.setattr("src.greetings.content.AsyncOpenAI", RecordingClient)
    RecordingClient.calls = []
    return _ai_greeting(library["profiles"][0])


def _preview(profile):
    async def run():
        async with access_client() as client:
            response = await client.post("/api/profiles/greeting/preview", json={"profile": profile},
                                         headers=same_origin(client))
            return response.status, await response.text()
    return asyncio.run(run())


@pytest.mark.parametrize("llm_change", [
    {"endpoint": "not-configured"},
    {"endpoint": "llamacpp", "base_url": ATTACKER_URL},
])
def test_greeting_preview_cannot_send_the_key_to_an_unlisted_host(greeting_route, llm_change):
    profile = greeting_route
    profile["llm"].update(llm_change)
    assert 400 <= _preview(profile)[0] < 500
    assert RecordingClient.calls == []


def test_greeting_preview_rejects_a_legacy_external_base_url(greeting_route):
    profile = greeting_route
    profile["llm"].pop("endpoint")
    profile["llm"].update(provider="openai", base_url=ATTACKER_URL)
    assert 400 <= _preview(profile)[0] < 500
    assert RecordingClient.calls == []


def test_greeting_preview_reaches_only_the_named_endpoint(greeting_route):
    status, body = _preview(greeting_route)
    assert status == 200, body
    assert [(c["base_url"], c["api_key"]) for c in RecordingClient.calls] == [
        ("http://127.0.0.1:8080/v1", SERVER_KEY)]


def test_validate_profile_never_returns_a_url():
    config = _config()
    from src.profiles.store import validate_library  # noqa: F401  (module import check)

    profile = {"id": "main", "name": "接待", "engine": "musetalk", "avatar_id": "musetalk_angela",
               "assistant_profile": {}, "llm": {"endpoint": "llamacpp", "model": "m"},
               "tts": {}, "rag": {"enabled": False, "dataset_ids": []},
               "reply_rules": {"activation": "a", "speech": "b", "board": "c"}}
    validated = validate_profile(profile)
    assert set(validated["llm"]) >= {"endpoint", "model"}
    assert not {"base_url", "provider", "api_key"} & set(validated["llm"])
    assert profile_config(config, validated).llm.endpoint == "llamacpp"


def test_model_catalog_lists_endpoints_without_keys(monkeypatch):
    from src.server import runtime_settings

    config = _config({"local": {"provider": "llamacpp", "base_url": "http://127.0.0.1:8080/v1",
                                "api_key": SERVER_KEY},
                      "lan": {"provider": "ollama", "base_url": "http://ollama.lan:9000/v1",
                              "api_key": REMOTE_KEY}})
    asked = []

    async def fake_ollama(base_url):
        asked.append(base_url)
        return {"reachable": True, "models": [{"name": "qwen"}], "error": ""}

    monkeypatch.setattr(runtime_settings, "fetch_ollama_models", fake_ollama)
    monkeypatch.setattr(runtime_settings, "list_gguf_models", lambda *_: [{"name": "local.gguf"}])
    catalog = asyncio.run(runtime_settings.fetch_llm_catalog(config))
    assert asked == ["http://ollama.lan:9000/v1"]
    endpoints = catalog["endpoints"]
    assert {e["name"]: e["provider"] for e in endpoints} == {"local": "llamacpp", "lan": "ollama"}
    assert SERVER_KEY not in repr(catalog) and REMOTE_KEY not in repr(catalog)


def test_global_switch_accepts_only_configured_endpoints(monkeypatch):
    from src.server import runtime_settings
    from src.server.runtime_settings import SettingsError, apply_llm_model

    config = _config({"local": {"provider": "llamacpp", "base_url": "http://127.0.0.1:8080/v1"},
                      "lan": {"provider": "ollama", "base_url": "http://ollama.lan:9000/v1",
                              "api_key": REMOTE_KEY}})
    monkeypatch.setattr(runtime_settings, "persist_runtime_overrides", lambda _: None)
    switched = []
    monkeypatch.setattr(runtime_settings, "switch_llm_endpoint", lambda **kw: switched.append(kw))
    with pytest.raises(SettingsError):
        apply_llm_model(config, "qwen", "attacker")
    result = apply_llm_model(config, "qwen", "lan")
    assert (result["provider"], result["base_url"], result["endpoint"]) == (
        "ollama", "http://ollama.lan:9000/v1", "lan")
    assert (switched[-1]["base_url"], switched[-1]["api_key"]) == ("http://ollama.lan:9000/v1", REMOTE_KEY)


def test_loaded_config_freezes_endpoints_and_persists_only_the_selection(tmp_path, monkeypatch):
    from src.config import loader, overrides

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"llm": {
        "provider": "llamacpp", "base_url": "http://127.0.0.1:8080/v1", "api_key": SERVER_KEY,
        "model": "local.gguf"}}), encoding="utf-8")
    monkeypatch.setattr(overrides, "RUNTIME_OVERRIDES_FILE", tmp_path / "runtime_overrides.yaml")
    config = loader.load_config(str(path))
    assert config.llm.endpoint == "llamacpp"
    config.llm.base_url = "http://127.0.0.1:9999/v1"  # e.g. a restarted local server
    from src.llm.endpoints import configured_endpoints
    assert configured_endpoints(config.llm)["llamacpp"].base_url == "http://127.0.0.1:8080/v1"
    overrides.persist_runtime_overrides(config)
    saved = yaml.safe_load((tmp_path / "runtime_overrides.yaml").read_text("utf-8"))
    assert saved["llm"]["endpoint"] == "llamacpp"
    assert "endpoints" not in saved["llm"]
