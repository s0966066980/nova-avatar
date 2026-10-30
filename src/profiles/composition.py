# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""當次角色組合: one main avatar and up to five enabled specialists (ADR 0023).

Holds the version 2 schema, the version 1 migration, per-scope revisions and
member compatibility. ``legacy_pair_view`` and ``apply_legacy_view`` are a
temporary adapter that keeps the two-role runtime and console working until
the N-way routing, runtime and settings UI replace them.
"""
from __future__ import annotations

from copy import deepcopy

from src.profiles.validation import ProfileError, identifier, obj, revision, text
from src.tts.cosyvoice_runtime import server_identity
from src.utils.logging import logger

MAX_ENABLED_MEMBERS = 5
# Every profile but the main one; the library holds at most 30.
MAX_MEMBERS = 29
EFFECTS = ("fade", "slide_left", "slide_right", "zoom")
DEFAULT_TRANSITION = {"kind": "effect", "effect": "fade", "duration": 0.6, "asset_id": ""}
MAIN_ANNOUNCEMENTS = {
    "announcement": "接下來請主數位人接續回答您的問題。",
    "announcement_en": "Our main avatar will help with your question next.",
}
HANDOFF_FIELDS = ("description", "rules", "announcement", "announcement_en")
_LIMITS = {"description": 2000, "rules": 12000, "announcement": 2000, "announcement_en": 2000}
_LABELS = {"description": "專長介紹", "rules": "交接規則", "announcement": "交接說明",
           "announcement_en": "英文交接說明"}
# Added by the two-role view or left by version 1; never stored in version 2.
VIEW_KEYS = ("enabled", "pair", "handoff", "weather", "transitions", "migrated")


# ── Schema ────────────────────────────────────────────────────────────────

def _handoff_text(value, who):
    return {key: text(value.get(key, ""), f"{who}的{_LABELS[key]}", _LIMITS[key],
                      empty=key != "announcement", field=key)
            for key in HANDOFF_FIELDS}


def _tools(value):
    tools = obj({} if value is None else value, {"weather"}, "角色工具")
    weather = obj(tools.get("weather", {}), {"enabled", "county", "town"}, "天氣工具")
    enabled = weather.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ProfileError("天氣工具啟用狀態不正確", field="tools.weather.enabled")
    site = {key: text(weather.get(key, ""), "場域預設地點", 80, field=f"tools.weather.{key}").replace("台", "臺")
            for key in ("county", "town")}
    return {"weather": {"enabled": enabled, **site}}


def _main(value):
    value = obj(value, {"profile_id", "revision", *HANDOFF_FIELDS}, "主數位人")
    return {"profile_id": identifier(value.get("profile_id"), "主數位人的設定檔"),
            "revision": revision(value.get("revision", 1), "主數位人的修訂版本"),
            **_handoff_text(value, "主數位人")}


def _member(value, names):
    value = obj(value, {"profile_id", "revision", "enabled", "tools", *HANDOFF_FIELDS}, "專門數位人")
    pid = identifier(value.get("profile_id"), "專門數位人的設定檔")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ProfileError("專門數位人的啟用狀態不正確", field="enabled")
    return {"profile_id": pid, "revision": revision(value.get("revision", 1), "專門數位人的修訂版本"),
            "enabled": enabled, **_handoff_text(value, f"「{names.get(pid, pid)}」"),
            "tools": _tools(value.get("tools"))}


def _transition(value, label, extra=()):
    value = obj(value, {"kind", "effect", "duration", "asset_id", *extra}, label)
    kind, effect = value.get("kind", "effect"), value.get("effect", "fade")
    duration = value.get("duration", 0.6)
    if kind not in {"effect", "video"} or effect not in EFFECTS:
        raise ProfileError("轉場類型或特效不正確")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not .2 <= duration <= 2:
        raise ProfileError("特效時長必須介於 0.2–2 秒")
    asset = value.get("asset_id", "")
    if asset:
        identifier(asset, "轉場影片識別碼")
    if kind == "video" and not asset:
        raise ProfileError("請選擇轉場影片")
    return dict(kind=kind, effect=effect, duration=float(duration), asset_id=asset)


def _transitions(value, names):
    value = obj(value, {"revision", "default", "overrides"}, "角色轉場")
    overrides = value.get("overrides", [])
    if not isinstance(overrides, list) or len(overrides) > 200:
        raise ProfileError("轉場設定格式不正確")
    seen, edges = set(), []
    for edge in overrides:
        normalized = _transition(edge, "角色轉場", ("source", "target"))
        source, target = edge.get("source"), edge.get("target")
        if source not in names or target not in names or source == target or (source, target) in seen:
            raise ProfileError("轉場來源、目的或重複設定不正確")
        seen.add((source, target))
        edges.append(dict(source=source, target=target, **normalized))
    return {"revision": revision(value.get("revision", 1), "角色轉場的修訂版本"),
            "default": _transition(value.get("default", DEFAULT_TRANSITION), "預設轉場"),
            "overrides": edges}


def validate_composition(value, names: dict) -> dict:
    """Normalize a composition against ``names`` (profile id -> display name)."""
    value = obj(value, {"revision", "enabled", "main", "members", "transitions"}, "角色組合")
    if not isinstance(value.get("enabled"), bool):
        raise ProfileError("角色交接啟用狀態不正確", field="enabled")
    main = _main(value.get("main"))
    if main["profile_id"] not in names:
        raise ProfileError("主數位人的設定檔不存在", 409, field="main")
    members = value.get("members", [])
    if not isinstance(members, list) or len(members) > MAX_MEMBERS:
        raise ProfileError("專門數位人清單格式不正確")
    members = [_member(m, names) for m in members]
    seen = set()
    for member in members:
        pid = member["profile_id"]
        if pid not in names:
            raise ProfileError(f"專門數位人的設定檔「{pid}」不存在", 409, field="profile_id")
        if pid == main["profile_id"]:
            raise ProfileError(f"「{names[pid]}」是主數位人，不能同時是專門數位人", 409, field="profile_id")
        if pid in seen:
            raise ProfileError(f"「{names[pid]}」已在角色組合中", 409, field="profile_id")
        seen.add(pid)
    if sum(m["enabled"] for m in members) > MAX_ENABLED_MEMBERS:
        raise ProfileError(f"最多同時啟用 {MAX_ENABLED_MEMBERS} 位專門數位人，請先停用一位", 409, field="enabled")
    holders = [m["profile_id"] for m in members if m["tools"]["weather"]["enabled"]]
    if len(holders) > 1:
        raise ProfileError(f"天氣工具同時只限一位專門數位人提供，目前由「{names[holders[0]]}」提供",
                           409, field="tools.weather.enabled")
    return {"revision": revision(value.get("revision"), "角色組合的修訂版本"), "enabled": value["enabled"],
            "main": main, "members": members,
            "transitions": _transitions(value.get("transitions", {"default": DEFAULT_TRANSITION}), names)}


def new_member(profile_id: str) -> dict:
    """A member as first added: disabled, without a tool; texts come from the console."""
    return {"profile_id": profile_id, "revision": 1, "enabled": False,
            **dict.fromkeys(HANDOFF_FIELDS, ""),
            "tools": {"weather": {"enabled": False, "county": "", "town": ""}}}


# ── Revisions ─────────────────────────────────────────────────────────────

def _structure(composition):
    """What only a composition-wide save may change (its own revision guards it)."""
    return (composition["enabled"], composition["main"]["profile_id"],
            [(m["profile_id"], m["enabled"]) for m in composition["members"]])


def _content(scope, *skip):
    return {key: value for key, value in scope.items() if key not in {"revision", *skip}}


def bump_revisions(old: dict, new: dict, renamed: dict | None = None) -> dict:
    """Give ``new`` the stored revisions, plus one for every scope that changed.

    Revisions in ``new`` itself are ignored: only the server assigns them.
    ``renamed`` maps a member's new profile id to the one it replaced.
    """
    new = deepcopy(new)
    new["revision"] = old["revision"] + (_structure(old) != _structure(new))
    new["main"]["revision"] = old["main"]["revision"] + (
        _content(old["main"], "profile_id") != _content(new["main"], "profile_id"))
    previous = {m["profile_id"]: m for m in old["members"]}
    for member in new["members"]:
        before = previous.get((renamed or {}).get(member["profile_id"], member["profile_id"]))
        member["revision"] = 1 if before is None else before["revision"] + (_content(before) != _content(member))
    new["transitions"]["revision"] = old["transitions"]["revision"] + (
        _content(old["transitions"]) != _content(new["transitions"]))
    return new


# ── Version 1 migration ───────────────────────────────────────────────────

def migrate_v1(raw: dict) -> dict:
    """Turn a version 1 pair library into version 2; profile fields are kept as is.

    pair.main becomes the main avatar; pair.specialist the first member with the
    single handoff block, the weather tool and site; the return announcement
    becomes the main avatar's announcement; directed transitions become
    overrides of a built-in fade.
    """
    raw = deepcopy(raw)
    profiles = raw.get("profiles") if isinstance(raw.get("profiles"), list) else []
    pair = raw.get("pair") if isinstance(raw.get("pair"), dict) else {}
    handoff = raw.get("handoff") if isinstance(raw.get("handoff"), dict) else {}
    site = raw.get("weather") if isinstance(raw.get("weather"), dict) else {}
    main_id, specialist_id = pair.get("main"), pair.get("specialist")
    holders = []
    for profile in profiles:
        tools = profile.pop("tools", None) if isinstance(profile, dict) else None
        if isinstance(tools, dict) and tools.get("weather") is True:
            holders.append(profile.get("id"))
    if set(holders) - {specialist_id}:
        logger.warning("角色組合轉換：天氣工具只保留給專門數位人 %s，移除 %s 的天氣工具",
                       specialist_id, sorted(set(holders) - {specialist_id}))
    members = []
    if specialist_id is not None and specialist_id != main_id:
        members.append({
            "profile_id": specialist_id, "revision": 1, "enabled": True,
            **{key: handoff.get(key, "") for key in HANDOFF_FIELDS},
            "tools": {"weather": {"enabled": specialist_id in holders,
                                  "county": site.get("county", ""), "town": site.get("town", "")}}})
    main = {"profile_id": main_id, "revision": 1, "description": "", "rules": "",
            "announcement": handoff.get("return_announcement") or MAIN_ANNOUNCEMENTS["announcement"],
            "announcement_en": handoff.get("return_announcement_en", MAIN_ANNOUNCEMENTS["announcement_en"])}
    number = raw.get("revision")
    number = number + 1 if type(number) is int else number
    return {"version": 2, "revision": number, "profiles_revision": number, "profiles": profiles,
            "composition": {"revision": 1, "enabled": raw.get("enabled", False), "main": main,
                            "members": members,
                            "transitions": {"revision": 1, "default": dict(DEFAULT_TRANSITION),
                                            "overrides": list(raw.get("transitions") or [])}}}


def canonical(raw) -> dict:
    """The stored form of ``raw``: version 1 is migrated, view keys are dropped."""
    if not isinstance(raw, dict):
        raise ProfileError("角色設定格式不正確")
    if raw.get("version") == 1:
        return migrate_v1(raw)
    value = {key: deepcopy(item) for key, item in raw.items() if key not in VIEW_KEYS}
    for profile in value.get("profiles") or ():
        if isinstance(profile, dict):
            profile.pop("tools", None)
    return value


# ── Reading a composition ─────────────────────────────────────────────────

def main_profile_id(library: dict) -> str:
    return library["composition"]["main"]["profile_id"]


def incompatibility(main: dict, profile: dict) -> list[str]:
    """Why ``profile`` cannot join ``main``'s live composition (empty when it can)."""
    reasons = []
    if main["engine"] != "musetalk" or profile["engine"] != "musetalk":
        reasons.append("首版即時組合需要兩位 MuseTalk 數位人")
    if any(main["llm"].get(key) != profile["llm"].get(key) for key in ("endpoint", "model")):
        reasons.append("即時組合必須共用同一 LLM 服務及模型")
    if main["tts"]["type"] != profile["tts"]["type"]:
        reasons.append("即時組合需共用語音合成引擎，可分別設定聲線")
    elif main["tts"]["type"] == "breezyvoice" and len({
            server_identity(p["tts"]["tts_server"], p["tts"]["model"]) for p in (main, profile)}) > 1:
        # Only the main role's BreezyVoice server is started; every role speaks through it.
        reasons.append("即時組合的數位人共用一個 BreezyVoice 伺服器，請在「聲音與工具」的"
                       "「其他 BreezyVoice 設定」選擇同一個 BreezyVoice 模型與服務網址；參考音檔可以不同")
    return reasons


