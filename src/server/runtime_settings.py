# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定：Ollama 模型列表、LLM 切換、數字人切換與配置持久化。"""
from __future__ import annotations

import gc
import base64
import threading
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from src.avatars.catalog import (
    ENGINE_META,
    apply_engine_paths,
    is_safe_avatar_id,
    list_avatar_characters,
    list_engines,
)
from src.avatars.mouth_quality import (
    QualityError,
    apply_quality_to_model,
    quality_from_model,
)
from src.config.overrides import persist_runtime_overrides
from src.llm.base import (
    DEFAULT_RESPONSE_MAX_CHARS,
    load_system_prompt,
    response_token_budget,
    validate_response_max_chars,
)
from src.llm.llamacpp import (
    ensure_server,
    find_llama_server,
    list_gguf_models,
    openai_base_url,
    server_status,
)
from src.llm.service import switch_llm_endpoint
from src.llm.rules import default_rules, rules_from_config, snapshot_from_config, validate_rules
from src.asr.factory import activate_asr_engine, create_asr_engine
from src.asr.engines.funasr import local_funasr_model_ready
from src.tts.cosyvoice_runtime import (
    cosyvoice_family,
    is_cosyvoice_engine,
    languages_for_family,
    normalize_language,
)
from src.utils.logging import logger

_SWITCH_LOCK = threading.Lock()
_RULES_LOCK = threading.RLock()

DEFAULT_STAGE_CAPTION_MAX_CHARS = 120
MIN_STAGE_CAPTION_MAX_CHARS = 20
MAX_STAGE_CAPTION_MAX_CHARS = 2000
DEFAULT_CAPTION_X = 50
DEFAULT_CAPTION_Y = 90
DEFAULT_CAPTION_WIDTH = 100
MIN_CAPTION_WIDTH = 40
BOARD_STYLES = ("glass", "slate", "cue")
BOARD_PRESETS = ("tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br", "custom")
DEFAULT_BOARD_STYLE = "glass"
DEFAULT_BOARD_WIDTH = 252
DEFAULT_BOARD_HEIGHT = 300
DEFAULT_BOARD_TRANSPARENCY = 28
DEFAULT_BOARD_X = 100
DEFAULT_BOARD_Y = 0
DEFAULT_BOARD_PRESET = "tr"
DEFAULT_BOARD_OPEN_X = 50
DEFAULT_BOARD_OPEN_Y = 8
DEFAULT_MIC_X = 50
DEFAULT_MIC_Y = 62
DEFAULT_MIC_PRESET = "custom"
MIN_BOARD_WIDTH = 200
MAX_BOARD_WIDTH = 720
MIN_BOARD_HEIGHT = 180
MAX_BOARD_HEIGHT = 720
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


class SettingsError(Exception):
    def __init__(self, message: str, status: int = 400, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra or {}


def ollama_native_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url or "http://localhost:11434"


def is_ollama_endpoint(base_url: str) -> bool:
    raw = (base_url or "").lower()
    if "11434" in raw or "ollama" in raw:
        return True
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


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
    provider = (getattr(config.llm, "provider", "") or "").strip().lower()
    if provider in {"ollama", "llamacpp"}:
        return provider
    if "11434" in (config.llm.base_url or ""):
        return "ollama"
    if "8080" in (config.llm.base_url or "") or str(config.llm.model).endswith(".gguf"):
        return "llamacpp"
    return "ollama" if is_ollama_endpoint(config.llm.base_url) else "openai"


def current_snapshot(config) -> Dict[str, Any]:
    characters = list_avatar_characters()
    engines = list_engines(characters)
    llm = config.llm
    model_cfg = config.model
    return {
        "llm": {
            "model": llm.model,
            "base_url": llm.base_url,
            "provider": resolve_provider(config),
            "system_prompt": load_system_prompt(config),
            "assistant_profile": assistant_profile_snapshot(config),
            "response_max_chars": int(
                getattr(llm, "response_max_chars", DEFAULT_RESPONSE_MAX_CHARS)
            ),
            "board_max_items": validate_board_max_items(
                getattr(getattr(llm, "board", None), "max_items", 8)
            ),
            "reply_mode": (
                "streaming"
                if bool(getattr(config.reply_streaming, "enabled", False))
                else "legacy"
            ),
            "semantic_wait_seconds": float(
                getattr(config.reply_streaming, "semantic_wait_seconds", 5.0) or 5.0
            ),
            "reply_rules": rules_from_config(config),
        },
        "avatar": {
            "type": model_cfg.type,
            "avatar_id": model_cfg.avatar_id,
        },
        "avatar_quality": quality_from_model(model_cfg),
        "engines": engines,
        "characters": characters,
        "vad": vad_snapshot(config),
        "speech": speech_snapshot(config),
        "stage": stage_snapshot(config),
    }


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
            from src.config.schema import ReplyRulesConfig
            rule_config = ReplyRulesConfig()
            config.llm.reply_rules = rule_config
        rule_config.revision = int(checked["revision"])
        rule_config.activation = str(checked["activation"])
        rule_config.speech = str(checked["speech"])
        rule_config.board = str(checked["board"])
        try:
            persist_runtime_overrides(config)
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


def validate_stage_caption_max_chars(value) -> int:
    """驗證舞台字幕顯示上限。"""
    if isinstance(value, bool):
        raise ValueError("舞台字幕顯示上限必須是整數")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("舞台字幕顯示上限必須是整數") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("舞台字幕顯示上限必須是整數")
    if not MIN_STAGE_CAPTION_MAX_CHARS <= normalized <= MAX_STAGE_CAPTION_MAX_CHARS:
        raise ValueError(
            f"舞台字幕顯示上限必須介於 {MIN_STAGE_CAPTION_MAX_CHARS} 到 "
            f"{MAX_STAGE_CAPTION_MAX_CHARS} 之間"
        )
    return normalized


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


def _validate_int_range(value, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}必須是整數")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}必須是整數") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field}必須是整數")
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{field}必須介於 {minimum} 到 {maximum} 之間")
    return normalized


