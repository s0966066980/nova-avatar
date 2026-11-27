# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""當次角色組合: version 1 migration, validation and per-member saves (ADR 0023)."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml

from nova_core.profiles.composition import (
    MAX_ENABLED_MEMBERS, compatibility_report, live_members, profile_ids, referenced_media, transition,
)
from nova_core.profiles.coordinator import ConversationRoles
from nova_core.profiles.store import ProfileError, ProfileStore, validate_profile
from composition_fakes import _config, _request, composition_routes, store  # noqa: F401

_RULES = """\
  reply_rules:
    revision: 4
    activation: '依本輪問題與已提交的對話上下文，選擇簡答或看板回覆。'
    speech: '簡答直接回答問題，語氣自然、清楚。'
    board: '使用容易閱讀的條列，每項包括簡短標題與具體說明。'
"""
_SHARED = """\
  llm:
    board_max_items: 8
    reply_mode: streaming
    semantic_wait_seconds: 0.5
    model: gemma-4-E2B_q4_0-it
    max_tokens: 788
    response_max_chars: 200
    endpoint: llamacpp
  tts:
    voice_en_us: en-US-JennyNeural
    type: edgetts
    ref_file: zh-TW-HsiaoChenNeural
    ref_text: null
    tts_server: http://127.0.0.1:9880
    model: ''
    edge_persistent_worker: true
    edge_prefetch: true
    edge_connection_reuse: true
"""
# The structure of the venue's config/avatar_profiles.yaml on 2026-10-30
# (version 1, revision 13), with prompts shortened and a placeholder dataset.
LIVE_V1 = f"""\
# Nova Avatar role profiles. Credentials stay in the server environment.
version: 1
revision: 13
enabled: true
profiles:
- id: main
  name: Nova Avatar
  engine: musetalk
  avatar_id: musetalk_angela
  assistant_profile:
    assistant_name: Nova Avatar
    system_prompt: '你的特點：親切、清楚。'
    restriction_prompt: '不隨意提供個人資訊。'
    output_locale: zh-TW
    enforce_output_locale: true
    forbidden_self_names: []
{_SHARED}  rag:
    enabled: true
    dataset_ids:
    - {"a" * 32}
    document_scope: all
    document_ids: []
{_RULES}  tools:
    weather: false
  greeting:
    mode: ai
    scripts: []
    scripts_en: []
    prompt: 用親切的繁體中文介紹你能提供什麼服務，再邀請訪客提問
    min_chars: 20
    max_chars: 100
- id: weather
  name: 天氣助手
  engine: musetalk
  avatar_id: musetalk_1
  assistant_profile:
    assistant_name: 天氣助手
    system_prompt: 你負責解說臺灣天氣。
    restriction_prompt: 未取得氣象資料時明說暫時查不到最新資料。
    output_locale: zh-TW
    enforce_output_locale: true
    forbidden_self_names: []
{_SHARED}  rag:
    enabled: false
    dataset_ids: []
    document_scope: all
    document_ids: []
{_RULES}  tools:
    weather: true
  greeting:
    mode: scripts
    scripts: []
    scripts_en: []
    prompt: ''
    min_chars: 20
    max_chars: 60
pair:
  main: main
  specialist: weather
transitions:
- source: main
  target: weather
  kind: effect
  effect: fade
  duration: 0.6
  asset_id: ''
handoff:
  description: 回答臺灣各縣市鄉鎮的目前天氣、溫度與未來預報。
  rules: 當訪客詢問具體天氣、氣溫、下雨機率或天氣預報時，交給專門角色。混合主題先詢問優先主題，語意不清楚時先釐清。
  announcement: 接下來請天氣助手為您說明。
  announcement_en: ''
  return_announcement: 接下來請主數位人接續回答您的問題。
  return_announcement_en: Our main avatar will help with your question next.
weather:
  county: ''
  town: ''
migrated: true
"""


