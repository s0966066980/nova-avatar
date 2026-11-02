# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

from copy import deepcopy
import json

import pytest

from src.config.schema import Config
from src.profiles.composition import MAIN_ANNOUNCEMENTS, incompatibility, live_members
from src.profiles.store import ProfileError, ProfileStore, profile_config
from src.llm import service as llm_service
from types import SimpleNamespace


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setattr("src.profiles.store.avatar_settings",
                        lambda _: {"enabled": True, "dataset_ids": ["a" * 32]})
    config = Config()
    config.model.avatar_id = "musetalk_angela"
    config.llm.assistant_profile.assistant_name = "現有身分"
    config.llm.assistant_profile.system_prompt = "現有接待規則"
    config.llm.api_key = "server-only-test-credential"
    store = ProfileStore(tmp_path / "profiles.yaml")
    return store, config, store.initialize(config)


def _save_profiles(store, data):
    return store.save_profiles(data["profiles"], expected_revision=data["profiles_revision"])


def test_migration_is_once_only_and_excludes_credentials(profiles):
    store, config, data = profiles
    assert data["profiles"][0]["assistant_profile"]["system_prompt"] == "現有接待規則"
    assert data["profiles"][0]["rag"]["dataset_ids"] == ["a" * 32]
    assert data["profiles"][1]["rag"]["dataset_ids"] == []
    config.llm.assistant_profile.assistant_name = "後來的全域名稱"
    assert store.initialize(config) == data
    assert config.llm.api_key not in store.path.read_text()
    assert "api_key" not in json.dumps(data)


def test_old_libraries_gain_a_main_announcement_once_without_overwriting_content(profiles):
    import yaml
    store, config, data = profiles
    # A version 1 file saved before return announcements existed.
    weather = data["composition"]["members"][0]
    old = {"version": 1, "revision": data["revision"], "enabled": False,
           "profiles": [dict(p, tools={"weather": p["id"] == "weather"}) for p in data["profiles"]],
           "pair": {"main": "main", "specialist": "weather"}, "transitions": [],
           "handoff": {key: weather[key] for key in ("description", "rules", "announcement", "announcement_en")},
           "weather": {"county": "", "town": ""}}
    store.path.write_text(yaml.safe_dump(old, allow_unicode=True), encoding='utf8')
    migrated = store.initialize(config)
    main = migrated['composition']['main']
    assert (main['announcement'], main['announcement_en']) == (
        MAIN_ANNOUNCEMENTS['announcement'], MAIN_ANNOUNCEMENTS['announcement_en'])
    assert migrated['composition']['members'][0]['announcement'] == old['handoff']['announcement']
    assert migrated['revision'] == old['revision'] + 1
    assert store.initialize(config) == migrated
    saved = store.save_main({'announcement': '專用返回說明', 'announcement_en': 'Custom return message.'},
                            expected_revision=main['revision'])
    assert store.initialize(config) == saved
    assert saved['composition']['main']['announcement'] == '專用返回說明'


@pytest.mark.parametrize('value', [42, 'x' * 2001])
def test_invalid_main_announcements_do_not_replace_saved_settings(profiles, value):
    store, _, data = profiles
    before = store.path.read_bytes()
    with pytest.raises(ProfileError):
        store.save_main({'announcement_en': value}, expected_revision=data['composition']['main']['revision'])
    assert store.path.read_bytes() == before


def test_role_identity_is_independent_of_reused_visual_material(profiles):
    store, config, data = profiles
    data["profiles"][1]["avatar_id"] = data["profiles"][0]["avatar_id"]
    saved = _save_profiles(store, data)
    a, b = (profile_config(config, p) for p in saved["profiles"])
    assert a.model.avatar_id == b.model.avatar_id
    assert a.profile_id != b.profile_id
    assert a.llm.assistant_profile.assistant_name != b.llm.assistant_profile.assistant_name
    assert a.profile_rag != b.profile_rag
    assert a.llm.api_key == config.llm.api_key
    a.profile_rag["dataset_ids"].clear()
    assert store.load()["profiles"][0]["rag"]["dataset_ids"] == ["a" * 32]


def test_stale_editor_cannot_overwrite_a_saved_revision(profiles):
    store, _, data = profiles
    stale = deepcopy(data)
    data["profiles"][0]["name"] = "已更新"
    assert _save_profiles(store, data)["profiles_revision"] == 2
    with pytest.raises(ProfileError, match="其他控制台"):
        _save_profiles(store, stale)
    assert store.load()["profiles"][0]["name"] == "已更新"


def test_site_location_normalizes_common_tai_spelling(profiles):
    store, _, data = profiles
    weather = data['composition']['members'][0]
    saved = store.save_member('weather', {'tools': {'weather': {'enabled': True, 'county': '台東縣', 'town': '台東市'}}},
                              expected_revision=weather['revision'])
    assert saved['composition']['members'][0]['tools']['weather'] == {
        'enabled': True, 'county': '臺東縣', 'town': '臺東市'}


@pytest.mark.parametrize("change", [
    lambda d: d["profiles"][0]["llm"].update(api_key="should-not-save"),
    lambda d: d["profiles"][0]["llm"].update(base_url="https://user:password@localhost/v1"),
    lambda d: d["profiles"][0]["rag"].update(enabled=True, dataset_ids=[]),
    lambda d: d["profiles"][0].update(id="../outside"),
    lambda d: d["profiles"][1].update(tools={"weather": True}),
])
def test_invalid_save_does_not_damage_current_settings(profiles, change):
    store, _, data = profiles
    before = store.path.read_bytes()
    change(data)
    with pytest.raises(ProfileError):
        _save_profiles(store, data)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("edge", [
    {"source": "main", "target": "main", "kind": "effect"},
    {"source": "main", "target": "weather", "kind": "video"},
])
def test_invalid_transition_does_not_damage_current_settings(profiles, edge):
    store, _, data = profiles
    before = store.path.read_bytes()
    with pytest.raises(ProfileError):
        store.save_transitions({"overrides": [edge]},
                               expected_revision=data["composition"]["transitions"]["revision"])
    assert store.path.read_bytes() == before


