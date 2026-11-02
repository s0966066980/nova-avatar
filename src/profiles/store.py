# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Atomic, non-secret role profiles; rendering and conversations are runtime state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields
import os
from pathlib import Path
import shutil
import tempfile
from threading import RLock
import time
from urllib.parse import urlsplit

import yaml

from src.config.schema import AssistantProfileConfig, ReplyRulesConfig, TTSConfig, GreetingConfig
from src.greetings.content import validate_content
from src.llm.endpoints import (EndpointError, active_endpoint_name, apply_endpoint,
                               configured_endpoints, endpoint_for_url)
from src.llm.rules import rules_from_config, validate_rules
from src.profiles.composition import (
    HANDOFF_FIELDS, MAIN_ANNOUNCEMENTS, apply_legacy_view, bump_revisions, canonical, incompatibility,
    legacy_pair_view, new_member, profile_ids, validate_composition,
)
from src.profiles.validation import ProfileError
from src.profiles.validation import identifier as _identifier, obj as _object, revision as _revision, text as _text
from src.ragflow.settings import avatar_settings
from src.ragflow.selection import validate_selection
from src.tts.voice_library import (
    REFERENCE_AUDIO_ENGINES, TTS_ENGINES, VoiceLibraryError, check_model, check_reference, check_tts_server,
    drop_stale_transcript, migrate_tts_values, voice_transcript,
)
from src.utils.logging import logger

__all__ = ["RETURN_ANNOUNCEMENTS", "ProfileError", "ProfileStore", "compatible_pair", "profile_config",
           "validate_library", "validate_profile"]

LLM_FIELDS = ("endpoint", "model", "max_tokens", "response_max_chars")
# Profiles saved before the endpoint allowlist stored a URL instead of a name.
LEGACY_LLM_FIELDS = ("provider", "base_url")
LLM_PLAYBACK_DEFAULTS = {"board_max_items": 8, "reply_mode": "legacy", "semantic_wait_seconds": 0.5}
_MEMBER_INPUT = {"profile_id", "revision", "enabled", "tools", *HANDOFF_FIELDS}


def _playback_settings(config):
    return dict(board_max_items=config.llm.board.max_items,
                reply_mode="streaming" if config.reply_streaming.enabled else "legacy",
                semantic_wait_seconds=config.reply_streaming.semantic_wait_seconds)


# Temporary two-role adapter: the runtime's fallback return announcements.
RETURN_ANNOUNCEMENTS = {
    "return_announcement": MAIN_ANNOUNCEMENTS["announcement"],
    "return_announcement_en": MAIN_ANNOUNCEMENTS["announcement_en"],
}


def _expect(expected, actual, scope, message, *, current=None, profile_id=None):
    """Refuse a save whose ``expected`` revision is not the stored one."""
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ProfileError("請附上修訂版本", 400, field="expected_revision")
    if expected != actual:
        conflict = {"scope": scope, "revision": actual}
        if profile_id is not None:
            conflict["profile_id"] = profile_id
        if current is not None:
            conflict["current"] = deepcopy(current)
        raise ProfileError(message, 409, conflict=conflict)