def test_live_v1_library_becomes_a_composition_once_with_a_backup(tmp_path):
    path = tmp_path / "avatar_profiles.yaml"
    path.write_text(LIVE_V1, encoding="utf-8")
    old = yaml.safe_load(LIVE_V1)
    store = ProfileStore(path)

    library = store.initialize(_config())

    backups = list(tmp_path.glob("avatar_profiles.yaml.v1-*.bak"))
    assert len(backups) == 1 and backups[0].read_text("utf-8") == LIVE_V1
    stored = yaml.safe_load(path.read_text("utf-8"))
    assert set(stored) == {"version", "revision", "profiles_revision", "profiles", "composition"}
    assert (stored["version"], stored["revision"], stored["profiles_revision"]) == (2, 14, 14)
    # Profiles are kept as they were, except tools now belong to members.
    assert stored["profiles"] == [{k: v for k, v in p.items() if k != "tools"} for p in old["profiles"]]
    assert stored["composition"] == {
        "revision": 1, "enabled": True,
        "main": {"profile_id": "main", "revision": 1, "description": "", "rules": "",
                 "announcement": "接下來請主數位人接續回答您的問題。",
                 "announcement_en": "Our main avatar will help with your question next."},
        "members": [{"profile_id": "weather", "revision": 1, "enabled": True,
                     "description": old["handoff"]["description"], "rules": old["handoff"]["rules"],
                     "announcement": "接下來請天氣助手為您說明。", "announcement_en": "",
                     "tools": {"weather": {"enabled": True, "county": "", "town": ""}}}],
        "transitions": {"revision": 1,
                        "default": {"kind": "effect", "effect": "fade", "duration": 0.6, "asset_id": ""},
                        "overrides": old["transitions"]}}
    # Reads return the stored shape only: no two-role keys, no profile tools.
    assert set(library) == {"version", "revision", "profiles_revision", "profiles", "composition"}
    assert all("tools" not in p for p in library["profiles"])

    before = path.read_bytes()
    assert store.initialize(_config()) == library
    assert path.read_bytes() == before
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_loading_a_version_1_file_converts_without_writing(tmp_path):
    path = tmp_path / "avatar_profiles.yaml"
    path.write_text(LIVE_V1, encoding="utf-8")
    library = ProfileStore(path).load()
    assert library["composition"]["main"]["profile_id"] == "main"
    assert path.read_text("utf-8") == LIVE_V1
    assert not list(tmp_path.glob("*.bak"))


def _member(store, pid):
    return next(m for m in store.load()["composition"]["members"] if m["profile_id"] == pid)


def _add(store, pid, **fields):
    composition = store.load()["composition"]
    return store.add_member({"profile_id": pid, "announcement": f"接下來請{pid}回答。", **fields},
                            expected_revision=composition["revision"])


def test_seeded_library_is_a_one_member_composition(store):
    composition = store.load()["composition"]
    assert composition["main"]["profile_id"] == "main"
    assert [m["profile_id"] for m in composition["members"]] == ["weather"]
    assert composition["members"][0]["tools"]["weather"]["enabled"] is True
    assert composition["enabled"] is False


def test_at_most_five_specialists_are_enabled_but_more_may_wait_disabled(store):
    for number in range(1, MAX_ENABLED_MEMBERS):
        _add(store, f"s{number}", enabled=True)
    before = store.path.read_bytes()
    with pytest.raises(ProfileError, match="最多同時啟用 5 位") as error:
        _add(store, "s5", enabled=True)
    assert error.value.status == 409 and error.value.extra["field"] == "enabled"
    assert store.path.read_bytes() == before
    library = _add(store, "s5")
    assert sum(m["enabled"] for m in library["composition"]["members"]) == MAX_ENABLED_MEMBERS
    assert len(library["composition"]["members"]) == MAX_ENABLED_MEMBERS + 1


@pytest.mark.parametrize("fields,message,status", [
    ({"profile_id": "weather"}, "已在角色組合中", 409),
    ({"profile_id": "main"}, "是主數位人", 409),
    ({"profile_id": "missing"}, "不存在", 409),
    ({"profile_id": "s1", "tools": {"weather": {"enabled": True}}}, "天氣工具同時只限一位", 409),
    ({"profile_id": "s1", "announcement": "  "}, "交接說明", 400),
    ({"profile_id": "s1", "surprise": 1}, "未知欄位", 400),
])
def test_invalid_members_leave_the_saved_composition_untouched(store, fields, message, status):
    before = store.path.read_bytes()
    with pytest.raises(ProfileError, match=message) as error:
        store.add_member({"announcement": "請稍候。", **fields},
                         expected_revision=store.load()["composition"]["revision"])
    assert error.value.status == status
    assert store.path.read_bytes() == before


