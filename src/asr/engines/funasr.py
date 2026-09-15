# Derived from Kedreamix/Linly-Talker-Stream.
# Licensed under the Apache License, Version 2.0.
# Modified by HongXian0903, 2026. See LICENSE and NOTICE.

"""
FunASR 引擎實現
阿里達摩院的 FunASR，專注中文識別
"""

from functools import lru_cache
from pathlib import Path
from typing import Dict, Any

import torch

from src.utils.logging import logger
from src.asr.base import BaseASR


LOCAL_MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "funasr" / "paraformer-zh"
REQUIRED_MODEL_FILES = frozenset({
    "am.mvn",
    "config.yaml",
    "configuration.json",
    "model.pt",
    "seg_dict",
    "tokens.json",
})
FUNASR_OUTPUT_SCRIPTS = frozenset({"traditional-tw", "simplified"})


@lru_cache(maxsize=1)
def _taiwan_traditional_converter():
    from opencc import OpenCC

    return OpenCC("s2twp")


def convert_funasr_text(text: str, output_script: str) -> str:
    """Convert Paraformer simplified output to the configured Chinese script."""
    if output_script == "simplified" or not text:
        return text
    if output_script != "traditional-tw":
        raise ValueError(f"不支援的 FunASR 輸出文字: {output_script}")
    return _taiwan_traditional_converter().convert(text)


def local_funasr_model_ready(model_dir: Path = LOCAL_MODEL_DIR) -> bool:
    """Return whether a complete browser-downloaded Paraformer model is present."""
    return model_dir.is_dir() and all((model_dir / name).is_file() for name in REQUIRED_MODEL_FILES)


def resolve_funasr_model(model_name: str) -> str:
    """Prefer the bundled local Paraformer checkpoint over the remote alias."""
    requested = str(model_name or "paraformer-zh").strip()
    if requested == "paraformer-zh" and local_funasr_model_ready(LOCAL_MODEL_DIR):
        return str(LOCAL_MODEL_DIR)
    return str(Path(requested).expanduser()) if Path(requested).expanduser().is_dir() else requested


class FunASR(BaseASR):
    """
    FunASR 引擎（阿里達摩院）
    
    專注中文語音識別，速度快，準確度高
    """
    
    def __init__(self, config=None, model_name: str = "paraformer-zh"):
        """
        初始化 FunASR
        
        Args:
            config: 配置物件
            model_name: 模型名稱（預設 paraformer-zh）
        """
        super().__init__(config)
        
        self.model_name = resolve_funasr_model(model_name)
        self.output_script = getattr(
            getattr(config, "asr", None),
            "output_script",
            "traditional-tw",
        )
        requested_device = str(
            getattr(getattr(config, "asr", None), "device", "auto")
            or "auto"
        ).lower()
        if requested_device == "auto":
            requested_device = "cuda" if torch.cuda.is_available() else "cpu"
        if requested_device not in {"cpu", "cuda"}:
            raise ValueError(f"不支援的 FunASR 裝置: {requested_device}")
        if requested_device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("FunASR 設定要求 CUDA，但目前沒有可用的 CUDA")
        self.device = requested_device
        self.model = None
        
        logger.info(f'[FunASR] 模型: {model_name}')
    
    def _load_model(self):
        """載入 FunASR 模型"""
        try:
            from funasr import AutoModel
            logger.info(f'[FunASR] 正在載入模型: {self.model_name}')
            self.model = AutoModel(
                model=self.model_name,
                device=self.device,
                disable_update=True,
            )
            logger.info('[FunASR] 模型載入成功')
            
        except ImportError:
            raise ImportError(
                "請安裝 FunASR:\n"
                "  pip install funasr"
            )
        except Exception as e:
            logger.error(f'[FunASR] 模型載入失敗: {e}')
            raise
    
    def _transcribe(self, audio_path: str) -> Dict[str, Any]:
        """
        使用 FunASR 識別音訊
        
        Args:
            audio_path: 音訊檔案路徑
            
        Returns:
            識別結果字典
        """
        result = self.model.generate(input=audio_path)
        
        if result and len(result) > 0:
            text = convert_funasr_text(
                result[0].get("text", ""),
                self.output_script,
            )
            return {
                "text": text.strip(),
                "language": "zh"
            }
        
        return {
            "text": "",
            "language": "zh"
        }
    
    def get_info(self) -> Dict[str, Any]:
        """獲取引擎資訊"""
        info = super().get_info()
        info.update({
            "model_name": self.model_name,
            "device": self.device,
        })
        return info