def validate_board_style(value) -> str:
    style = str(value or "").strip()
    if style not in BOARD_STYLES:
        raise ValueError("看板視窗樣式必須是 glass、slate 或 cue")
    return style


def validate_board_preset(value) -> str:
    preset = str(value or "").strip()
    if preset not in BOARD_PRESETS:
        raise ValueError("看板位置必須是九宮格預設或 custom")
    return preset


def stage_snapshot(config) -> Dict[str, Any]:
    stage = getattr(config, "stage", None)
    caption = getattr(stage, "caption_max_chars", DEFAULT_STAGE_CAPTION_MAX_CHARS)
    return {
        "caption_max_chars": validate_stage_caption_max_chars(caption),
        "caption_x": _validate_int_range(
            getattr(stage, "caption_x", DEFAULT_CAPTION_X),
            field="字幕帶左右位置",
            minimum=0,
            maximum=100,
        ),
        "caption_y": _validate_int_range(
            getattr(stage, "caption_y", DEFAULT_CAPTION_Y),
            field="字幕帶上下位置",
            minimum=0,
            maximum=100,
        ),
        "caption_width": _validate_int_range(
            getattr(stage, "caption_width", DEFAULT_CAPTION_WIDTH),
            field="字幕帶寬度",
            minimum=MIN_CAPTION_WIDTH,
            maximum=100,
        ),
        "board_style": validate_board_style(
            getattr(stage, "board_style", DEFAULT_BOARD_STYLE)
        ),
        "board_width": _validate_int_range(
            getattr(stage, "board_width", DEFAULT_BOARD_WIDTH),
            field="看板寬度",
            minimum=MIN_BOARD_WIDTH,
            maximum=MAX_BOARD_WIDTH,
        ),
        "board_height": _validate_int_range(
            getattr(stage, "board_height", DEFAULT_BOARD_HEIGHT),
            field="看板高度",
            minimum=MIN_BOARD_HEIGHT,
            maximum=MAX_BOARD_HEIGHT,
        ),
        "board_transparency": _validate_int_range(
            getattr(stage, "board_transparency", DEFAULT_BOARD_TRANSPARENCY),
            field="看板背景透明度",
            minimum=0,
            maximum=100,
        ),
        "board_x": _validate_int_range(
            getattr(stage, "board_x", DEFAULT_BOARD_X),
            field="看板左右位置",
            minimum=0,
            maximum=100,
        ),
        "board_y": _validate_int_range(
            getattr(stage, "board_y", DEFAULT_BOARD_Y),
            field="看板上下位置",
            minimum=0,
            maximum=100,
        ),
        "board_preset": validate_board_preset(
            getattr(stage, "board_preset", DEFAULT_BOARD_PRESET)
        ),
        "board_preview": bool(getattr(stage, "board_preview", False)),
        "board_open_x": _validate_int_range(
            getattr(stage, "board_open_x", DEFAULT_BOARD_OPEN_X),
            field="展開看板按鈕左右位置",
            minimum=0,
            maximum=100,
        ),
        "board_open_y": _validate_int_range(
            getattr(stage, "board_open_y", DEFAULT_BOARD_OPEN_Y),
            field="展開看板按鈕上下位置",
            minimum=0,
            maximum=100,
        ),
        "mic_x": _validate_int_range(
            getattr(stage, "mic_x", DEFAULT_MIC_X),
            field="麥克風左右位置",
            minimum=0,
            maximum=100,
        ),
        "mic_y": _validate_int_range(
            getattr(stage, "mic_y", DEFAULT_MIC_Y),
            field="麥克風上下位置",
            minimum=0,
            maximum=100,
        ),
        "mic_preset": validate_board_preset(
            getattr(stage, "mic_preset", DEFAULT_MIC_PRESET)
        ),
    }