def test_saving_one_member_checks_and_bumps_only_its_own_revision(store):
    _add(store, "s1", enabled=True)
    _add(store, "s2", enabled=True)
    console_a = store.load()["composition"]
    s1, s2 = (deepcopy(next(m for m in console_a["members"] if m["profile_id"] == pid)) for pid in ("s1", "s2"))

    # Console B edits s1 first.
    store.save_member("s1", {"rules": "主控台 B 的規則"}, expected_revision=s1["revision"])
    # Console A's s2 save is unaffected by B's s1 save.
    saved = store.save_member("s2", {"description": "主控台 A 的介紹"}, expected_revision=s2["revision"])
    composition = saved["composition"]
    assert composition["revision"] == console_a["revision"]
    assert composition["main"]["revision"] == console_a["main"]["revision"]
    assert composition["transitions"]["revision"] == console_a["transitions"]["revision"]
    assert _member(store, "s1")["revision"] == s1["revision"] + 1
    assert _member(store, "s2")["revision"] == s2["revision"] + 1
    assert _member(store, "weather")["revision"] == 1

    # Console A's stale s1 draft is refused with the saved member to merge against.
    before = store.path.read_bytes()
    with pytest.raises(ProfileError, match="其他控制台") as error:
        store.save_member("s1", {"rules": "主控台 A 的規則"}, expected_revision=s1["revision"])
    assert error.value.status == 409
    conflict = error.value.extra["conflict"]
    assert (conflict["scope"], conflict["profile_id"], conflict["revision"]) == ("member", "s1", s1["revision"] + 1)
    assert conflict["current"]["rules"] == "主控台 B 的規則"
    assert store.path.read_bytes() == before


def test_enabling_a_member_also_checks_the_composition_revision(store):
    _add(store, "s1")
    composition = store.load()["composition"]
    member = _member(store, "s1")
    _add(store, "s2")  # another console changes the roster
    with pytest.raises(ProfileError) as error:
        store.save_member("s1", {"enabled": True}, expected_revision=member["revision"],
                          expected_composition_revision=composition["revision"])
    assert error.value.extra["conflict"]["scope"] == "composition"
    # Text-only saves never need the composition revision.
    store.save_member("s1", {"description": "介紹"}, expected_revision=member["revision"])
    current = store.load()["composition"]
    saved = store.save_member("s1", {"enabled": True}, expected_revision=member["revision"] + 1,
                              expected_composition_revision=current["revision"])
    assert saved["composition"]["revision"] == current["revision"] + 1
    assert [m["profile_id"] for m in live_members(saved)] == []  # handoff is still switched off
    saved, disabled = store.update_composition(expected_revision=saved["composition"]["revision"], enabled=True)
    assert disabled == []
    assert [m["profile_id"] for m in live_members(saved)] == ["weather", "s1"]


def test_an_incompatible_member_cannot_be_enabled_but_keeps_its_settings(store):
    library = store.load()
    profiles = deepcopy(library["profiles"])
    for profile in profiles:
        if profile["id"] in {"s1", "s2"}:
            profile["llm"]["model"] = "another-local-model"
    library = store.save_profiles(profiles, expected_revision=library["profiles_revision"])
    assert compatibility_report(library)["s1"] == ["即時組合必須共用同一 LLM 服務及模型"]
    assert compatibility_report(library)["s3"] == []
    library = _add(store, "s1", description="保留的介紹")
    member = _member(store, "s1")
    with pytest.raises(ProfileError, match="不相容") as error:
        store.save_member("s1", {"enabled": True}, expected_revision=member["revision"],
                          expected_composition_revision=library["composition"]["revision"])
    assert error.value.status == 409 and error.value.extra["reasons"]
    with pytest.raises(ProfileError, match="不相容"):
        _add(store, "s2", enabled=True)
    # Disabled, it can still be edited and saved.
    store.save_member("s1", {"rules": "改過的規則"}, expected_revision=member["revision"])
    assert _member(store, "s1")["description"] == "保留的介紹"