def test_different_model_can_be_saved_but_not_activated_as_live_member(profiles):
    store, config, data = profiles
    data["profiles"][1]["llm"]["model"] = "another-local-model"
    saved = _save_profiles(store, data)
    assert saved["profiles"][1]["llm"]["model"] == "another-local-model"
    assert "即時組合必須共用同一 LLM 服務及模型" in incompatibility(*saved["profiles"][:2])
    saved["composition"]["enabled"] = True
    assert saved["composition"]["members"][0]["enabled"]
    assert live_members(saved) == []


@pytest.mark.parametrize("field,value", [("model", "tts/BreezyVoice-other"),
                                         ("tts_server", "http://127.0.0.1:50001")])
def test_live_pair_shares_one_breezyvoice_model_and_server(profiles, field, value):
    _, config, data = profiles
    config.tts.type = "breezyvoice"
    for index, profile in enumerate(data["profiles"]):
        # Each role may clone its own recording; the server and model are shared.
        profile["tts"].update(type="breezyvoice", ref_file=f"{index:016x}", model="", tts_server="")
    data["profiles"][1]["tts"]["tts_server"] = "http://127.0.0.1:50000"  # the default, spelled out
    assert incompatibility(*data["profiles"][:2]) == []
    data["profiles"][1]["tts"][field] = value
    assert any("同一個 BreezyVoice 模型與服務網址" in reason for reason in incompatibility(*data["profiles"][:2]))


def test_return_resumes_only_that_roles_played_history_and_reset_clears_both(profiles, monkeypatch):
    _, config, data = profiles
    monkeypatch.setattr(llm_service, "_session_llm_instances", {})
    monkeypatch.setattr(llm_service, "_active_profiles", {})
    avatar = SimpleNamespace(sessionid=123, config=profile_config(config, data["profiles"][0]))
    llm_service.prepare_spoken_history("原問題", avatar, "source-turn")
    assert llm_service.session_history(123) == []
    llm_service.commit_session_history(123, "source-turn",
                                       assistant_text="已播交接說明", terminal_reason="completed")
    avatar.config = profile_config(config, data["profiles"][1])
    llm_service.prepare_spoken_history("原問題", avatar, "weather-turn")
    llm_service.commit_session_history(123, "weather-turn",
                                       assistant_text="已播天氣答案", terminal_reason="interrupt")
    llm_service.select_session_profile(123, "main")
    assert llm_service.session_history(123)[-1]["content"] == "已播交接說明"
    assert llm_service.session_history(123, "weather")[-1]["content"] == "已播天氣答案"
    llm_service.clear_session_history(123, "main")
    assert llm_service.session_history(123, "main") == []
    assert llm_service.session_history(123, "weather")
    llm_service.clear_session_history(123)
    assert llm_service.session_history(123, "weather") == []
    llm_service.remove_session(123)
    assert not llm_service._session_llm_instances


def test_document_scope_and_model_rules_are_per_profile_snapshots(profiles):
    store, config, data = profiles
    main, specialist = data['profiles']
    specialist['avatar_id'] = main['avatar_id']
    main['rag'].update(document_scope='selected', document_ids=['c' * 32])
    main['llm'].update(board_max_items=3, reply_mode='streaming', semantic_wait_seconds=2.5)
    saved = _save_profiles(store, data)
    a, b = [profile_config(config, p) for p in saved['profiles']]
    assert a.profile_rag['document_ids'] == ['c' * 32]
    assert b.profile_rag['document_scope'] == 'all'
    assert b.profile_rag['document_ids'] == []
    assert a.llm.board.max_items == 3
    assert a.reply_streaming.enabled
    assert a.reply_streaming.semantic_wait_seconds == 2.5
    assert config.llm.board.max_items != 3
    a.profile_rag['document_ids'].clear()
    assert store.load()['profiles'][0]['rag']['document_ids'] == ['c' * 32]


@pytest.mark.parametrize('change', [
    {'document_scope': 'selected', 'document_ids': []},
    {'document_scope': 'selected', 'document_ids': ['invalid']},
    {'document_scope': 'selected', 'document_ids': ['c' * 32] * 2},
    {'document_scope': {'invalid': True}},
    {'document_scope': 'unknown'},
])
def test_bad_document_scope_does_not_replace_saved_library(profiles, change):
    store, _, data = profiles
    before = store.path.read_bytes()
    data['profiles'][0]['rag'].update(change)
    with pytest.raises(ProfileError):
        _save_profiles(store, data)
    assert store.path.read_bytes() == before


def test_existing_profiles_migrate_effective_shared_playback_choices_once(profiles):
    import yaml
    store, config, data = profiles
    for profile in data['profiles']:
        for key in ['board_max_items', 'reply_mode', 'semantic_wait_seconds']:
            profile['llm'].pop(key)
    store.path.write_text(yaml.safe_dump(data), encoding='utf8')
    config.llm.board.max_items = 4
    config.reply_streaming.enabled = True
    config.reply_streaming.semantic_wait_seconds = 3
    migrated = store.initialize(config)
    assert migrated['revision'] == 2
    assert all(p['llm']['reply_mode'] == 'streaming' for p in migrated['profiles'])
    assert all(p['llm']['board_max_items'] == 4 for p in migrated['profiles'])
    config.reply_streaming.enabled = False
    assert store.initialize(config) == migrated