def compatibility_report(library: dict) -> dict:
    """Profile id -> reasons it cannot join the saved main avatar's composition."""
    profiles = {p["id"]: p for p in library["profiles"]}
    main = profiles[main_profile_id(library)]
    return {pid: incompatibility(main, profile) for pid, profile in profiles.items() if pid != main["id"]}


def live_members(library: dict) -> list[dict]:
    """Members that take part in handoffs: enabled and compatible, handoff on."""
    composition = library["composition"]
    if not composition["enabled"]:
        return []
    profiles = {p["id"]: p for p in library["profiles"]}
    main = profiles[composition["main"]["profile_id"]]
    return [m for m in composition["members"]
            if m["enabled"] and not incompatibility(main, profiles[m["profile_id"]])]


def weather_holder(library: dict) -> dict | None:
    """The member holding the weather tool, enabled or not."""
    return next((m for m in library["composition"]["members"] if m["tools"]["weather"]["enabled"]), None)


def transition(library: dict, source: str, target: str) -> dict:
    """The override for ``source`` -> ``target``, otherwise the default."""
    transitions = library["composition"]["transitions"]
    edge = next((e for e in transitions["overrides"] if e["source"] == source and e["target"] == target),
                transitions["default"])
    return dict(edge, source=source, target=target)


