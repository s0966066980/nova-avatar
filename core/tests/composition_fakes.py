# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Role-composition store and route fixtures shared by the composition tests."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.config.schema import Config
from src.profiles.store import ProfileStore
from src.server.state import state
from tests.access_helpers import access_client, same_origin
from tests.llm_fakes import FakeLlm


def _config():
    config = Config()
    config.model.type = "musetalk"
    config.model.avatar_id = "musetalk_angela"
    return config


@pytest.fixture
def store(tmp_path, monkeypatch):
    """main + weather (seeded) and seven more profiles compatible with main."""
    monkeypatch.setattr("src.profiles.store.avatar_settings", lambda _: {"enabled": False, "dataset_ids": []})
    store = ProfileStore(tmp_path / "avatar_profiles.yaml")
    library = store.initialize(_config())
    extra = []
    for number in range(1, 8):
        profile = deepcopy(library["profiles"][1])
        profile.update(id=f"s{number}", name=f"專門{number}")
        extra.append(profile)
    store.save_profiles(library["profiles"] + extra, expected_revision=library["profiles_revision"])
    return store


@pytest.fixture
def composition_routes(store, monkeypatch):
    monkeypatch.setattr(state, "config", _config())
    monkeypatch.setattr(state, "llm", FakeLlm(), raising=False)
    library = store.load()

    async def close():
        return None

    roles = SimpleNamespace(store=store, enabled=False, library=library, snapshot=lambda: {"phase": "disabled"},
                            media=SimpleNamespace(list=lambda: []), close=close,
                            profiles={p["id"]: p for p in library["profiles"]}, current_id="main")
    monkeypatch.setattr(state, "roles", roles, raising=False)
    return store


def _request(method, path, body=None):
    async def run():
        async with access_client() as client:
            response = await client.request(method, path, json=body, headers=same_origin(client))
            return response.status, await response.json()
    return asyncio.run(run())
