# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""掃描本地數字人素材，判斷引擎型別與預覽圖。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.paths import get_data_dir, get_models_dir

AVATAR_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"

ENGINE_META: Dict[str, Dict[str, str]] = {
    "musetalk": {
        "label": "MuseTalk (Supported / Commercial)",
        "description": "MIT code；高質量唇形同步，模型與依賴需另行核對授權",
    },
    "wav2lip": {
        "label": "Wav2Lip (Research / Non-commercial)",
        "description": "上游公開版僅限研究、學術與個人用途，不可商用",
    },
    "ultralight": {
        "label": "UltraLight",
        "description": "端側友好的輕量數字人",
    },
    "ernerf": {
        "label": "ERNeRF",
        "description": "NeRF 渲染，畫質更高、更吃視訊記憶體",
    },
    "talkinggaussian": {
        "label": "TalkingGaussian",
        "description": "3D Gaussian 渲染，真實感更強",
    },
}

ENGINE_ORDER = list(ENGINE_META.keys())
IMPORTABLE_ENGINES = ("musetalk", "wav2lip")


def avatars_root() -> Path:
    return get_data_dir() / "avatars"


def is_safe_avatar_id(avatar_id: str) -> bool:
    import re

    return bool(avatar_id) and bool(re.fullmatch(AVATAR_ID_PATTERN, avatar_id))


def detect_avatar_type(avatar_dir: Path) -> Optional[str]:
    """根據目錄內容判斷數字人引擎，無法判斷時回退到目錄名字首。"""
    if not avatar_dir.is_dir():
        return None

    if (avatar_dir / "latents.pt").exists() and (avatar_dir / "mask").is_dir():
        return "musetalk"
    if (avatar_dir / "ultralight.pth").exists():
        return "ultralight"
    if (avatar_dir / "ngp_kf.pth").exists() or (avatar_dir / "data_kf.json").exists():
        return "ernerf"
    if _looks_like_talkinggaussian(avatar_dir):
        return "talkinggaussian"
    if (avatar_dir / "face_imgs").is_dir() and (avatar_dir / "coords.pkl").exists():
        return "wav2lip"

    name = avatar_dir.name.lower()
    for engine in ENGINE_ORDER:
        if name.startswith(engine) or name.startswith(engine.replace("talkinggaussian", "tg")):
            return engine
    return None


def _looks_like_talkinggaussian(avatar_dir: Path) -> bool:
    if (avatar_dir / "source").is_dir() and (
        (avatar_dir / "model").is_dir() or (avatar_dir / "output").is_dir()
    ):
        return True
    if (avatar_dir / "point_cloud").is_dir():
        return True
    for child in avatar_dir.iterdir() if avatar_dir.exists() else []:
        if child.is_dir() and (child / "source").is_dir():
            return True
    return False


def find_preview_image(avatar_dir: Path) -> Optional[Path]:
    """優先用 full_imgs 第一幀，其次任意常見圖片。"""
    candidates: List[Path] = []
    full_imgs = avatar_dir / "full_imgs"
    if full_imgs.is_dir():
        candidates.extend(full_imgs.glob("*.[Pp][Nn][Gg]"))
        candidates.extend(full_imgs.glob("*.[Jj][Pp][Gg]"))
        candidates.extend(full_imgs.glob("*.[Jj][Pp][Ee][Gg]"))
    if not candidates:
        for pattern in ("*.png", "*.jpg", "*.jpeg", "full_imgs/*.png"):
            candidates.extend(avatar_dir.glob(pattern))
    if not candidates:
        return None

    def sort_key(path: Path):
        stem = path.stem
        return (0, int(stem)) if stem.isdigit() else (1, stem)

    return sorted(candidates, key=sort_key)[0]


def _read_avatar_info(avatar_dir: Path) -> Dict[str, Any]:
    info_path = avatar_dir / "avator_info.json"
    if not info_path.exists():
        return {}
    try:
        return json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def list_avatar_characters() -> List[Dict[str, Any]]:
    root = avatars_root()
    if not root.is_dir():
        return []

    characters: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        engine = detect_avatar_type(child)
        if not engine:
            continue
        info = _read_avatar_info(child)
        preview = find_preview_image(child)
        characters.append(
            {
                "id": child.name,
                "type": engine,
                "label": info.get("avatar_id") or child.name,
                "has_preview": preview is not None,
                "preview_url": f"/api/avatars/{child.name}/preview" if preview else None,
            }
        )
    return characters


