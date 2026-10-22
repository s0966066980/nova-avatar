# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Atomic, non-secret role profiles; rendering and conversations are runtime state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from urllib.parse import urlsplit

import yaml

from src.config.schema import AssistantProfileConfig, ReplyRulesConfig, TTSConfig, GreetingConfig
from src.greetings.content import validate_content
from src.llm.rules import rules_from_config, validate_rules
from src.ragflow.settings import avatar_settings
from src.ragflow.selection import validate_selection

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}")
LLM_FIELDS = ("provider", "model", "base_url", "max_tokens", "response_max_chars")
LLM_PLAYBACK_DEFAULTS = {"board_max_items": 8, "reply_mode": "legacy", "semantic_wait_seconds": 0.5}
EFFECTS = ("fade", "slide_left", "slide_right", "zoom")


def _playback_settings(config):
    return dict(board_max_items=config.llm.board.max_items,
                reply_mode="streaming" if config.reply_streaming.enabled else "legacy",
                semantic_wait_seconds=config.reply_streaming.semantic_wait_seconds)


class ProfileError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _text(value, label, limit=12000, *, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ProfileError(f"{label} 格式或長度不正確")
    return value.strip()


def _identifier(value, label="角色識別碼"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProfileError(f"{label} 不正確")
    return value


def _object(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ProfileError(f"{label} 含未知欄位或格式不正確")
    return value


def _endpoint(value):
    value = _text(value, "模型服務網址", 500)
    parsed = urlsplit(value)
    if value and (parsed.scheme not in {"http", "https"} or not parsed.hostname
                  or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ProfileError("模型服務網址不可包含帳密、查詢參數或片段")
    return value


def profile_config(base, profile: dict):
    """Keep server credentials and engine options private; apply a role snapshot."""
    result = deepcopy(base)
    result.profile_id = profile["id"]
    result.model.type = profile["engine"]
    result.model.avatar_id = profile["avatar_id"]
    for key, value in profile["llm"].items():
        if key == "board_max_items":
            result.llm.board.max_items = value
        elif key == "reply_mode":
            result.reply_streaming.enabled = value == "streaming"
        elif key == "semantic_wait_seconds":
            result.reply_streaming.semantic_wait_seconds = value
        else:
            setattr(result.llm, key, value)
    result.llm.assistant_profile = AssistantProfileConfig(**profile["assistant_profile"])
    result.llm.reply_rules = ReplyRulesConfig(**profile["reply_rules"])
    result.tts = TTSConfig(**profile["tts"])
    result.greeting = GreetingConfig(**validate_content(profile.get("greeting")))
    result.profile_rag = deepcopy(profile["rag"])
    return result


def validate_profile(value: dict) -> dict:
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
    llm = _object(value.get("llm"), (*LLM_FIELDS, *LLM_PLAYBACK_DEFAULTS), "回答模型")
    llm = {**LLM_PLAYBACK_DEFAULTS, **llm}
    for key in ("provider", "model"):
        llm[key] = _text(llm.get(key), key, 160, empty=False)
    llm["base_url"] = _endpoint(llm.get("base_url", ""))
    for key, lower, upper in (("max_tokens", 16, 8192), ("response_max_chars", 20, 2000)):
        number = llm.get(key, 128)
        if isinstance(number, bool) or not isinstance(number, int) or not lower <= number <= upper:
            raise ProfileError(f"{key} 必須介於 {lower}–{upper}")
        llm[key] = number
    if llm["provider"] not in {"llamacpp", "ollama", "openai"}:
        raise ProfileError("回答模型服務不正確")
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
    if tts["tts_server"]:
        tts["tts_server"] = _endpoint(tts["tts_server"])
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
    tools = _object(value.get("tools", {"weather": False}), {"weather"}, "角色工具")
    if not isinstance(tools.get("weather"), bool):
        raise ProfileError("天氣工具啟用狀態不正確")
    try:
        greeting = validate_content(value.get("greeting"))
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    return {"id": pid, "name": name, "engine": engine, "avatar_id": avatar_id,
            "assistant_profile": identity, "llm": llm, "tts": tts,
            "rag": rag, "reply_rules": rules,
            "tools": dict(tools), "greeting": greeting}


def validate_library(value: dict) -> dict:
    _object(value, {"version", "revision", "enabled", "profiles", "pair", "transitions",
                    "handoff", "weather", "migrated"}, "角色設定")
    if value.get("version") != 1 or not isinstance(value.get("enabled"), bool):
        raise ProfileError("角色設定版本或啟用狀態不正確")
    profiles = value.get("profiles")
    if not isinstance(profiles, list) or not 2 <= len(profiles) <= 30:
        raise ProfileError("請保存 2–30 份角色設定檔")
    normalized = [validate_profile(p) for p in profiles]
    ids = {p["id"] for p in normalized}
    if len(ids) != len(normalized):
        raise ProfileError("角色識別碼不可重複")
    pair = _object(value.get("pair"), {"main", "specialist"}, "角色組合")
    if pair.get("main") not in ids or pair.get("specialist") not in ids or pair["main"] == pair["specialist"]:
        raise ProfileError("請選擇兩份不同的主角色與專門角色設定檔")
    transitions = value.get("transitions")
    if not isinstance(transitions, list) or len(transitions) > 200:
        raise ProfileError("轉場設定格式不正確")
    seen, edges = set(), []
    for edge in transitions:
        _object(edge, {"source", "target", "kind", "effect", "duration", "asset_id"}, "角色轉場")
        source, target = edge.get("source"), edge.get("target")
        if source not in ids or target not in ids or source == target or (source, target) in seen:
            raise ProfileError("轉場來源、目的或重複設定不正確")
        seen.add((source, target))
        kind, effect = edge.get("kind", "effect"), edge.get("effect", "fade")
        duration = edge.get("duration", 0.6)
        if kind not in {"effect", "video"} or effect not in EFFECTS:
            raise ProfileError("轉場類型或特效不正確")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not .2 <= duration <= 2:
            raise ProfileError("特效時長必須介於 0.2–2 秒")
        asset = edge.get("asset_id", "")
        if asset:
            _identifier(asset, "轉場影片識別碼")
        if kind == "video" and not asset:
            raise ProfileError("請選擇轉場影片")
        edges.append(dict(source=source, target=target, kind=kind, effect=effect,
                          duration=float(duration), asset_id=asset))
    handoff = _object(value.get("handoff"), {"description", "rules", "announcement"}, "角色交接")
    handoff = {key: _text(handoff.get(key), key, 12000 if key == "rules" else 2000, empty=False)
               for key in ("description", "rules", "announcement")}
    weather = _object(value.get("weather"), {"county", "town"}, "天氣地點")
    weather = {key: _text(weather.get(key, ""), key, 80) for key in ("county", "town")}
    weather = {key: value.replace("台", "臺") for key, value in weather.items()}
    revision = value.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ProfileError("設定版本不正確")
    return dict(version=1, revision=revision, enabled=value["enabled"],
                profiles=normalized, pair=dict(pair), transitions=edges, handoff=handoff,
                weather=weather, migrated=True)


class ProfileStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = RLock()

    def load(self) -> dict:
        with self._lock:
            if self.path.is_symlink():
                raise ProfileError("角色設定不可使用符號連結")
            try:
                return validate_library(yaml.safe_load(self.path.read_text("utf-8")))
            except OSError as exc:
                raise ProfileError("無法讀取角色設定", 503) from exc
            except yaml.YAMLError as exc:
                raise ProfileError("角色設定 YAML 無法解析") from exc

    def initialize(self, config, *, defaults_path: Path | None = None) -> dict:
        """Migrate missing settings once, preserving every explicit role choice."""
        with self._lock:
            if self.path.exists() or self.path.is_symlink():
                library = self.load()
                raw = yaml.safe_load(self.path.read_text("utf-8"))
                changed = False
                for profile, original in zip(library["profiles"], raw["profiles"]):
                    for key, value in _playback_settings(config).items():
                        if key not in original["llm"]:
                            profile["llm"][key] = value
                            changed = True
                if changed:
                    library["revision"] += 1
                    self._write(library)
                return library
            defaults_path = defaults_path or Path(__file__).resolve().parents[2] / "config/avatar_profiles.defaults.yaml"
            defaults = yaml.safe_load(defaults_path.read_text("utf-8"))
            main = dict(id="main", name=config.llm.assistant_profile.assistant_name or config.model.avatar_id,
                        engine=config.model.type, avatar_id=config.model.avatar_id,
                        assistant_profile=asdict(config.llm.assistant_profile),
                        llm={key: getattr(config.llm, key) for key in LLM_FIELDS},
                        tts=asdict(config.tts), rag=avatar_settings(config.model.avatar_id),
                        reply_rules=rules_from_config(config), greeting=asdict(config.greeting))
            main["llm"].update(_playback_settings(config))
            specialist = deepcopy(main)
            specialist.update(id="weather", name=defaults["specialist"]["name"],
                              engine="musetalk", avatar_id=defaults["specialist"]["avatar_id"],
                              assistant_profile=defaults["specialist"]["assistant_profile"],
                              rag={"enabled": False, "dataset_ids": []}, tools={"weather": True})
            library = validate_library(dict(version=1, revision=1, enabled=False, migrated=True,
                profiles=[main, specialist], pair={"main": "main", "specialist": "weather"},
                transitions=[], handoff=defaults["handoff"], weather={"county": "", "town": ""}))
            self._write(library)
            return deepcopy(library)

    def save(self, value: dict, *, expected_revision: int) -> dict:
        normalized = validate_library(value)
        with self._lock:
            current = self.load()
            if type(expected_revision) is not int or current["revision"] != expected_revision:
                raise ProfileError("設定已被其他控制台修改，請重新載入", 409)
            normalized["revision"] = current["revision"] + 1
            self._write(normalized)
        return deepcopy(normalized)

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


def compatible_pair(library: dict, base=None) -> tuple[dict, dict]:
    profiles = {p["id"]: p for p in library["profiles"]}
    main, specialist = (profiles[library["pair"][key]] for key in ("main", "specialist"))
    if main["engine"] != "musetalk" or specialist["engine"] != "musetalk":
        raise ProfileError("首版即時組合需要兩位 MuseTalk 數位人", 409)
    if any(main["llm"].get(key) != specialist["llm"].get(key) for key in ("provider", "model", "base_url")):
        raise ProfileError("即時組合必須共用同一 LLM 服務及模型", 409)
    if main["tts"]["type"] != specialist["tts"]["type"]:
        raise ProfileError("即時組合需共用語音合成引擎，可分別設定聲線", 409)
    if base is not None and main["tts"]["type"] != base.tts.type:
        raise ProfileError("語音引擎改變後請先在未連線時載入該引擎", 409)
    return main, specialist
