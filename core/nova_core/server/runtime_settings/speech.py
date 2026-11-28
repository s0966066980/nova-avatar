# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""執行時設定：語音辨識（STT）、語音活動偵測（VAD）與語音合成（TTS）目錄、套用與試聽。"""
from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, Dict
from nova_contracts.common import ServiceError
from nova_contracts.stt import SttEngineSettings, SttService
from nova_contracts.tts import (
    FragmentEnvelope,
    PlayableFragment,
    SynthesisRequest,
    TtsError,
    TtsService,
    TtsVoice,
    VoicePreparation,
)
from nova_tts import config_section as tts_section
from nova_core.utils.logging import logger
from nova_core.server.runtime_settings import shared
from nova_core.server.runtime_settings.shared import SettingsError


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
    from nova_core.vad import get_vad_engine_from_config, release_vad_engine

    release_vad_engine()
    if enabled:
        try:
            get_vad_engine_from_config(vad, config=config).ensure_ready()
        except Exception as exc:
            warmup_error = str(exc)
            logger.warning(f"[VAD] 預熱 {engine_type} 失敗: {exc}")

    shared.persist_runtime_overrides(config)
    logger.info(f"VAD 已更新: {previous} -> {vad.type}({'on' if vad.enabled else 'off'})")

    snapshot = vad_snapshot(config)
    snapshot["warmup_error"] = warmup_error
    return snapshot


STT_ENGINE_META = {
    "whisper": {
        "label": "faster-whisper",
        "module": "faster_whisper",
        "install": 'uv pip install "faster-whisper>=1.1"',
        "description": "CTranslate2 Whisper，GPU FP16 / CPU INT8",
    },
}


# The TTS engines are described by the TTS layer (nova_tts.config_section.ENGINE_META).
TTS_ENGINE_META = tts_section.ENGINE_META


STT_MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3", "turbo")