def test_changing_the_main_avatar_disables_incompatible_members_only_when_confirmed(store):
    _add(store, "s1", enabled=True)
    _add(store, "s2", enabled=True)
    library = store.load()
    profiles = deepcopy(library["profiles"])
    for profile in profiles:
        if profile["id"] in {"s3", "s1"}:
            profile["llm"]["model"] = "another-local-model"
    library = store.save_profiles(profiles, expected_revision=library["profiles_revision"])
    revision = library["composition"]["revision"]
    with pytest.raises(ProfileError, match="不相容") as error:
        store.update_composition(expected_revision=revision, main="s3")
    assert error.value.extra["disable_required"] == ["weather", "s2"]
    saved, disabled = store.update_composition(expected_revision=revision, main="s3", confirm_disable=True)
    assert disabled == ["weather", "s2"]
    composition = saved["composition"]
    assert composition["main"]["profile_id"] == "s3"
    assert {m["profile_id"]: m["enabled"] for m in composition["members"]} == {"weather": False, "s1": True, "s2": False}
    assert composition["revision"] == revision + 1
    with pytest.raises(ProfileError, match="目前是專門數位人"):
        store.update_composition(expected_revision=composition["revision"], main="s1")


def test_main_avatar_has_the_same_handoff_fields_and_its_own_revision(store):
    library = store.load()
    main = library["composition"]["main"]
    saved = store.save_main({"description": "一般接待", "rules": "其他角色都不負責時交給我",
                             "announcement": "這題我請接待員回答。", "announcement_en": "Our host will help."},
                            expected_revision=main["revision"])
    assert saved["composition"]["main"]["revision"] == main["revision"] + 1
    assert saved["composition"]["revision"] == library["composition"]["revision"]
    assert saved["composition"]["main"]["announcement"] == "這題我請接待員回答。"
    assert saved["composition"]["members"] == library["composition"]["members"]
    with pytest.raises(ProfileError) as error:
        store.save_main({"announcement": "過期"}, expected_revision=main["revision"])
    assert error.value.extra["conflict"]["scope"] == "main"


def test_removing_a_member_keeps_its_profile_and_transition_overrides(store):
    _add(store, "s1")
    transitions = store.load()["composition"]["transitions"]
    store.save_transitions({"default": {"kind": "effect", "effect": "zoom", "duration": 0.8},
                            "overrides": [{"source": "s1", "target": "weather", "effect": "slide_left"}]},
                           expected_revision=transitions["revision"])
    library = store.remove_member("s1", expected_revision=store.load()["composition"]["revision"])
    assert "s1" in {p["id"] for p in library["profiles"]}
    assert [m["profile_id"] for m in library["composition"]["members"]] == ["weather"]
    assert library["composition"]["transitions"]["overrides"][0]["source"] == "s1"
    with pytest.raises(ProfileError, match="已不在角色組合中"):
        store.remove_member("s1", expected_revision=library["composition"]["revision"])


def test_profile_list_saves_protect_members_and_drop_orphaned_overrides(store):
    _add(store, "s1")
    store.save_transitions({"overrides": [{"source": "s2", "target": "weather"}]},
                           expected_revision=store.load()["composition"]["transitions"]["revision"])
    library = store.load()
    with pytest.raises(ProfileError, match="在當次角色組合中"):
        store.save_profiles([p for p in library["profiles"] if p["id"] != "s1"],
                            expected_revision=library["profiles_revision"])
    member = _member(store, "s1")
    store.save_member("s1", {"rules": "不影響設定檔清單"}, expected_revision=member["revision"])
    saved = store.save_profiles([p for p in library["profiles"] if p["id"] != "s2"],
                                expected_revision=library["profiles_revision"])
    assert saved["composition"]["transitions"]["overrides"] == []
    assert saved["composition"]["transitions"]["revision"] == library["composition"]["transitions"]["revision"] + 1
    with pytest.raises(ProfileError, match="其他控制台"):
        store.save_profiles(saved["profiles"], expected_revision=library["profiles_revision"])


def test_transitions_fall_back_to_the_saved_default_in_the_runtime(store):
    transitions = store.load()["composition"]["transitions"]
    library = store.save_transitions(
        {"default": {"kind": "effect", "effect": "slide_right", "duration": 1.2},
         "overrides": [{"source": "main", "target": "weather", "kind": "effect", "effect": "zoom"}]},
        expected_revision=transitions["revision"])
    assert transition(library, "weather", "main")["effect"] == "slide_right"
    roles = SimpleNamespace(library=library)
    assert ConversationRoles.edge(roles, "weather", "main")["effect"] == "slide_right"
    assert ConversationRoles.edge(roles, "main", "weather")["effect"] == "zoom"