def apply_stage_settings(config, params: Dict[str, Any]) -> Dict[str, Any]:
    """更新並持久化數字人舞台顯示設定。"""
    stage = getattr(config, "stage", None)
    if stage is None:
        raise SettingsError("當前配置不支援舞台設定，請更新 config.yaml", status=400)
    payload = params or {}
    try:
        if "caption_max_chars" in payload:
            stage.caption_max_chars = validate_stage_caption_max_chars(
                payload["caption_max_chars"]
            )
        if "caption_x" in payload:
            stage.caption_x = _validate_int_range(
                payload["caption_x"],
                field="字幕帶左右位置",
                minimum=0,
                maximum=100,
            )
        if "caption_y" in payload:
            stage.caption_y = _validate_int_range(
                payload["caption_y"],
                field="字幕帶上下位置",
                minimum=0,
                maximum=100,
            )
        if "caption_width" in payload:
            stage.caption_width = _validate_int_range(
                payload["caption_width"],
                field="字幕帶寬度",
                minimum=MIN_CAPTION_WIDTH,
                maximum=100,
            )
        if "board_style" in payload:
            stage.board_style = validate_board_style(payload["board_style"])
        if "board_width" in payload:
            stage.board_width = _validate_int_range(
                payload["board_width"],
                field="看板寬度",
                minimum=MIN_BOARD_WIDTH,
                maximum=MAX_BOARD_WIDTH,
            )
        if "board_height" in payload:
            stage.board_height = _validate_int_range(
                payload["board_height"],
                field="看板高度",
                minimum=MIN_BOARD_HEIGHT,
                maximum=MAX_BOARD_HEIGHT,
            )
        if "board_transparency" in payload:
            stage.board_transparency = _validate_int_range(
                payload["board_transparency"],
                field="看板背景透明度",
                minimum=0,
                maximum=100,
            )
        if "board_x" in payload:
            stage.board_x = _validate_int_range(
                payload["board_x"],
                field="看板左右位置",
                minimum=0,
                maximum=100,
            )
        if "board_y" in payload:
            stage.board_y = _validate_int_range(
                payload["board_y"],
                field="看板上下位置",
                minimum=0,
                maximum=100,
            )
        if "board_preset" in payload:
            stage.board_preset = validate_board_preset(payload["board_preset"])
        if "board_preview" in payload:
            stage.board_preview = bool(payload["board_preview"])
        if "board_open_x" in payload:
            stage.board_open_x = _validate_int_range(
                payload["board_open_x"],
                field="展開看板按鈕左右位置",
                minimum=0,
                maximum=100,
            )
        if "board_open_y" in payload:
            stage.board_open_y = _validate_int_range(
                payload["board_open_y"],
                field="展開看板按鈕上下位置",
                minimum=0,
                maximum=100,
            )
        if "mic_x" in payload:
            stage.mic_x = _validate_int_range(
                payload["mic_x"],
                field="麥克風左右位置",
                minimum=0,
                maximum=100,
            )
        if "mic_y" in payload:
            stage.mic_y = _validate_int_range(
                payload["mic_y"],
                field="麥克風上下位置",
                minimum=0,
                maximum=100,
            )
        if "mic_preset" in payload:
            stage.mic_preset = validate_board_preset(payload["mic_preset"])
    except ValueError as exc:
        raise SettingsError(str(exc)) from exc
    persist_runtime_overrides(config)
    return stage_snapshot(config)


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


async def _fetch_openai_models(session, base_url: str):
    url = (base_url or "").rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    try:
        async with session.get(f"{url}/models") as resp:
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


