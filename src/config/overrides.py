# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""設定面板寫入的執行時覆蓋，啟動時疊在主配置之上。"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Dict

import yaml

from src.utils.logging import logger
from src.utils.paths import get_config_dir

RUNTIME_OVERRIDES_FILE = get_config_dir() / "runtime_overrides.yaml"


def load_runtime_overrides() -> Dict[str, Any]:
    if not RUNTIME_OVERRIDES_FILE.exists():
        return {}
    try:
        data = yaml.safe_load(RUNTIME_OVERRIDES_FILE.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"讀取 runtime_overrides.yaml 失敗: {exc}")
        return {}


def persist_runtime_overrides(config) -> None:
    # Loading a YAML configuration is also used by offline release checks. Keep
    # OpenCV-dependent avatar quality code on the write path, where it is
    # actually needed, rather than making every configuration read import it.
    from src.avatars.mouth_quality import quality_from_model
    from src.llm.rules import rules_from_config

    payload = {
        "llm": {
            "model": config.llm.model,
            "provider": getattr(config.llm, "provider", "ollama"),
            "base_url": getattr(config.llm, "base_url", ""),
            "api_key": getattr(config.llm, "api_key", ""),
            "max_tokens": getattr(config.llm, "max_tokens", 128),
            "response_max_chars": getattr(config.llm, "response_max_chars", 120),
            "assistant_profile": {
                "assistant_name": str(getattr(getattr(config.llm, "assistant_profile", None), "assistant_name", "") or ""),
                "system_prompt": str(getattr(getattr(config.llm, "assistant_profile", None), "system_prompt", "") or ""),
                "restriction_prompt": str(getattr(getattr(config.llm, "assistant_profile", None), "restriction_prompt", "") or ""),
                "output_locale": str(getattr(getattr(config.llm, "assistant_profile", None), "output_locale", "zh-TW") or "zh-TW"),
                "enforce_output_locale": bool(getattr(getattr(config.llm, "assistant_profile", None), "enforce_output_locale", True)),
                "forbidden_self_names": list(getattr(getattr(config.llm, "assistant_profile", None), "forbidden_self_names", []) or []),
            },
            "extra_body": getattr(config.llm, "extra_body", {}) or {},
            "board": {
                "max_items": int(
                    getattr(getattr(config.llm, "board", None), "max_items", 8)
                ),
            },
            "reply_rules": rules_from_config(config),
        },
        "model": {
            "type": config.model.type,
            "avatar_id": config.model.avatar_id,
            **quality_from_model(config.model),
        },
        "reply_streaming": {
            "enabled": bool(
                getattr(getattr(config, "reply_streaming", None), "enabled", False)
            ),
            "decoupled_audio_clock": bool(
                getattr(
                    getattr(config, "reply_streaming", None),
                    "decoupled_audio_clock",
                    False,
                )
            ),
            "strong_min_chars": int(
                getattr(
                    getattr(config, "reply_streaming", None),
                    "strong_min_chars",
                    1,
                )
            ),
        },
        "stage": {
            "caption_max_chars": int(
                getattr(getattr(config, "stage", None), "caption_max_chars", 120)
            ),
            "caption_x": int(
                getattr(getattr(config, "stage", None), "caption_x", 50)
            ),
            "caption_y": int(
                getattr(getattr(config, "stage", None), "caption_y", 90)
            ),
            "caption_width": int(
                getattr(getattr(config, "stage", None), "caption_width", 100)
            ),
            "board_style": str(
                getattr(getattr(config, "stage", None), "board_style", "glass")
            ),
            "board_width": int(
                getattr(getattr(config, "stage", None), "board_width", 252)
            ),
            "board_height": int(
                getattr(getattr(config, "stage", None), "board_height", 300)
            ),
            "board_transparency": int(
                getattr(getattr(config, "stage", None), "board_transparency", 28)
            ),
            "board_x": int(getattr(getattr(config, "stage", None), "board_x", 100)),
            "board_y": int(getattr(getattr(config, "stage", None), "board_y", 0)),
            "board_preset": str(
                getattr(getattr(config, "stage", None), "board_preset", "tr")
            ),
            "board_preview": False,
            "board_open_x": int(
                getattr(getattr(config, "stage", None), "board_open_x", 50)
            ),
            "board_open_y": int(
                getattr(getattr(config, "stage", None), "board_open_y", 8)
            ),
            "mic_x": int(getattr(getattr(config, "stage", None), "mic_x", 50)),
            "mic_y": int(getattr(getattr(config, "stage", None), "mic_y", 62)),
            "mic_preset": str(
                getattr(getattr(config, "stage", None), "mic_preset", "custom")
            ),
        },
    }

    vad = getattr(config, "vad", None)
    if vad is not None:
        payload["vad"] = {
            "enabled": bool(vad.enabled),
            "type": vad.type,
            "threshold": float(vad.threshold),
            "aggressiveness": int(vad.aggressiveness),
            "min_speech_ms": int(vad.min_speech_ms),
            "min_silence_ms": int(vad.min_silence_ms),
            "speech_pad_ms": int(vad.speech_pad_ms),
        }

    asr = getattr(config, "asr", None)
    if asr is not None:
        payload["asr"] = {
            "mode": "server",
            "type": asr.type,
            "model_size": asr.model_size,
            "language": asr.language,
            "output_script": getattr(asr, "output_script", "traditional-tw"),
            "device": asr.device,
        }
    tts = getattr(config, "tts", None)
    if tts is not None:
        payload["tts"] = {
            "type": tts.type,
            "mode": getattr(tts, "mode", "auto"),
            "ref_file": tts.ref_file,
            "ref_text": tts.ref_text,
            "tts_server": tts.tts_server,
            "model": tts.model,
            "language": tts.language,
            "speaker": tts.speaker,
            "instruct": tts.instruct,
            "device": tts.device,
        }
    RUNTIME_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# 由設定面板自動生成，請勿手改關鍵結構。\n"
        "# 會在啟動時覆蓋主配置中的 llm（含 reply_rules）/ model / reply_streaming / vad / asr / tts。\n"
    )
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    # Write and replace in the same directory so a process restart sees either
    # the previous complete file or the new complete file, never half YAML.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=RUNTIME_OVERRIDES_FILE.parent,
            prefix=f".{RUNTIME_OVERRIDES_FILE.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(header + text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, RUNTIME_OVERRIDES_FILE)
    except Exception:
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                pass
        raise