def _endpoint(value):
    value = _text(value, "模型服務網址", 500)
    parsed = urlsplit(value)
    if value and (parsed.scheme not in {"http", "https"} or not parsed.hostname
                  or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ProfileError("模型服務網址不可包含帳密、查詢參數或片段")
    return value


def _llm_endpoint(llm: dict, endpoints) -> str:
    """Return the endpoint name, mapping a legacy URL to the listed endpoint."""
    if "endpoint" in llm:
        if set(LEGACY_LLM_FIELDS) & set(llm):
            raise ProfileError("回答模型只能指定 LLM 端點名稱，不可另填服務或網址")
        name = llm["endpoint"]
        if not isinstance(name, str) or len(name) > 80:
            raise ProfileError("LLM 端點名稱不正確")
        return name
    legacy = llm.get("base_url", "")
    name = endpoint_for_url(endpoints or {}, legacy)
    if not name:
        logger.warning("數位人設定檔的模型服務網址 %s 不在 llm.endpoints 中，需改選端點", legacy)
    return name


def profile_config(base, profile: dict):
    """Keep server credentials and engine options private; apply a role snapshot."""
    result = deepcopy(base)
    result.profile_id = profile["id"]
    result.model.type = profile["engine"]
    result.model.avatar_id = profile["avatar_id"]
    try:
        # URL, provider and key come only from the configured allowlist.
        apply_endpoint(result.llm, profile["llm"].get("endpoint", ""))
    except EndpointError as exc:
        raise ProfileError(f"角色「{profile.get('name', profile['id'])}」未選擇設定檔中的 LLM 端點，"
                           "請在 AI 模型設定改選端點，或於設定檔 llm.endpoints 新增後再套用", 409) from exc
    llm = profile["llm"]
    for key in ("model", "max_tokens", "response_max_chars"):
        if key in llm:
            setattr(result.llm, key, llm[key])
    if "board_max_items" in llm:
        result.llm.board.max_items = llm["board_max_items"]
    if "reply_mode" in llm:
        result.reply_streaming.enabled = llm["reply_mode"] == "streaming"
    if "semantic_wait_seconds" in llm:
        result.reply_streaming.semantic_wait_seconds = llm["semantic_wait_seconds"]
    result.llm.assistant_profile = AssistantProfileConfig(**profile["assistant_profile"])
    result.llm.reply_rules = ReplyRulesConfig(**profile["reply_rules"])
    result.tts = TTSConfig(**profile["tts"])
    result.greeting = GreetingConfig(**validate_content(profile.get("greeting")))
    result.profile_rag = deepcopy(profile["rag"])
    return result


def validate_profile(value: dict, endpoints=None, *, require_endpoint=False, require_voice=False) -> dict:
    """Normalize a profile; ``require_endpoint`` also demands a listed endpoint name and
    ``require_voice`` a transcribed reference recording for BreezyVoice."""
    allowed = {"id", "name", "engine", "avatar_id", "assistant_profile", "llm",
               "tts", "rag", "reply_rules", "tools", "greeting"}
    value = _object(value, allowed, "角色設定檔")
    pid = _identifier(value.get("id"))
    name = _text(value.get("name"), "角色名稱", 80, empty=False)
    engine = _text(value.get("engine"), "人物引擎", 40, empty=False)
    avatar_id = _identifier(value.get("avatar_id"), "人物素材識別碼")
    identity = _object(value.get("assistant_profile"), asdict(AssistantProfileConfig()), "助手身分")
    identity = {**asdict(AssistantProfileConfig()), **identity}
    for key in ("assistant_name", "system_prompt", "restriction_prompt", "output_locale"):
        identity[key] = _text(identity[key], key, 12000)
    if identity["output_locale"] not in {"zh-TW", "zh-CN", "en", "en-US", "auto"}:
        raise ProfileError("輸出語系不正確")
    if not isinstance(identity["enforce_output_locale"], bool):
        raise ProfileError("語系限制必須是布林值")
    names = identity["forbidden_self_names"]
    if not isinstance(names, list) or len(names) > 30:
        raise ProfileError("禁止自稱名稱格式不正確")
    identity["forbidden_self_names"] = [_text(x, "禁止自稱名稱", 80, empty=False) for x in names]
    llm = _object(value.get("llm"), (*LLM_FIELDS, *LEGACY_LLM_FIELDS, *LLM_PLAYBACK_DEFAULTS), "回答模型")
    endpoint = _llm_endpoint(llm, endpoints)
    if require_endpoint and endpoint not in (endpoints or {}):
        raise ProfileError(f"角色「{name}」請選擇設定檔中的 LLM 端點")
    llm = {**LLM_PLAYBACK_DEFAULTS, **{k: v for k, v in llm.items() if k not in LEGACY_LLM_FIELDS},
           "endpoint": endpoint}
    llm["model"] = _text(llm.get("model"), "model", 160, empty=False)
    for key, lower, upper in (("max_tokens", 16, 8192), ("response_max_chars", 20, 2000)):
        number = llm.get(key, 128)
        if isinstance(number, bool) or not isinstance(number, int) or not lower <= number <= upper:
            raise ProfileError(f"{key} 必須介於 {lower}–{upper}")
        llm[key] = number
    if type(llm["board_max_items"]) is not int or not 1 <= llm["board_max_items"] <= 12:
        raise ProfileError("看板項目上限必須介於 1–12")
    if not isinstance(llm["reply_mode"], str) or llm["reply_mode"] not in {"legacy", "streaming"}:
        raise ProfileError("回覆模式不正確")
    wait = llm["semantic_wait_seconds"]
    if type(wait) not in {int, float} or not 0.5 <= wait <= 30:
        raise ProfileError("語意等待上限必須介於 0.5–30 秒")
    tts = _object(value.get("tts"), asdict(TTSConfig()), "聲音")
    tts = {**asdict(TTSConfig()), **tts}
    for item in fields(TTSConfig):
        current = tts[item.name]
        if isinstance(getattr(TTSConfig(), item.name), bool):
            if not isinstance(current, bool):
                raise ProfileError("聲音設定格式不正確")
        elif current is not None:
            tts[item.name] = _text(current, item.name, 4000)
    if tts["type"] not in TTS_ENGINES:
        raise ProfileError(f"聲音設定：不支援的 TTS 引擎「{tts['type'][:40]}」")
    drop_stale_transcript(tts, f"角色設定檔 {pid}")
    try:
        tts["ref_file"] = check_reference(tts["type"], tts["ref_file"])
        tts["tts_server"] = check_tts_server(tts["tts_server"])
        tts["model"] = check_model(tts["model"])
    except VoiceLibraryError as exc:
        raise ProfileError(f"聲音設定：{exc.message}") from None
    if require_voice and tts["type"] in REFERENCE_AUDIO_ENGINES:
        _require_reference(tts, name)
    try:
        rag = validate_selection(value.get("rag"))
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    raw_rules = value.get("reply_rules")
    _object(raw_rules, {"revision", "activation", "speech", "board"}, "回覆規則")
    try:
        rules = validate_rules(raw_rules, revision=raw_rules.get("revision", 1))
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    # Tools belong to composition members now; ``tools`` from the two-role
    # view is accepted and dropped (see composition.apply_legacy_view).
    try:
        greeting = validate_content(value.get("greeting"))
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    return {"id": pid, "name": name, "engine": engine, "avatar_id": avatar_id,
            "assistant_profile": identity, "llm": llm, "tts": tts,
            "rag": rag, "reply_rules": rules, "greeting": greeting}


def _require_reference(tts: dict, name: str) -> None:
    """BreezyVoice clones a library recording and needs what it says; none is chosen for the admin."""
    if not tts["ref_file"]:
        raise ProfileError(f"角色「{name}」使用 BreezyVoice，請在「聲音」選擇有逐字稿的參考音檔")
    if not voice_transcript(tts["ref_file"]):
        raise ProfileError(f"角色「{name}」的參考音檔沒有逐字稿，請改選有逐字稿的參考音檔或重新上傳並填寫逐字稿")


def validate_library(value: dict, endpoints=None, *, require_endpoint=False, require_voice=False) -> dict:
    """Normalize a version 2 library; version 1 and two-role view keys are converted first."""
    value = canonical(value)
    _object(value, {"version", "revision", "profiles_revision", "profiles", "composition"}, "角色設定")
    if value.get("version") != 2:
        raise ProfileError("角色設定版本不正確")
    profiles = value.get("profiles")
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 30:
        raise ProfileError("請保存 1–30 份角色設定檔")
    normalized = [validate_profile(p, endpoints, require_endpoint=require_endpoint, require_voice=require_voice)
                  for p in profiles]
    names = {p["id"]: p["name"] for p in normalized}
    if len(names) != len(normalized):
        raise ProfileError("角色識別碼不可重複")
    return dict(version=2, revision=_revision(value.get("revision")),
                profiles_revision=_revision(value.get("profiles_revision"), "設定檔版本"),
                profiles=normalized, composition=validate_composition(value.get("composition"), names))


def _migrate_voice_settings(raw) -> bool:
    """Saved reference paths move into the voice library or are cleared (see voice_library)."""
    profiles = raw.get("profiles") if isinstance(raw, dict) else None
    changed = False
    for profile in profiles if isinstance(profiles, list) else ():
        tts = profile.get("tts") if isinstance(profile, dict) else None
        if isinstance(tts, dict):
            values = {"type": TTSConfig().type, **tts}
            if migrate_tts_values(values, where=f"角色設定檔 {profile.get('id')}"):
                kept = {key: values[key] for key in tts if key in values}
                tts.clear()
                tts.update(kept)
                changed = True
    return changed


class ProfileStore:
    """The role library file: profiles and the 當次角色組合 (version 2).

    Reads return the stored library plus the temporary two-role view keys
    (``composition.legacy_pair_view``). Every write increases ``revision``;
    each save checks only the revision of the scope it changes.
    """

    def __init__(self, path: Path, endpoints=None):
        self.path = Path(path)
        self._lock = RLock()
        # Callable returning the configured LLM endpoint table.
        self.endpoints = endpoints

    def _endpoints(self):
        return self.endpoints() if self.endpoints else None

    def load(self) -> dict:
        with self._lock:
            return legacy_pair_view(validate_library(self._read_raw(), self._endpoints()))

    def _read_raw(self):
        if self.path.is_symlink():
            raise ProfileError("角色設定不可使用符號連結")
        try:
            return yaml.safe_load(self.path.read_text("utf-8"))
        except OSError as exc:
            raise ProfileError("無法讀取角色設定", 503) from exc
        except yaml.YAMLError as exc:
            raise ProfileError("角色設定 YAML 無法解析") from exc

    def _stored(self) -> tuple[dict, dict]:
        """The stored library as written and validated; a version 1 file is backed up first."""
        raw = self._read_raw()
        if isinstance(raw, dict) and raw.get("version") == 1:
            self._backup_version_1()
        stored = canonical(raw)
        return stored, validate_library(deepcopy(stored), self._endpoints())

    def _backup_version_1(self) -> Path:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.v1-{stamp}.bak")
        number = 1
        while backup.exists():
            backup = self.path.with_name(f"{self.path.name}.v1-{stamp}-{number}.bak")
            number += 1
        shutil.copy2(self.path, backup)
        logger.info("角色設定轉換為角色組合（版本 2），原檔備份於 %s", backup)
        return backup

    def initialize(self, config, *, defaults_path: Path | None = None) -> dict:
        """Migrate missing settings once, preserving every explicit role choice."""
        with self._lock:
            if self.endpoints is None:
                self.endpoints = lambda: configured_endpoints(config.llm)
            if self.path.exists() or self.path.is_symlink():
                raw = self._read_raw()
                upgrade = isinstance(raw, dict) and raw.get("version") == 1
                if upgrade:
                    self._backup_version_1()
                raw = canonical(raw)
                # Voice migration decodes and hashes audio: done once here and
                # saved as is, even while a legacy endpoint keeps the rest unsaved.
                if _migrate_voice_settings(raw) or upgrade:
                    self._write(raw)
                library = validate_library(deepcopy(raw), self._endpoints())
                legacy = [p for p, original in zip(library["profiles"], raw["profiles"])
                          if "endpoint" not in original["llm"]]
                # An unlisted legacy URL stays on disk until an admin picks an
                # endpoint; applying that role is refused meanwhile.
                unresolved = any(not p["llm"]["endpoint"] for p in legacy)
                changed = bool(legacy)
                for profile, original in zip(library["profiles"], raw["profiles"]):
                    for key, value in _playback_settings(config).items():
                        if key not in original["llm"]:
                            profile["llm"][key] = value
                            changed = True
                if changed and not unresolved:
                    library["revision"] += 1
                    library["profiles_revision"] += 1
                    self._write(library)
                return legacy_pair_view(library)
            defaults_path = defaults_path or Path(__file__).resolve().parents[2] / "config/avatar_profiles.defaults.yaml"
            defaults = yaml.safe_load(defaults_path.read_text("utf-8"))
            main = dict(id="main", name=config.llm.assistant_profile.assistant_name or config.model.avatar_id,
                        engine=config.model.type, avatar_id=config.model.avatar_id,
                        assistant_profile=asdict(config.llm.assistant_profile),
                        llm={"endpoint": active_endpoint_name(config.llm),
                             **{key: getattr(config.llm, key) for key in LLM_FIELDS if key != "endpoint"}},
                        tts=asdict(config.tts), rag=avatar_settings(config.model.avatar_id),
                        reply_rules=rules_from_config(config), greeting=asdict(config.greeting))
            main["llm"].update(_playback_settings(config))
            specialist = deepcopy(main)
            specialist.update(id="weather", name=defaults["specialist"]["name"],
                              engine="musetalk", avatar_id=defaults["specialist"]["avatar_id"],
                              assistant_profile=defaults["specialist"]["assistant_profile"],
                              rag={"enabled": False, "dataset_ids": []}, tools={"weather": True})
            # The defaults keep the version 1 shape; migrating them seeds the composition.
            seed = canonical(dict(version=1, revision=1, enabled=False,
                profiles=[main, specialist], pair={"main": "main", "specialist": "weather"},
                transitions=[], handoff=defaults["handoff"], weather={"county": "", "town": ""}))
            seed.update(revision=1, profiles_revision=1)
            library = validate_library(seed, self._endpoints(), require_endpoint=True)
            self._write(library)
            return legacy_pair_view(library)

    def _commit(self, current: dict, library: dict, renamed: dict | None = None) -> dict:
        """Write a whole validated ``library`` over ``current``; return its view."""
        library["composition"] = bump_revisions(current["composition"], library["composition"], renamed)
        library["revision"] = current["revision"] + 1
        library["profiles_revision"] = current["profiles_revision"] + (library["profiles"] != current["profiles"])
        self._write(library)
        return legacy_pair_view(library)

    def save(self, value: dict, *, expected_revision: int) -> dict:
        """Temporary adapter: save a whole library in the two-role shape.

        The pair, handoff, weather and transitions keys are mapped onto the
        composition; every other member keeps its settings. Checks the file
        ``revision``. The settings UI ticket replaces this with save_profiles
        and the composition saves below.
        """
        if not isinstance(value, dict) or not isinstance(value.get("profiles"), list):
            raise ProfileError("角色設定格式不正確")
        raw_tools = {p.get("id"): p.get("tools") for p in value["profiles"] if isinstance(p, dict)}
        with self._lock:
            _, current = self._stored()
            composition = apply_legacy_view(current["composition"], value, raw_tools)
            candidate = dict(version=2, revision=current["revision"],
                             profiles_revision=current["profiles_revision"],
                             profiles=value["profiles"], composition=composition)
            library = validate_library(candidate, self._endpoints(), require_endpoint=True, require_voice=True)
            if type(expected_revision) is not int or current["revision"] != expected_revision:
                raise ProfileError("設定已被其他控制台修改，請重新載入", 409,
                                   conflict={"scope": "library", "revision": current["revision"]})
            return self._commit(current, library)

    def save_profiles(self, profiles: list, *, expected_revision: int) -> dict:
        """Save the profile list; checks ``profiles_revision`` only.

        A profile in the composition cannot be removed; transition overrides
        of a removed profile are dropped.
        """
        if not isinstance(profiles, list):
            raise ProfileError("數位人設定檔格式不正確")
        with self._lock:
            _, current = self._stored()
            _expect(expected_revision, current["profiles_revision"], "profiles",
                    "數位人設定檔已被其他控制台修改，請重新載入")
            ids = {p.get("id") for p in profiles if isinstance(p, dict)}
            names = {p["id"]: p["name"] for p in current["profiles"]}
            missing = sorted(profile_ids(current) - ids)
            if missing:
                raise ProfileError(f"「{'、'.join(names[pid] for pid in missing)}」在當次角色組合中，"
                                   "請先移出組合或更換主數位人再刪除", 409, field="profiles")
            composition = deepcopy(current["composition"])
            transitions = composition["transitions"]
            transitions["overrides"] = [e for e in transitions["overrides"]
                                        if e["source"] in ids and e["target"] in ids]
            candidate = dict(version=2, revision=current["revision"],
                             profiles_revision=current["profiles_revision"],
                             profiles=profiles, composition=composition)
            library = validate_library(candidate, self._endpoints(), require_endpoint=True, require_voice=True)
            return self._commit(current, library)

    def _update_composition(self, change, renamed: dict | None = None) -> dict:
        """Apply ``change(library) -> composition``; profiles stay byte for byte."""
        with self._lock:
            stored, current = self._stored()
            names = {p["id"]: p["name"] for p in current["profiles"]}
            composition = validate_composition(change(current), names)
            composition = bump_revisions(current["composition"], composition, renamed)
            stored.update(composition=composition, revision=current["revision"] + 1)
            self._write(stored)
            return legacy_pair_view(dict(current, composition=composition, revision=stored["revision"]))

    def update_composition(self, *, expected_revision: int, main=None, enabled=None,
                           confirm_disable=False) -> tuple[dict, list[str]]:
        """Change the main avatar and/or the handoff switch; checks the composition revision.

        Enabled members incompatible with a new main avatar are refused unless
        ``confirm_disable`` is true, which disables them; returns their ids.
        """
        disabled: list[str] = []

        def change(library):
            composition = deepcopy(library["composition"])
            _expect(expected_revision, composition["revision"], "composition",
                    "角色組合已被其他控制台修改，請重新載入", current=library["composition"])
            if enabled is not None:
                if not isinstance(enabled, bool):
                    raise ProfileError("角色交接啟用狀態不正確", field="enabled")
                composition["enabled"] = enabled
            if main is not None and main != composition["main"]["profile_id"]:
                profiles = {p["id"]: p for p in library["profiles"]}
                if main not in profiles:
                    raise ProfileError("找不到這份數位人設定檔", 404, field="main")
                if any(m["profile_id"] == main for m in composition["members"]):
                    raise ProfileError(f"「{profiles[main]['name']}」目前是專門數位人，請先移出角色組合再設為主數位人",
                                       409, field="main")
                broken = [m for m in composition["members"]
                          if m["enabled"] and incompatibility(profiles[main], profiles[m["profile_id"]])]
                if broken and confirm_disable is not True:
                    names = "、".join(profiles[m["profile_id"]]["name"] for m in broken)
                    raise ProfileError(f"更換主數位人後「{names}」不相容，確認後會一併停用", 409, field="main",
                                       disable_required=[m["profile_id"] for m in broken])
                for member in broken:
                    member["enabled"] = False
                    disabled.append(member["profile_id"])
                composition["main"]["profile_id"] = main
            return composition

        return self._update_composition(change), disabled

    def save_main(self, value: dict, *, expected_revision: int) -> dict:
        """Save the main avatar's handoff fields; checks only its revision."""
        def change(library):
            composition = deepcopy(library["composition"])
            main = composition["main"]
            fields_ = _object(value, {"profile_id", "revision", *HANDOFF_FIELDS}, "主數位人")
            if fields_.get("profile_id", main["profile_id"]) != main["profile_id"]:
                raise ProfileError("主數位人已更換，請重新載入", 409, conflict={
                    "scope": "composition", "revision": composition["revision"], "current": library["composition"]})
            _expect(expected_revision, main["revision"], "main",
                    "主數位人的交接設定已被其他控制台修改，請重新載入；其他成員不受影響",
                    current=library["composition"]["main"], profile_id=main["profile_id"])
            main.update({key: fields_[key] for key in HANDOFF_FIELDS if key in fields_})
            return composition
        return self._update_composition(change)

    def add_member(self, value: dict, *, expected_revision: int) -> dict:
        """Add a specialist (disabled unless ``enabled``); checks the composition revision."""
        def change(library):
            composition = deepcopy(library["composition"])
            _expect(expected_revision, composition["revision"], "composition",
                    "角色組合已被其他控制台修改，請重新載入", current=library["composition"])
            fields_ = _object(value, _MEMBER_INPUT, "專門數位人")
            member = {**new_member(fields_.get("profile_id")),
                      **{key: item for key, item in fields_.items() if key != "revision"}}
            _require_compatible(library, member)
            composition["members"].append(member)
            return composition
        return self._update_composition(change)

    def save_member(self, profile_id: str, value: dict, *, expected_revision: int,
                    expected_composition_revision: int | None = None) -> dict:
        """Save one specialist; checks only its revision.

        Omitted fields keep their values. Changing ``enabled`` or pointing the
        member at another ``profile_id`` also checks the composition revision.
        """
        renamed: dict[str, str] = {}

        def change(library):
            composition = deepcopy(library["composition"])
            members = composition["members"]
            index = next((i for i, m in enumerate(members) if m["profile_id"] == profile_id), None)
            if index is None:
                raise ProfileError("這位專門數位人已不在角色組合中，請重新載入", 409, conflict={
                    "scope": "composition", "revision": composition["revision"], "current": library["composition"]})
            stored = members[index]
            name = next(p["name"] for p in library["profiles"] if p["id"] == profile_id)
            _expect(expected_revision, stored["revision"], "member",
                    f"「{name}」已被其他控制台修改，請重新載入這位；其他成員不受影響",
                    current=library["composition"]["members"][index], profile_id=profile_id)
            fields_ = _object(value, _MEMBER_INPUT, "專門數位人")
            member = {**stored, **{key: item for key, item in fields_.items() if key != "revision"}}
            structural = member["profile_id"] != profile_id or member["enabled"] != stored["enabled"]
            if structural:
                _expect(expected_composition_revision, composition["revision"], "composition",
                        "角色組合已被其他控制台修改，請重新載入", current=library["composition"])
            if member["profile_id"] != profile_id:
                renamed[member["profile_id"]] = profile_id
            if member["enabled"] is True and structural:
                _require_compatible(library, member)
            members[index] = member
            return composition
        return self._update_composition(change, renamed)

    def remove_member(self, profile_id: str, *, expected_revision: int) -> dict:
        """Remove a specialist; its profile and transition overrides stay. Checks the composition revision."""
        def change(library):
            composition = deepcopy(library["composition"])
            _expect(expected_revision, composition["revision"], "composition",
                    "角色組合已被其他控制台修改，請重新載入", current=library["composition"])
            members = [m for m in composition["members"] if m["profile_id"] != profile_id]
            if len(members) == len(composition["members"]):
                raise ProfileError("這位專門數位人已不在角色組合中，請重新載入", 404)
            composition["members"] = members
            return composition
        return self._update_composition(change)

    def save_transitions(self, value: dict, *, expected_revision: int) -> dict:
        """Save the default transition and the directed overrides; checks only their revision."""
        def change(library):
            composition = deepcopy(library["composition"])
            transitions = composition["transitions"]
            fields_ = _object(value, {"revision", "default", "overrides"}, "角色轉場")
            _expect(expected_revision, transitions["revision"], "transitions",
                    "角色轉場已被其他控制台修改，請重新載入", current=library["composition"]["transitions"])
            transitions.update({key: fields_[key] for key in ("default", "overrides") if key in fields_})
            return composition
        return self._update_composition(change)

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".avatar-profiles-", delete=False) as handle:
                temporary = handle.name
                handle.write("# Nova Avatar role profiles. Credentials stay in the server environment.\n")
                yaml.safe_dump(value, handle, allow_unicode=True, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def _require_compatible(library: dict, member: dict) -> None:
    """An enabled member must share the main avatar's engines and services."""
    if member.get("enabled") is not True:
        return
    profiles = {p["id"]: p for p in library["profiles"]}
    profile = profiles.get(member.get("profile_id"))
    if profile is None:
        raise ProfileError("找不到這份數位人設定檔", 404, field="profile_id")
    reasons = incompatibility(profiles[library["composition"]["main"]["profile_id"]], profile)
    if reasons:
        raise ProfileError(f"「{profile['name']}」與主數位人不相容，無法啟用：{'；'.join(reasons)}",
                           409, field="enabled", reasons=reasons)


def compatible_pair(library: dict, base=None) -> tuple[dict, dict]:
    """Temporary two-role adapter: the view's pair, refused when it cannot run live."""
    profiles = {p["id"]: p for p in library["profiles"]}
    main, specialist = (profiles[library["pair"][key]] for key in ("main", "specialist"))
    reasons = incompatibility(main, specialist)
    if reasons:
        raise ProfileError(reasons[0], 409)
    if base is not None and main["tts"]["type"] != base.tts.type:
        raise ProfileError("語音引擎改變後請先在未連線時載入該引擎", 409)
    return main, specialist
