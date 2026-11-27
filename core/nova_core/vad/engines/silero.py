# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""
Silero VAD 引擎實現

基於 snakers4/silero-vad 的輕量神經網路 VAD，具備良好噪聲魯棒性，
CPU 上單幀推理約 1ms 量級，輸出 0~1 的語音機率。

模型載入順序：
1. 配置裡顯式給了 model_path（.jit / .onnx 本地檔案）
2. pip 包 silero-vad 自帶的模型（離線可用，推薦）
3. torch.hub 線上下載 snakers4/silero-vad（首次需要聯網）

注意：silero 只支援 8000 / 16000Hz，且幀長固定為 256 / 512 取樣點。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np

from src.utils.logging import logger
from src.vad.base import BaseVAD


class SileroVAD(BaseVAD):
    """Silero VAD 引擎"""

    ENGINE_TYPE = "silero"
    SUPPORTED_SAMPLE_RATES = (8000, 16000)
    # silero 要求的固定幀長（取樣點）
    FIXED_FRAME_SAMPLES = {8000: 256, 16000: 512}
    DEFAULT_FRAME_MS = 32  # 16000Hz 下 512 取樣點

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 0,
        threshold: float = 0.5,
        model_path: str = "",
        device: str = "cpu",
        use_onnx: bool = False,
        config=None,
        **kwargs,
    ):
        """
        Args:
            model_path: 本地模型檔案（.jit / .onnx），留空則用 pip 包或 torch.hub
            device: cpu | cuda | auto（逐幀推理，CPU 通常反而更快，預設 cpu）
            use_onnx: 用 onnxruntime 跑（需要 pip install onnxruntime）
        """
        self.model_path = str(model_path or "")
        self.device = self._resolve_device(device)
        self.use_onnx = bool(use_onnx) or self.model_path.endswith(".onnx")
        self.model = None
        self._source = ""
        super().__init__(
            sample_rate=sample_rate,
            frame_ms=frame_ms,
            threshold=threshold,
            config=config,
        )

    @staticmethod
    def _resolve_device(device: str) -> str:
        device = (device or "cpu").strip().lower()
        if device == "auto":
            return "cpu"  # 單幀 512 點，CPU 沒有 kernel 啟動開銷，比 GPU 更快
        return device

    def _normalize_frame_ms(self, frame_ms: int) -> int:
        """silero 幀長固定，忽略傳入值，直接換算成對應毫秒數"""
        fixed_samples = self.FIXED_FRAME_SAMPLES[self.sample_rate]
        fixed_ms = int(round(fixed_samples * 1000 / self.sample_rate))
        if frame_ms and frame_ms != fixed_ms:
            logger.warning(
                f'[VAD] silero 在 {self.sample_rate}Hz 下幀長固定為 '
                f'{fixed_samples} 取樣點({fixed_ms}ms)，已忽略配置的 {frame_ms}ms'
            )
        return fixed_ms

    @property
    def frame_samples(self) -> int:
        """嚴格返回 silero 要求的取樣點數，避免四捨五入誤差"""
        return self.FIXED_FRAME_SAMPLES[self.sample_rate]

    # ------------------------------------------------------------------ 模型載入

    def _load_model(self):
        if self.use_onnx:
            self.model = self._load_onnx_model()
        else:
            self.model = self._load_torch_model()
        logger.info(f'[VAD] silero 模型就緒（{self._source}, device={self.device}）')

    def _load_torch_model(self):
        import torch

        # 1. 本地 jit 模型
        if self.model_path:
            path = Path(self.model_path)
            if not path.exists():
                raise FileNotFoundError(f'[VAD] silero 模型不存在: {path}')
            model = torch.jit.load(str(path), map_location=self.device)
            model.eval()
            self._source = f'local:{path}'
            return model

        # 2. pip 包自帶模型（離線可用）
        try:
            from silero_vad import load_silero_vad

            model = load_silero_vad(onnx=False)
            if self.device != "cpu":
                model.to(self.device)
            self._source = 'silero-vad package'
            return model
        except ImportError:
            logger.warning('[VAD] 未安裝 silero-vad 包，改用 torch.hub 線上載入')

        # 3. torch.hub 線上下載
        try:
            model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False,
                trust_repo=True,
            )
            if self.device != "cpu":
                model.to(self.device)
            self._source = 'torch.hub'
            return model
        except Exception as e:
            raise ImportError(
                f"Silero VAD 模型載入失敗: {e}\n"
                "請安裝依賴（自帶模型，可離線使用）:\n"
                "  pip install silero-vad\n"
                "或在 config.yaml 裡配置 vad.model_path 指向本地 silero_vad.jit"
            )

    def _load_onnx_model(self):
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            raise ImportError(
                "使用 vad.use_onnx 需要安裝 onnxruntime:\n  pip install onnxruntime"
            )

        if self.model_path:
            from silero_vad.utils_vad import OnnxWrapper

            model = OnnxWrapper(self.model_path, force_onnx_cpu=True)
        else:
            from silero_vad import load_silero_vad

            model = load_silero_vad(onnx=True)
        self._source = 'onnxruntime'
        return model

    # ------------------------------------------------------------------ 推理

    def _speech_prob(self, frame: np.ndarray) -> float:
        import torch

        audio = frame.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio)
        if self.device != "cpu":
            tensor = tensor.to(self.device)
        with torch.no_grad():
            return self.model(tensor, self.sample_rate).item()

    def reset(self):
        """清空 silero 的 RNN 隱狀態，換會話/換音訊前必須呼叫"""
        if self.model is not None and hasattr(self.model, "reset_states"):
            self.model.reset_states()

    def close(self):
        self.model = None
        self._source = ""
        super().close()

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "device": self.device,
            "use_onnx": self.use_onnx,
            "model_source": self._source,
        })
        return info


__all__ = ["SileroVAD"]