def engine_ready(engine: str, characters: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """判斷某引擎是否具備權重 + 至少一套角色素材。"""
    characters = characters if characters is not None else list_avatar_characters()
    has_character = any(item["type"] == engine for item in characters)
    weights_ok, reason = _engine_weights_ready(engine)
    available = has_character and weights_ok
    can_import = engine in IMPORTABLE_ENGINES and (
        weights_ok if engine == "musetalk" else True
    )
    if not has_character and not weights_ok:
        message = "尚未安裝模型權重與角色素材"
    elif not has_character:
        message = "尚未準備角色素材，可從設定匯入影片製作"
    elif not weights_ok:
        message = reason
    else:
        message = ""
    return {
        "id": engine,
        "label": ENGINE_META[engine]["label"],
        "description": ENGINE_META[engine]["description"],
        "available": available,
        "can_import": can_import,
        "has_character": has_character,
        "has_weights": weights_ok,
        "message": message,
    }


def list_engines(characters: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    characters = characters if characters is not None else list_avatar_characters()
    return [engine_ready(engine, characters) for engine in ENGINE_ORDER]


def avatar_bootable(engine: str, avatar_id: str) -> tuple[bool, str]:
    """啟動或套用前檢查該引擎+角色是否具備權重與素材。"""
    engine = (engine or "").strip().lower()
    avatar_id = (avatar_id or "").strip()
    if engine not in ENGINE_META:
        return False, f"不支援的數字人引擎: {engine or '(未選擇)'}"
    if not avatar_id:
        return False, "尚未選擇數字人角色"
    weights_ok, reason = _engine_weights_ready(engine)
    if not weights_ok:
        return False, reason
    match = next((item for item in list_avatar_characters() if item["id"] == avatar_id), None)
    if match is None:
        return False, f"找不到角色 {avatar_id}"
    if match["type"] != engine:
        return False, f"角色 {avatar_id} 屬於 {match['type']}，與引擎 {engine} 不一致"
    return True, ""


def resolve_wav2lip_weights() -> Optional[Path]:
    """Wav2Lip 實際載入路徑，與 factory 保持一致。"""
    models = get_models_dir()
    for name in ("wav2lip.pth", "wav2lip256.pth"):
        candidate = models / name
        if candidate.is_file():
            return candidate
    return None


def _engine_weights_ready(engine: str) -> tuple[bool, str]:
    models = get_models_dir()
    if engine == "musetalk":
        unet = models / "musetalk" / "musetalkV15" / "unet.pth"
        if unet.exists():
            return True, ""
        return False, "缺少 MuseTalk 權重 (models/musetalk)"
    if engine == "wav2lip":
        if resolve_wav2lip_weights() is not None:
            return True, ""
        return False, "缺少 Wav2Lip 權重 (models/wav2lip.pth 或 models/wav2lip256.pth)"
    if engine == "ultralight":
        # 權重隨角色目錄提供
        return True, ""
    if engine == "ernerf":
        return True, ""
    if engine == "talkinggaussian":
        return True, ""
    return False, "未知引擎"


def apply_engine_paths(config: Any, engine: str, avatar_id: str) -> None:
    """為需要路徑的引擎寫入對應角色目錄。"""
    avatar_dir = avatars_root() / avatar_id
    if engine == "ernerf":
        ernerf = config.model.ernerf
        ernerf.pose = str(avatar_dir / "data_kf.json")
        ernerf.au = str(avatar_dir / "au.csv")
        ernerf.workspace = str(avatar_dir) + "/"
        ckpt = avatar_dir / "ngp_kf.pth"
        if ckpt.exists():
            ernerf.ckpt = str(ckpt)
    elif engine == "talkinggaussian":
        tg = config.model.talkinggaussian
        source, model_path = _talkinggaussian_paths(avatar_dir)
        if source:
            tg.source_path = source
        if model_path:
            tg.model_path = model_path


def _talkinggaussian_paths(avatar_dir: Path) -> tuple[Optional[str], Optional[str]]:
    candidates = [
        (avatar_dir / "source", avatar_dir / "model"),
        (avatar_dir / "Obama" / "source", avatar_dir / "Obama" / "model"),
    ]
    for child in avatar_dir.iterdir() if avatar_dir.is_dir() else []:
        if child.is_dir() and (child / "source").is_dir():
            candidates.append((child / "source", child / "model"))
    for source, model_path in candidates:
        if source.is_dir():
            return str(source), str(model_path) if model_path.exists() else str(model_path)
    return None, None


def resolve_preview_path(avatar_id: str) -> Optional[Path]:
    if not is_safe_avatar_id(avatar_id):
        return None
    avatar_dir = (avatars_root() / avatar_id).resolve()
    root = avatars_root().resolve()
    if root not in avatar_dir.parents and avatar_dir != root:
        return None
    if not avatar_dir.is_dir():
        return None
    return find_preview_image(avatar_dir)