def test_profiles_and_stored_libraries_no_longer_carry_tools_or_two_role_keys(store):
    library = store.load()
    profile = deepcopy(library["profiles"][1])
    profile["tools"] = {"weather": True}
    with pytest.raises(ProfileError, match="角色組合與交接") as error:
        validate_profile(profile)
    assert error.value.extra["field"] == "tools"
    before = store.path.read_bytes()
    with pytest.raises(ProfileError):
        store.save_profiles([*library["profiles"][:1], profile], expected_revision=library["profiles_revision"])
    assert store.path.read_bytes() == before
    # A version 2 file is read as stored: two-role keys are refused, not dropped.
    for extra in ({"pair": {"main": "main", "specialist": "weather"}}, {"transitions": []}, {"enabled": True}):
        store.path.write_text(yaml.safe_dump({**yaml.safe_load(before), **extra}, allow_unicode=True), "utf-8")
        with pytest.raises(ProfileError, match="未知欄位"):
            store.load()
    store.path.write_bytes(before)


def test_only_the_saved_default_and_overrides_reference_transition_clips(store):
    transitions = store.load()["composition"]["transitions"]
    library = store.save_transitions(
        {"default": {"kind": "video", "asset_id": "clip_default"},
         "overrides": [{"source": "main", "target": "weather", "kind": "video", "asset_id": "clip_edge"}]},
        expected_revision=transitions["revision"])
    assert referenced_media(library) == {"clip_default", "clip_edge"}
    assert referenced_media({**library, "transitions": [{"kind": "video", "asset_id": "stale"}]}) == {
        "clip_default", "clip_edge"}


def test_member_routes_report_conflicts_with_the_saved_member(composition_routes):
    store = composition_routes
    status, body = _request("GET", "/api/profiles")
    assert status == 200
    assert body["library"]["composition"]["members"][0]["profile_id"] == "weather"
    assert body["compatibility"]["s1"] == []
    revision = body["library"]["composition"]["revision"]
    status, body = _request("POST", "/api/profiles/composition/members",
                            {"expected_revision": revision, "member": {"profile_id": "s1", "announcement": "請稍候。"}})
    assert status == 200, body
    status, body = _request("PUT", "/api/profiles/composition/members/s1",
                            {"expected_revision": 1, "member": {"rules": "新規則"}})
    assert status == 200 and _member(store, "s1")["rules"] == "新規則"
    status, body = _request("PUT", "/api/profiles/composition/members/s1",
                            {"expected_revision": 1, "member": {"rules": "過期規則"}})
    assert status == 409
    assert body["code"] == -1 and "其他控制台" in body["msg"]
    assert body["conflict"]["scope"] == "member" and body["conflict"]["current"]["rules"] == "新規則"
    status, body = _request("PUT", "/api/profiles/composition/members/s1",
                            {"expected_revision": 2, "member": {"announcement": ""}})
    assert (status, body["field"]) == (400, "announcement")
    status, body = _request("DELETE", "/api/profiles/composition/members/s1",
                            {"expected_revision": store.load()["composition"]["revision"]})
    assert status == 200 and [m["profile_id"] for m in body["library"]["composition"]["members"]] == ["weather"]


def test_whole_library_saves_are_refused_and_profile_lists_save_over_http(composition_routes):
    store = composition_routes
    library = store.load()
    before = store.path.read_bytes()
    status, body = _request("PUT", "/api/profiles", {"library": library, "expected_revision": library["revision"]})
    assert (status, body["code"]) == (400, -1)
    assert store.path.read_bytes() == before
    profiles = deepcopy(library["profiles"])
    profiles[0]["name"] = "新的接待員"
    status, body = _request("PUT", "/api/profiles",
                            {"profiles": profiles, "expected_profiles_revision": library["profiles_revision"]})
    assert status == 200, body
    assert body["library"]["profiles"][0]["name"] == "新的接待員"
    assert body["library"]["composition"] == library["composition"]
    assert "pair" not in body["library"] and body["compatibility"]["s1"] == []
    status, body = _request("PUT", "/api/profiles",
                            {"profiles": profiles, "expected_profiles_revision": library["profiles_revision"]})
    assert status == 409 and body["conflict"]["scope"] == "profiles"


def test_a_composition_without_members_has_only_the_main_avatar(store):
    library = store.remove_member("weather", expected_revision=store.load()["composition"]["revision"])
    library["composition"]["enabled"] = True
    assert library["composition"]["members"] == []
    assert live_members(library) == []
    assert profile_ids(library) == {"main"}