def apply_llm_model(
    config,
    model: str,
    provider: str = "",
    system_prompt: Optional[str] = None,
    response_max_chars: Optional[int] = None,
    reply_mode: Optional[str] = None,
    board_max_items: Optional[int] = None,
    assistant_profile: Optional[Dict[str, Any]] = None,
    semantic_wait_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    model = (model or "").strip()
    if not model:
        raise SettingsError("請選擇一個對話模型")
    provider = (provider or resolve_provider(config)).strip().lower()
    if provider not in {"ollama", "llamacpp"}:
        raise SettingsError("不支援的對話後端，請選擇 Ollama 或 llama.cpp")
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
        getattr(config.reply_streaming, "semantic_wait_seconds", 5.0)
        if semantic_wait_seconds is None
        else semantic_wait_seconds
    )
    if not 0.5 <= next_semantic_wait <= 30.0:
        raise SettingsError("語意等待上限必須介於 0.5 至 30 秒")

    previous = f"{resolve_provider(config)}/{config.llm.model}"
    if provider == "llamacpp":
        host = getattr(config.llm, "llamacpp_host", "127.0.0.1") or "127.0.0.1"
        port = int(getattr(config.llm, "llamacpp_port", 8080) or 8080)
        extra_dir = getattr(config.llm, "llamacpp_dir", "") or ""
        try:
            base_url = ensure_server(
                model,
                extra_dir=extra_dir,
                host=host,
                port=port,
                ctx=int(getattr(config.llm, "llamacpp_ctx", 8192) or 8192),
                threads=int(getattr(config.llm, "llamacpp_threads", 0) or 0),
            )
        except Exception as exc:
            raise SettingsError(f"無法啟動 llama.cpp：{exc}", status=500) from exc
        extra_body = {}
        api_key = config.llm.api_key or "llamacpp"
    else:
        base_url = config.llm.base_url
        if "11434" not in (base_url or ""):
            base_url = "http://localhost:11434/v1"
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
        api_key = config.llm.api_key or "ollama"

    config.llm.provider = provider
    config.llm.model = model
    config.llm.base_url = base_url
    config.llm.api_key = api_key
    config.llm.max_tokens = next_max_tokens
    config.llm.response_max_chars = next_response_max_chars
    config.llm.board.max_items = next_board_max_items
    from src.config.schema import AssistantProfileConfig
    if getattr(config.llm, "assistant_profile", None) is None:
        config.llm.assistant_profile = AssistantProfileConfig()
    for key, value in next_profile.items():
        setattr(config.llm.assistant_profile, key, value)
    # Do not write the deprecated field; it remains readable only for migration.
    profile_changed = previous_profile != next_profile
    config.llm.extra_body = extra_body
    config.reply_streaming.enabled = next_reply_mode == "streaming"
    config.reply_streaming.semantic_wait_seconds = next_semantic_wait
    switch_llm_endpoint(
        model=model,
        base_url=base_url,
        extra_body=extra_body,
        api_key=api_key,
        max_tokens=next_max_tokens,
        response_max_chars=next_response_max_chars,
        system_prompt=next_system_prompt,
        reset_history=profile_changed,
    )
    persist_runtime_overrides(config)
    logger.info(f"LLM 已切換: {previous} -> {provider}/{model} @ {base_url}")
    return {
        "model": model,
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


async def fetch_llm_catalog(config) -> Dict[str, Any]:
    extra_dir = getattr(config.llm, "llamacpp_dir", "") or ""
    host = getattr(config.llm, "llamacpp_host", "127.0.0.1") or "127.0.0.1"
    port = int(getattr(config.llm, "llamacpp_port", 8080) or 8080)
    ggufs = list_gguf_models(extra_dir)
    llama_status = server_status(host, port)
    binary = find_llama_server()
    ollama = await fetch_ollama_models(
        config.llm.base_url if "11434" in (config.llm.base_url or "") else "http://localhost:11434/v1"
    )
    return {
        "current": {
            "provider": resolve_provider(config),
            "model": config.llm.model,
            "base_url": config.llm.base_url,
        },
        "providers": {
            "ollama": {
                "id": "ollama",
                "label": "Ollama",
                "reachable": ollama.get("reachable", False),
                "error": ollama.get("error", ""),
                "models": ollama.get("models") or [],
                "base_url": "http://localhost:11434/v1",
            },
            "llamacpp": {
                "id": "llamacpp",
                "label": "llama.cpp",
                "reachable": bool(binary) or bool(ggufs),
                "error": "" if (binary or ggufs) else "找不到 llama-server 或 GGUF 模型",
                "models": ggufs,
                "base_url": openai_base_url(host, port),
                "server_running": llama_status["running"],
                "binary": llama_status["binary"],
            },
        },
    }


def apply_avatar(config, engine: str, avatar_id: str, *, session_count: int) -> Dict[str, Any]:
    engine = (engine or "").strip().lower()
    avatar_id = (avatar_id or "").strip()

    if engine not in ENGINE_META:
        raise SettingsError(f"不支援的數字人引擎: {engine}")
    if not is_safe_avatar_id(avatar_id):
        raise SettingsError("無效的角色 ID")

    characters = list_avatar_characters()
    engines = {item["id"]: item for item in list_engines(characters)}
    engine_info = engines[engine]
    if not engine_info["available"]:
        raise SettingsError(engine_info["message"] or f"{engine} 當前不可用")

    match = next((item for item in characters if item["id"] == avatar_id), None)
    if match is None:
        raise SettingsError(f"找不到角色: {avatar_id}")
    if match["type"] != engine:
        raise SettingsError(f"角色 {avatar_id} 屬於 {match['type']}，與所選引擎不一致")

    from src.server.state import state as server_state

    already_selected = config.model.type == engine and config.model.avatar_id == avatar_id
    if already_selected and getattr(server_state, "model_ready", False) and server_state.model is not None:
        return {
            "type": engine,
            "avatar_id": avatar_id,
            "reloaded": False,
            "type_changed": False,
        }

    if session_count > 0:
        raise SettingsError(
            "請先斷開當前連線，再切換數字人",
            status=409,
            extra={"sessions": session_count, "need_disconnect": True},
        )

    if not _SWITCH_LOCK.acquire(blocking=False):
        raise SettingsError("正在切換數字人，請稍候", status=409)

    try:
        return _reload_avatar(config, engine, avatar_id)
    finally:
        _SWITCH_LOCK.release()


def apply_mouth_quality(config, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist mouth paste-back / character-build quality settings."""
    try:
        quality = apply_quality_to_model(config.model, params or {})
    except QualityError as exc:
        raise SettingsError(str(exc)) from exc
    persist_runtime_overrides(config)
    return quality


def _reload_avatar(config, engine: str, avatar_id: str) -> Dict[str, Any]:
    from copy import deepcopy

    from src.avatars.factory import load_avatar_data, prepare_avatar_model
    from src.server.state import state

    type_changed = config.model.type != engine or state.model is None
    previous = f"{config.model.type}/{config.model.avatar_id}"
    pending = deepcopy(config)
    apply_engine_paths(pending, engine, avatar_id)
    pending.model.type = engine
    pending.model.avatar_id = avatar_id

    state.switching = True
    try:
        if type_changed:
            new_model, new_avatar = prepare_avatar_model(pending)
        else:
            new_model, new_avatar = state.model, load_avatar_data(pending)

        old_model, old_avatar = state.model, state.avatar
        state.model = new_model
        state.avatar = new_avatar
        state.model_ready = state.model is not None and state.avatar is not None
        apply_engine_paths(config, engine, avatar_id)
        config.model.type = engine
        config.model.avatar_id = avatar_id
        persist_runtime_overrides(config)

        if type_changed and old_model is not new_model:
            del old_model, old_avatar
            _release_gpu_resources(clear_state=False)

        logger.info(f"數字人已切換: {previous} -> {engine}/{avatar_id}")
        return {
            "type": engine,
            "avatar_id": avatar_id,
            "reloaded": True,
            "type_changed": type_changed,
        }
    except SettingsError:
        raise
    except Exception as exc:
        logger.exception("切換數字人失敗")
        raise SettingsError(f"切換數字人失敗: {exc}", status=500) from exc
    finally:
        state.switching = False


def _release_gpu_resources(*, clear_state: bool = True) -> None:
    from src.server.state import state

    if clear_state:
        state.model = None
        state.avatar = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# --------------------------------------------------------------------- VAD

VAD_ENGINE_META = {
    "silero": {
        "label": "Silero VAD",
        "package": "silero-vad",
        "module": "silero_vad",
        "install": 'uv pip install "silero-vad>=5.1"',
        "description": "神經網路，抗噪更好，適合真實麥克風",
    },
}

# 前端可調的 VAD 數值引數與取值範圍
VAD_RANGES = {
    "threshold": (0.1, 0.95),
    "aggressiveness": (0, 3),
    "min_speech_ms": (50, 2000),
    "min_silence_ms": (100, 3000),
    "speech_pad_ms": (0, 1000),
}


def _module_installed(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


def list_vad_engines() -> list:
    """The microphone endpoint detector is intentionally Silero-only."""
    return [
        {
            "id": engine_id,
            "label": meta["label"],
            "description": meta.get("description", ""),
            "package": meta["package"],
            "install": meta["install"],
            "available": _module_installed(meta["module"]),
        }
        for engine_id, meta in VAD_ENGINE_META.items()
    ]


def vad_snapshot(config) -> Dict[str, Any]:
    """VAD 當前配置 + 是否真的會生效（瀏覽器識別時服務端拿不到音訊）"""
    vad = getattr(config, "vad", None)
    asr_mode = "server"
    if vad is None:
        return {"supported": False, "engines": list_vad_engines(), "asr_mode": asr_mode}

    return {
        "supported": True,
        "enabled": bool(vad.enabled),
        "type": vad.type,
        "threshold": float(vad.threshold),
        "aggressiveness": int(vad.aggressiveness),
        "min_speech_ms": int(vad.min_speech_ms),
        "min_silence_ms": int(vad.min_silence_ms),
        "speech_pad_ms": int(vad.speech_pad_ms),
        "sample_rate": int(vad.sample_rate),
        "engines": list_vad_engines(),
        "asr_mode": asr_mode,
        # 只有音訊送到後端（服務端識別）時，服務端 VAD 才有音訊可分析
        "effective": bool(vad.enabled),
    }


def _clamp_number(name: str, value, current):
    low, high = VAD_RANGES[name]
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SettingsError(f"{name} 需要是數字")
    number = max(low, min(high, number))
    return number if isinstance(current, float) else int(round(number))


def apply_vad_settings(config, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    應用 Silero VAD 開關、閾值與端點引數，並立即重建、預熱引擎。
    """
    vad = getattr(config, "vad", None)
    if vad is None:
        raise SettingsError("當前配置不支援 VAD，請更新 config.yaml", status=400)

    requested_type = str(params.get("type", "silero") or "silero").strip().lower()
    if requested_type != "silero":
        raise SettingsError("VAD 固定使用 Silero；WebRTC 只負責音訊傳輸")
    engine_type = "silero"

    enabled = bool(params.get("enabled", vad.enabled))
    if enabled and not _module_installed(VAD_ENGINE_META[engine_type]["module"]):
        meta = VAD_ENGINE_META[engine_type]
        raise SettingsError(
            f"{meta['label']} 依賴未安裝，請先執行：{meta['install']}",
            extra={"missing_package": meta["package"]},
        )

    previous = f"{vad.type}({'on' if vad.enabled else 'off'})"

    vad.type = engine_type
    vad.enabled = enabled
    for name in VAD_RANGES:
        if name in params and params[name] is not None:
            setattr(vad, name, _clamp_number(name, params[name], getattr(vad, name)))
    config.asr.mode = "server"

    # 引擎引數變了就重建單例；順手預熱，避免第一次識別時才報缺依賴
    warmup_error = ""
    from src.vad import get_vad_engine_from_config, release_vad_engine

    release_vad_engine()
    if enabled:
        try:
            get_vad_engine_from_config(vad, config=config).ensure_ready()
        except Exception as exc:
            warmup_error = str(exc)
            logger.warning(f"[VAD] 預熱 {engine_type} 失敗: {exc}")

    persist_runtime_overrides(config)
    logger.info(f"VAD 已更新: {previous} -> {vad.type}({'on' if vad.enabled else 'off'})")

    snapshot = vad_snapshot(config)
    snapshot["warmup_error"] = warmup_error
    return snapshot


# --------------------------------------------------------------------- STT / TTS

STT_ENGINE_META = {
    "whisper": {
        "label": "faster-whisper",
        "module": "faster_whisper",
        "install": 'uv pip install "faster-whisper>=1.1"',
        "description": "CTranslate2 Whisper，GPU FP16 / CPU INT8",
    },
    "funasr": {
        "label": "FunASR",
        "module": "funasr",
        "install": "uv sync --extra funasr",
        "description": "paraformer-zh，中文優先",
    },
}
STT_OUTPUT_SCRIPTS = ("traditional-tw", "simplified")

TTS_ENGINE_META = {
    "edgetts": {
        "label": "Edge TTS",
        "module": "edge_tts",
        "description": "免金鑰雲端語音；預設繁體中文女聲",
        "setup": "",
    },
    "gpt-sovits": {
        "label": "GPT-SoVITS",
        "module": "requests",
        "description": "連線本機或內網 GPT-SoVITS 服務",
        "setup": "需要可連線的本地服務與參考音訊",
    },
    "xtts": {
        "label": "XTTS",
        "module": "requests",
        "description": "連線本機或內網 XTTS 服務",
        "setup": "需要可連線的本地服務與參考音訊",
    },
    "cosyvoice": {
        "label": "CosyVoice 2",
        "module": "requests",
        "description": "本機 CosyVoice2-0.5B；套用時自動啟動獨立 GPU 服務",
        "setup": "需要 conda 環境 cosyvoice、CosyVoice2-0.5B 與參考音訊",
    },
    "fun-cosyvoice3": {
        "label": "Fun-CosyVoice 3.0",
        "module": "requests",
        "description": "本機 Fun-CosyVoice3-0.5B；九語加方言，套用時自動啟動獨立 GPU 服務",
        "setup": "需要 conda 環境 cosyvoice、Fun-CosyVoice3-0.5B 與參考音訊",
    },
    "fishtts": {
        "label": "Fish Speech",
        "module": "requests",
        "description": "連線本機或內網 Fish Speech 服務",
        "setup": "需要可連線的本地服務",
    },
    "indextts2": {
        "label": "IndexTTS2",
        "module": "gradio_client",
        "description": "連線本機或內網 IndexTTS2 Gradio 服務",
        "setup": "需要 gradio_client、本地服務與參考音訊",
    },
}

STT_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")
STT_MODELS_BY_ENGINE = {
    "whisper": STT_MODEL_SIZES,
    "funasr": ("paraformer-zh",),
}
STT_LANGUAGES = ("zh", "en", "auto")
STT_DEVICES = ("auto", "cpu", "cuda")
EDGE_TTS_ZH_TW_VOICES = (
    {"id": "zh-TW-HsiaoChenNeural", "name": "HsiaoChen", "gender": "female"},
    {"id": "zh-TW-HsiaoYuNeural", "name": "HsiaoYu", "gender": "female"},
    {"id": "zh-TW-YunJheNeural", "name": "YunJhe", "gender": "male"},
)
EDGE_TTS_ZH_TW_VOICE_IDS = frozenset(
    voice["id"] for voice in EDGE_TTS_ZH_TW_VOICES
)


def _engine_available(item: Dict[str, str]) -> bool:
    return _module_installed(item["module"])


def _catalog(meta: Dict[str, Dict[str, str]]) -> list:
    items = []
    for engine_id, item in meta.items():
        available = _engine_available(item)
        items.append({
            "id": engine_id,
            "label": item["label"],
            "description": item.get("description", ""),
            "setup": item.get("setup", ""),
            "available": available,
            "message": "" if available else f"缺少依賴：{item['module']}",
            "install": item.get("install", ""),
        })
    return items


def speech_snapshot(config) -> Dict[str, Any]:
    asr = config.asr
    tts = config.tts
    return {
        "stt": {
            "type": asr.type,
            "model_size": asr.model_size,
            "language": asr.language,
            "output_script": getattr(asr, "output_script", "traditional-tw"),
            "device": asr.device,
            "mode": "server",
            "local_model_ready": local_funasr_model_ready(),
            "engines": _catalog(STT_ENGINE_META),
            "model_sizes": list(STT_MODEL_SIZES),
            "models_by_engine": {
                key: list(values) for key, values in STT_MODELS_BY_ENGINE.items()
            },
            "languages": list(STT_LANGUAGES),
            "devices": list(STT_DEVICES),
        },
        "tts": {
            "type": tts.type,
            "mode": getattr(tts, "mode", "auto"),
            "ref_file": tts.ref_file,
            "ref_text": tts.ref_text or "",
            "tts_server": tts.tts_server,
            "model": tts.model,
            "language": (
                normalize_language(
                    tts.language,
                    family=cosyvoice_family(tts.type),
                )
                if is_cosyvoice_engine(tts.type)
                else tts.language
            ),
            "speaker": tts.speaker,
            "instruct": tts.instruct,
            "device": tts.device,
            "engines": _catalog(TTS_ENGINE_META),
            "models": [],
            "languages": [
                {"id": item_id, "label": label}
                for item_id, label in languages_for_family(
                    cosyvoice_family(tts.type)
                )
            ],
            "speakers": [],
            "edge_voices": [dict(voice) for voice in EDGE_TTS_ZH_TW_VOICES],
            "devices": list(STT_DEVICES),
        },
    }


def _require_no_sessions(session_count: int) -> None:
    if session_count:
        raise SettingsError(
            "請先斷開當前連線，再套用語音引擎",
            status=409,
            extra={"sessions": session_count, "need_disconnect": True},
        )


def apply_stt_settings(config, params: Dict[str, Any], *, session_count: int) -> Dict[str, Any]:
    """Validate and prewarm a keyless STT engine before committing it."""
    from copy import deepcopy

    _require_no_sessions(session_count)
    engine = str(params.get("type", config.asr.type)).strip().lower()
    model_size = str(params.get("model_size", config.asr.model_size)).strip()
    language = str(params.get("language", config.asr.language)).strip().lower()
    output_script = str(
        params.get(
            "output_script",
            getattr(config.asr, "output_script", "traditional-tw"),
        )
    ).strip().lower()
    device = str(params.get("device", config.asr.device)).strip().lower()
    if engine not in STT_ENGINE_META:
        raise SettingsError(f"不支援的 STT 引擎: {engine}")
    if not _engine_available(STT_ENGINE_META[engine]):
        raise SettingsError(
            f"{STT_ENGINE_META[engine]['label']} 依賴未安裝",
            extra={"missing_package": STT_ENGINE_META[engine]["module"]},
        )
    if engine == "whisper" and model_size not in STT_MODEL_SIZES:
        raise SettingsError(f"不支援的 faster-whisper 模型: {model_size}")
    if language not in STT_LANGUAGES:
        raise SettingsError(f"不支援的識別語言: {language}")
    if output_script not in STT_OUTPUT_SCRIPTS:
        raise SettingsError(f"不支援的 FunASR 輸出文字: {output_script}")
    if device not in STT_DEVICES:
        raise SettingsError(f"不支援的運算裝置: {device}")

    pending = deepcopy(config)
    pending.asr.mode = "server"
    pending.asr.type = engine
    pending.asr.model_size = model_size
    pending.asr.language = language
    pending.asr.output_script = output_script
    pending.asr.device = device
    candidate = create_asr_engine(engine, config=pending, model_size=model_size)
    candidate.set_language(language)
    try:
        candidate.ensure_ready()
    except Exception as exc:
        raise SettingsError(f"STT 預熱失敗: {exc}", status=500) from exc

    config.asr.mode = "server"
    config.asr.type = engine
    config.asr.model_size = model_size
    config.asr.language = language
    config.asr.output_script = output_script
    config.asr.device = device
    candidate.config = config
    activate_asr_engine(
        candidate,
        asr_type=engine,
        model_size=model_size,
        config=config,
    )
    persist_runtime_overrides(config)
    return speech_snapshot(config)["stt"]


def apply_tts_settings(config, params: Dict[str, Any], *, session_count: int) -> Dict[str, Any]:
    """Validate reference/connectivity and synthesize a short preview before commit."""
    _require_no_sessions(session_count)
    engine = str(params.get("type", config.tts.type)).strip().lower()
    if engine not in TTS_ENGINE_META:
        raise SettingsError(f"不支援的 TTS 引擎: {engine}")
    meta = TTS_ENGINE_META[engine]
    if not _engine_available(meta):
        raise SettingsError(
            f"{meta['label']} 依賴未安裝",
            extra={"missing_package": meta["module"]},
        )
    ref_file = str(params.get("ref_file", config.tts.ref_file) or "").strip()
    ref_text = str(params.get("ref_text", config.tts.ref_text) or "").strip()
    tts_server = str(params.get("tts_server", config.tts.tts_server) or "").strip()
    model = str(params.get("model", config.tts.model) or "").strip()
    mode = str(params.get("mode", getattr(config.tts, "mode", "auto")) or "auto").strip().lower()
    language = str(params.get("language", config.tts.language) or "Auto").strip()
    speaker = str(params.get("speaker", config.tts.speaker) or "").strip()
    instruct = str(params.get("instruct", config.tts.instruct) or "").strip()
    device = str(params.get("device", config.tts.device) or "auto").strip().lower()
    if engine == "edgetts" and ref_file not in EDGE_TTS_ZH_TW_VOICE_IDS:
        raise SettingsError("請選擇可用的 Edge TTS 台灣華語聲線")
    if is_cosyvoice_engine(engine):
        from src.tts.cosyvoice_runtime import (
            DEFAULT_PROMPT_TEXT,
            DEFAULT_PROMPT_WAV,
            ensure_server,
            parse_server_url,
            prepare_prompt_wav,
            resolve_prompt_source,
        )

        family = cosyvoice_family(engine)
        language = normalize_language(language, family=family)

        if not tts_server:
            tts_server = "http://127.0.0.1:50000"
        if ref_file in EDGE_TTS_ZH_TW_VOICE_IDS:
            ref_file = ""

        if mode == "zero_shot" and ref_file and not ref_text:
            raise SettingsError(
                "Zero-shot 需要填寫「參考語音逐字稿」，且內容必須與選取的參考音檔實際語句一致。"
            )

        if ref_file:
            try:
                source = resolve_prompt_source(ref_file)
            except FileNotFoundError:
                raise SettingsError(
                    f"參考音訊不存在：{ref_file}。"
                    "請填完整路徑，例如 /home/oliver/CosyVoice/asset/SHINeeJonghyun.mp3"
                ) from None
            try:
                ref_file = str(prepare_prompt_wav(source))
            except Exception as exc:
                raise SettingsError(
                    f"無法把參考音訊轉成 CosyVoice 可用的 WAV：{source}。"
                    "請使用可播放的 WAV 或 MP3。"
                ) from exc
        else:
            if not DEFAULT_PROMPT_WAV.is_file():
                raise SettingsError(
                    "未填參考音訊，且預設 data/tts/cosyvoice_prompt.wav 也不存在。"
                )
            ref_file = str(DEFAULT_PROMPT_WAV)
            if not ref_text:
                ref_text = DEFAULT_PROMPT_TEXT
        if mode == "zero_shot" and not ref_text:
            raise SettingsError(
                "Zero-shot 需要填寫「參考語音逐字稿」，且內容必須與選取的參考音檔實際語句一致。"
            )
        host, port = parse_server_url(tts_server)
        try:
            tts_server = ensure_server(
                model_dir=model,
                family=family,
                host=host,
                port=port,
            )
        except FileNotFoundError as exc:
            raise SettingsError(str(exc)) from exc
    elif engine != "edgetts" and not tts_server:
        raise SettingsError("本地 TTS 必須填寫服務地址")

    preview_audio = _preview_tts(
        config,
        engine=engine,
        ref_file=ref_file,
        ref_text=ref_text,
        tts_server=tts_server,
        model=model,
        mode=mode,
        language=language,
        speaker=speaker,
        instruct=instruct,
        device=device,
    )

    config.tts.type = engine
    config.tts.ref_file = ref_file
    config.tts.ref_text = ref_text or None
    config.tts.tts_server = tts_server
    config.tts.model = model
    config.tts.mode = mode
    config.tts.language = language
    config.tts.speaker = speaker
    config.tts.instruct = instruct
    config.tts.device = device
    persist_runtime_overrides(config)
    result = speech_snapshot(config)["tts"]
    result["preview_audio"] = preview_audio
    return result


def _preview_tts(
    config,
    *,
    engine: str,
    ref_file: str,
    ref_text: str,
    tts_server: str,
    model: str,
    mode: str,
    language: str,
    speaker: str,
    instruct: str,
    device: str,
) -> str:
    """Run the real engine against a bounded phrase and return a WAV data URI."""
    if engine in {"gpt-sovits", "xtts", "cosyvoice", "fun-cosyvoice3", "indextts2"}:
        audio_path = Path(ref_file).expanduser() if ref_file else None
        if audio_path is None or not audio_path.is_file():
            shown = ref_file or "（未填寫）"
            raise SettingsError(
                f"參考音訊不存在：{shown}。"
                "請填寫本機 WAV／MP3 的完整路徑，不能使用 Edge 聲線名稱"
                "（例如 zh-TW-HsiaoChenNeural）。"
            )

    pending = deepcopy(config)
    pending.tts.type = engine
    pending.tts.ref_file = ref_file
    pending.tts.ref_text = ref_text or None
    pending.tts.tts_server = tts_server
    pending.tts.model = model
    pending.tts.mode = mode
    pending.tts.language = language
    pending.tts.speaker = speaker
    pending.tts.instruct = instruct
    pending.tts.device = device

    class PreviewSink:
        def __init__(self):
            self.frames = []

        def put_audio_frame(self, audio_chunk, datainfo=None):
            if sum(len(item) for item in self.frames) < 16000 * 5:
                self.frames.append(np.asarray(audio_chunk, dtype=np.float32))

    import numpy as np
    from src.tts.factory import create_tts_engine

    sink = PreviewSink()
    try:
        candidate = create_tts_engine(engine, pending, sink)
        candidate.txt_to_audio(("語音設定完成", {"preview": True}))
    except Exception as exc:
        raise SettingsError(f"TTS 連線或試聽失敗: {exc}", status=502) from exc
    if not sink.frames:
        raise SettingsError("TTS 試聽沒有產生音訊，請檢查服務與參考資料", status=502)
    audio = np.concatenate(sink.frames)[: 16000 * 5]
    wav = BytesIO()
    import soundfile as sf

    sf.write(wav, audio, 16000, format="WAV", subtype="PCM_16")
    return "data:audio/wav;base64," + base64.b64encode(wav.getvalue()).decode("ascii")