def referenced_media(library: dict) -> set[str]:
    """Transition clips the library refers to, including the two-role view's edges."""
    transitions = library["composition"]["transitions"]
    edges = (transitions["default"], *transitions["overrides"], *library.get("transitions", ()))
    return {e["asset_id"] for e in edges if e.get("kind") == "video" and e.get("asset_id")}


def profile_ids(library: dict, *, enabled_only=False) -> set[str]:
    """The main avatar and the (enabled) members."""
    composition = library["composition"]
    return {composition["main"]["profile_id"],
            *(m["profile_id"] for m in composition["members"] if m["enabled"] or not enabled_only)}


# ── Temporary two-role adapter (remove with tickets 02–04) ────────────────

def _view_specialist(composition, profiles):
    main = profiles[composition["main"]["profile_id"]]
    members = composition["members"]
    return (next((m for m in members
                  if m["enabled"] and not incompatibility(main, profiles[m["profile_id"]])), None)
            or next((m for m in members if m["enabled"]), None)
            or next(iter(members), None))


def legacy_pair_view(library: dict) -> dict:
    """``library`` plus the version 1 keys the two-role runtime and console read.

    The pair's specialist is the first enabled, compatible member (else the
    first enabled, else the first one). Without any member the pair repeats
    the main avatar and handoff is off.
    """
    view = deepcopy(library)
    composition = view["composition"]
    profiles = {p["id"]: p for p in view["profiles"]}
    main = composition["main"]
    specialist = _view_specialist(composition, profiles)
    source = specialist or main
    view["enabled"] = bool(composition["enabled"] and specialist and specialist["enabled"])
    view["pair"] = {"main": main["profile_id"], "specialist": source["profile_id"]}
    view["handoff"] = {**{key: source[key] for key in HANDOFF_FIELDS},
                       "return_announcement": main["announcement"],
                       "return_announcement_en": main["announcement_en"]}
    site = specialist["tools"]["weather"] if specialist else {}
    view["weather"] = {"county": site.get("county", ""), "town": site.get("town", "")}
    view["transitions"] = deepcopy(composition["transitions"]["overrides"])
    holder = weather_holder(view)
    for profile in view["profiles"]:
        profile["tools"] = {"weather": holder is not None and profile["id"] == holder["profile_id"]}
    return view


