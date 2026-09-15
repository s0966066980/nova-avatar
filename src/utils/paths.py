# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""路徑解析工具"""
import os
from pathlib import Path

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()

# 各資源目錄
MODELS_DIR = PROJECT_ROOT / "models"
DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets"
WEB_DIR = PROJECT_ROOT / "web"
CONFIG_DIR = PROJECT_ROOT / "config"


def get_project_root() -> Path:
    """獲取專案根目錄"""
    return PROJECT_ROOT


def get_models_dir() -> Path:
    """獲取模型目錄"""
    return MODELS_DIR


def get_data_dir() -> Path:
    """獲取資料目錄"""
    return DATA_DIR


def get_assets_dir() -> Path:
    """獲取資源目錄"""
    return ASSETS_DIR


def get_web_dir() -> Path:
    """獲取 Web 資源目錄"""
    return WEB_DIR


def get_config_dir() -> Path:
    """獲取配置目錄"""
    return CONFIG_DIR


def resolve_path(path: str) -> Path:
    """
    解析路徑，支援相對路徑和絕對路徑
    
    Args:
        path: 路徑字串
    
    Returns:
        Path: 解析後的絕對路徑
    """
    p = Path(path)
    if p.is_absolute():
        return p
    else:
        return (PROJECT_ROOT / p).resolve()


def ensure_dir(path: Path) -> Path:
    """
    確保目錄存在，不存在則建立
    
    Args:
        path: 目錄路徑
    
    Returns:
        Path: 目錄路徑
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