STT_MODELS_BY_ENGINE = {
    "whisper": STT_MODEL_SIZES,
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


MATCHA_VOICE_MODEL_REQUIRED = "Matcha 需要選擇聲線模型（models/tts 中附使用限制標示的聲線模型）"


def _engine_unavailable_reason(item: Dict[str, str]) -> str:
    return "" if _module_installed(item["module"]) else f"缺少依賴：{item['module']}"


def _engine_available(item: Dict[str, str]) -> bool:
    return not _engine_unavailable_reason(item)


def _catalog(meta: Dict[str, Dict[str, str]]) -> list:
    items = []
    for engine_id, item in meta.items():
        reason = _engine_unavailable_reason(item)
        items.append({
            "id": engine_id,
            "label": item["label"],
            "description": item.get("description", ""),
            "setup": item.get("setup", ""),
            "voice_source": item.get("voice_source", ""),
            "starts_service": bool(item.get("starts_service", False)),
            "available": not reason,
            "message": reason,
            "install": item.get("install", ""),
        })
    return items


def _stt_catalog() -> list:
    """STT engines with what the console form needs to render each of them."""
    items = _catalog(STT_ENGINE_META)
    for item in items:
        item["models"] = list(STT_MODELS_BY_ENGINE.get(item["id"], ()))
    return items


def stt_snapshot(config) -> Dict[str, Any]:
    asr = config.asr
    return {
        "type": asr.type,
        "model_size": asr.model_size,
        "language": asr.language,
        "device": asr.device,
        "mode": "server",
        "engines": _stt_catalog(),
        "model_sizes": list(STT_MODEL_SIZES),
        "models_by_engine": {
            key: list(values) for key, values in STT_MODELS_BY_ENGINE.items()
        },
        "languages": list(STT_LANGUAGES),
        "devices": list(STT_DEVICES),
    }


def speech_snapshot(config, *, tts: TtsService) -> Dict[str, Any]:
    catalog = tts.catalog()
    return {
        "stt": stt_snapshot(config),
        # Only what a role profile's voice is chosen from: the default voice
        # is the main role's, so there is no global voice to report.
        "tts": {
            "engines": _catalog(TTS_ENGINE_META),
            # Reference audio and models are chosen from these server-side lists.
            "voices": [voice.model_dump(mode="json") for voice in catalog.voices],
            "models": [model.model_dump(mode="json") for model in catalog.models],
            "edge_voices": [dict(voice) for voice in EDGE_TTS_ZH_TW_VOICES],
            "edge_english_voices": [dict(voice) for voice in tts_section.EDGE_ENGLISH_VOICES],
            # Matcha voice models with their usage labels; profiles name one by ID.
            "voice_models": [model.model_dump(mode="json") for model in catalog.voice_models],
            # Saved settings that named a removed engine and now use Edge TTS.
            "notice": tts_section.removed_engine_notice(),
        },
    }


def _require_no_sessions(session_count: int) -> None:
    if session_count:
        raise SettingsError(
            "請先斷開當前連線，再套用語音引擎",
            status=409,
            extra={"sessions": session_count, "need_disconnect": True},
        )


def apply_stt_settings(
    config, params: Dict[str, Any], *, session_count: int, stt: SttService,
) -> Dict[str, Any]:
    """Validate a keyless STT engine and have the STT service load it before committing it."""
    _require_no_sessions(session_count)
    engine = str(params.get("type", config.asr.type)).strip().lower()
    model_size = str(params.get("model_size", config.asr.model_size)).strip()
    language = str(params.get("language", config.asr.language)).strip().lower()
    device = str(params.get("device", config.asr.device)).strip().lower()
    if engine not in STT_ENGINE_META:
        raise SettingsError(f"不支援的 STT 引擎: {engine}")
    unavailable = _engine_unavailable_reason(STT_ENGINE_META[engine])
    if unavailable:
        raise SettingsError(
            f"{STT_ENGINE_META[engine]['label']} 無法使用：{unavailable}",
            extra={"missing_package": STT_ENGINE_META[engine]["module"]},
        )
    if model_size not in STT_MODELS_BY_ENGINE[engine]:
        raise SettingsError(f"不支援的 {STT_ENGINE_META[engine]['label']} 模型: {model_size}")
    if language not in STT_LANGUAGES:
        raise SettingsError(f"不支援的識別語言: {language}")
    if device not in STT_DEVICES:
        raise SettingsError(f"不支援的運算裝置: {device}")

    try:
        stt.apply_engine(SttEngineSettings(engine=engine, model_size=model_size, device=device))
    except ServiceError as exc:
        raise SettingsError(f"STT 預熱失敗: {exc}", status=500) from exc

    config.asr.mode = "server"
    config.asr.type = engine
    config.asr.model_size = model_size
    config.asr.language = language
    config.asr.device = device
    shared.persist_runtime_overrides(config)
    return stt_snapshot(config)


def validate_tts_sources(config, params: Dict[str, Any]) -> Dict[str, str]:
    """Check the TTS fields that name files, models or servers.

    ``ref_file`` must be a voice-library ID, a voice-model ID (Matcha; apply
    and preview also require it to be installed) or an Edge voice name,
    ``model`` a ``models/`` catalog ID and ``tts_server`` a loopback address.
    Runs before a request is applied or saved for later.
    """
    if not isinstance(params, dict):
        raise SettingsError("設定格式不正確")
    engine = str(params.get("type", config.tts.type)).strip().lower()
    if engine not in TTS_ENGINE_META:
        raise SettingsError(f"不支援的 TTS 引擎: {engine}")
    values = {
        key: params.get(key, getattr(config.tts, key))
        for key in ("ref_file", "tts_server", "model")
    }
    for key, value in values.items():
        if value is not None and not isinstance(value, str):
            raise SettingsError(f"{key} 格式不正確")
        values[key] = (value or "").strip()
    if engine == "breezyvoice" and values["ref_file"] in EDGE_TTS_ZH_TW_VOICE_IDS:
        values["ref_file"] = ""
    try:
        values = tts_section.check_voice_values(engine, values["ref_file"], values["tts_server"], values["model"])
    except ValueError as exc:
        raise SettingsError(str(exc)) from None
    return {"type": engine, **values}


def _require_matcha_voice_model(ref_file: str) -> None:
    """Before a Matcha apply or preview: a voice model is chosen and installed now."""
    if not ref_file:
        raise SettingsError(MATCHA_VOICE_MODEL_REQUIRED)
    try:
        tts_section.check_voice_model_installed(ref_file)
    except ValueError as exc:
        raise SettingsError(str(exc)) from None


def _voice(config, *, engine: str, ref_file: str, tts_server: str, model: str) -> TtsVoice:
    """``config``'s voice with the given engine and sources (the Edge options stay)."""
    return tts_section.voice(config.tts).model_copy(update={
        "engine": engine, "voice": ref_file, "server": tts_server, "model": model})


def apply_tts_settings(
    config, params: Dict[str, Any], *, session_count: int, tts: TtsService,
) -> Dict[str, Any]:
    """Validate reference/connectivity and synthesize a short preview before commit."""
    _require_no_sessions(session_count)
    sources = validate_tts_sources(config, params)
    engine = sources["type"]
    meta = TTS_ENGINE_META[engine]
    if not _engine_available(meta):
        raise SettingsError(
            f"{meta['label']} 依賴未安裝",
            extra={"missing_package": meta["module"]},
        )
    ref_file = sources["ref_file"]
    tts_server = sources["tts_server"]
    model = sources["model"]
    if engine == "edgetts":
        if ref_file not in EDGE_TTS_ZH_TW_VOICE_IDS:
            raise SettingsError("請選擇可用的 Edge TTS 台灣華語聲線")
        tts_server, model = "", ""
    elif engine == "matcha":
        _require_matcha_voice_model(ref_file)
        tts_server, model = "", ""
    else:
        # BreezyVoice only clones from a reference recording and its transcript.
        if not ref_file:
            raise SettingsError("BreezyVoice 需要從音訊庫選擇參考音訊（自錄或有書面授權的台灣華語錄音）")
        if not tts_section.voice_transcript(ref_file):
            raise SettingsError("BreezyVoice 需要附逐字稿的參考音訊，請在音訊庫重新上傳並填寫逐字稿")
        voice = _voice(config, engine=engine, ref_file=ref_file, tts_server=tts_server, model=model)
        try:
            tts_server = tts.prepare_voice(VoicePreparation(voice=voice)).server
        except TtsError as exc:
            raise SettingsError(exc.message, status=exc.status) from exc

    preview_audio = _preview_tts(
        config,
        engine=engine,
        ref_file=ref_file,
        tts_server=tts_server,
        model=model,
        tts=tts,
    )

    config.tts.type = engine
    config.tts.ref_file = ref_file
    config.tts.ref_text = None
    config.tts.tts_server = tts_server
    config.tts.model = model
    shared.persist_runtime_overrides(config)
    tts_section.clear_removed_engine_notice()
    result = speech_snapshot(config, tts=tts)["tts"]
    result["preview_audio"] = preview_audio
    return result


def _preview_tts(
    config,
    *,
    engine: str,
    ref_file: str,
    tts_server: str,
    model: str,
    tts: TtsService,
    text: str = "語音設定完成",
) -> str:
    """Have the TTS layer speak a bounded phrase in the voice; a WAV data URI."""
    import numpy as np
    import soundfile as sf

    request = SynthesisRequest(
        fragment=PlayableFragment(envelope=FragmentEnvelope(turn_id="preview", generation=0, sequence=0),
                                  text=text, estimated_seconds=0),
        voice=_voice(config, engine=engine, ref_file=ref_file, tts_server=tts_server, model=model),
        max_seconds=PREVIEW_SECONDS,
    )
    try:
        pcm = b"".join(tts.synthesize(request))
    except TtsError as exc:
        raise SettingsError(f"TTS 連線或試聽失敗: {exc.message}", status=502) from exc
    if not pcm:
        raise SettingsError("TTS 試聽沒有產生音訊，請檢查服務與參考資料", status=502)
    wav = BytesIO()
    sf.write(wav, np.frombuffer(pcm, dtype="<i2"), 16000, format="WAV", subtype="PCM_16")
    return "data:audio/wav;base64," + base64.b64encode(wav.getvalue()).decode("ascii")


# Short enough to fit the 5 s preview; what a visitor would hear first.
PREVIEW_SECONDS = 5.0


PROFILE_PREVIEW_TEXT = "您好，歡迎光臨，很高興為您服務。"


def breezyvoice_server_ready(config, params: Dict[str, Any], *, tts: TtsService) -> bool:
    """Whether a profile's BreezyVoice server is already up, so a preview need not start it."""
    sources = validate_tts_sources(config, {**params, "type": "breezyvoice"})
    voice = _voice(config, engine="breezyvoice", ref_file=sources["ref_file"],
                   tts_server=sources["tts_server"], model=sources["model"])
    return tts.server_status(voice).ready


def preview_profile_voice(config, params: Dict[str, Any], *, session_count: int, tts: TtsService) -> str:
    """Synthesize PROFILE_PREVIEW_TEXT with a profile's (unsaved) voice; a WAV data URI.

    Only the voice fields are read, as server-managed IDs. BreezyVoice starts
    its server when needed, but never while a conversation is connected and
    never in place of the server the applied default voice is using.
    """
    sources = validate_tts_sources(config, params)
    engine, ref_file = sources["type"], sources["ref_file"]
    tts_server, model = sources["tts_server"], sources["model"]
    meta = TTS_ENGINE_META[engine]
    if not _engine_available(meta):
        raise SettingsError(f"{meta['label']} 依賴未安裝", extra={"missing_package": meta["module"]})
    if engine == "edgetts":
        if not ref_file:
            raise SettingsError("請先填寫 Edge TTS 聲線")
        tts_server, model = "", ""
    elif engine == "matcha":
        _require_matcha_voice_model(ref_file)
        tts_server, model = "", ""
    else:
        if not ref_file:
            raise SettingsError("請先選擇有逐字稿的參考音檔")
        if not tts_section.voice_transcript(ref_file):
            raise SettingsError("這段參考音檔沒有逐字稿，請改選或重新上傳並填寫逐字稿")
        wanted = tts_section.server_identity(tts_server, model)
        default = config.tts
        if default.type == "breezyvoice" and wanted != tts_section.server_identity(
                default.tts_server, default.model):
            raise SettingsError("試聽這個 BreezyVoice 模型或服務網址會停止預設聲音正在使用的伺服器；"
                                "請先套用此設定檔，或改用相同的模型與服務網址試聽", status=409)
        voice = _voice(config, engine=engine, ref_file=ref_file, tts_server=tts_server, model=model)
        server = tts.server_status(voice)
        if server.ready:
            tts_server = server.url
        elif session_count:
            raise SettingsError("對話連線中，試聽不會啟動 BreezyVoice 伺服器；請在所有頁面斷線後再試聽",
                                status=409, extra={"sessions": session_count, "need_disconnect": True})
        else:
            try:
                tts_server = tts.prepare_voice(VoicePreparation(voice=voice)).server
            except TtsError as exc:
                raise SettingsError(f"BreezyVoice 啟動失敗：{exc.message}", status=503) from exc
    return _preview_tts(config, engine=engine, ref_file=ref_file, tts_server=tts_server,
                        model=model, tts=tts, text=PROFILE_PREVIEW_TEXT)