def apply_legacy_view(composition: dict, value: dict, raw_tools: dict) -> dict:
    """Map a save in the two-role shape onto ``composition``; other members stay.

    ``raw_tools`` maps a submitted profile id to its submitted ``tools``.
    """
    pair = obj(value.get("pair"), {"main", "specialist"}, "角色組合")
    main_id, specialist_id = pair.get("main"), pair.get("specialist")
    if main_id not in raw_tools or specialist_id not in raw_tools or main_id == specialist_id:
        raise ProfileError("請選擇兩份不同的主角色與專門角色設定檔")
    handoff = obj(value.get("handoff"), {*HANDOFF_FIELDS, "return_announcement", "return_announcement_en"},
                  "角色交接")
    site = obj(value.get("weather", {}), {"county", "town"}, "天氣地點")
    if not isinstance(value.get("enabled"), bool):
        raise ProfileError("角色設定版本或啟用狀態不正確")
    result = deepcopy(composition)
    result["enabled"] = value["enabled"]
    main = result["main"]
    main["profile_id"] = main_id
    for key, legacy in (("announcement", "return_announcement"), ("announcement_en", "return_announcement_en")):
        if legacy in handoff:
            main[key] = handoff[legacy]
    members = [m for m in result["members"] if m["profile_id"] != main_id]
    member = next((m for m in members if m["profile_id"] == specialist_id), None)
    if member is None:
        member = new_member(specialist_id)
    else:
        members.remove(member)
    members.insert(0, member)
    member.update({key: handoff.get(key, "") for key in HANDOFF_FIELDS})
    if value["enabled"]:
        member["enabled"] = True
    weather = member["tools"]["weather"]
    tools = raw_tools.get(specialist_id)
    if isinstance(tools, dict) and isinstance(tools.get("weather"), bool):
        weather["enabled"] = tools["weather"]
    weather.update(county=site.get("county", ""), town=site.get("town", ""))
    if weather["enabled"]:
        for other in members[1:]:
            other["tools"]["weather"]["enabled"] = False
    result["members"] = members
    result["transitions"]["overrides"] = value.get("transitions", result["transitions"]["overrides"])
    return result
