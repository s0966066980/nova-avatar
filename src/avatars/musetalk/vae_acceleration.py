# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Optional TensorRT adapter around the existing MuseTalk VAE interface.

The engine accepts unscaled FP16 latents and returns raw decoder samples.
Encoding, model parameters, and the fallback decoder stay owned by MuseTalk.
"""

from pathlib import Path
from threading import Lock

import numpy as np
import torch

from src.utils.logging import logger


class TensorRTVAEDecoder:
    def __init__(self, original, engine_path):
        # Bindings may be installed separately to use Jetson's system runtime.
        try:
            import tensorrt as trt
        except ImportError:
            import tensorrt_bindings as trt

        self.original = original
        self._logger = trt.Logger(trt.Logger.WARNING)
        self._runtime = trt.Runtime(self._logger)
        self._engine = self._runtime.deserialize_cuda_engine(Path(engine_path).read_bytes())
        if self._engine is None:
            raise ValueError("Unable to deserialize the VAE engine on this device")
        if self._engine.num_io_tensors != 2:
            raise ValueError("VAE engine must have exactly latents and decoded tensors")
        for name in ("latents", "decoded"):
            if self._engine.get_tensor_dtype(name) != trt.float16:
                raise ValueError(f"VAE engine tensor {name} must use FP16")
        self._context = self._engine.create_execution_context()
        if self._context is None:
            raise ValueError("Unable to create the VAE execution context")
        self._lock = Lock()
        self._stream = None
        self._failed = False

    def __getattr__(self, name):
        return getattr(self.original, name)

    @torch.no_grad()
    def decode_latents(self, latents):
        with self._lock:
            if not self._failed:
                try:
                    if latents.device.type != "cuda" or latents.dtype != torch.float16:
                        raise ValueError("VAE engine requires CUDA FP16 latents")
                    inputs = latents.contiguous()
                    if not self._context.set_input_shape("latents", tuple(inputs.shape)):
                        raise ValueError("VAE batch is outside the engine shape profile")
                    shape = tuple(self._context.get_tensor_shape("decoded"))
                    if shape != (inputs.shape[0], 3, 256, 256):
                        raise ValueError(f"Unexpected VAE output shape: {shape}")
                    output = torch.empty(shape, device=inputs.device, dtype=torch.float16)
                    self._context.set_tensor_address("latents", inputs.data_ptr())
                    self._context.set_tensor_address("decoded", output.data_ptr())
                    if self._stream is None:
                        self._stream = torch.cuda.Stream(device=inputs.device)
                    self._stream.wait_stream(torch.cuda.current_stream(inputs.device))
                    with torch.cuda.stream(self._stream):
                        if not self._context.execute_async_v3(self._stream.cuda_stream):
                            raise RuntimeError("VAE engine execution failed")
                        # Preserve MuseTalk's range, rounding and BGR contract.
                        # The CPU transfer synchronizes the private stream
                        # before its buffers leave this locked invocation.
                        pixels = (
                            (output / 2 + 0.5).clamp(0, 1)
                            .permute(0, 2, 3, 1).float().cpu().numpy()
                        )
                    return np.rint(pixels * 255).astype(np.uint8)[..., ::-1]
                except Exception as exc:
                    if self._stream is not None:
                        self._stream.synchronize()
                    self._failed = True
                    logger.warning("TensorRT VAE disabled; using original decoder: %s", exc)
            return self.original.decode_latents(latents)
