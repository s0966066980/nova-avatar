# Copyright (c) 2026 HongXian0903
# SPDX-License-Identifier: Apache-2.0

"""Optional FP16 TensorRT execution of the original MuseTalk UNet."""
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import torch

from src.utils.logging import logger

class TensorRTUNet(torch.nn.Module):
    """Single-step MuseTalk predictor with an original-model fallback.

    Engine inputs: FP16 sample [N,8,32,32], encoder_hidden_states [N,50,384].
    Output: FP16 latent [N,4,32,32]. The zero diffusion step is baked in.
    """
    def __init__(self, original, engine_path):
        super().__init__()
        try:
            import tensorrt as trt
        except ImportError:
            import tensorrt_bindings as trt

        self.original = original
        self._logger = trt.Logger(trt.Logger.WARNING)
        self._runtime = trt.Runtime(self._logger)
        self._engine = self._runtime.deserialize_cuda_engine(Path(engine_path).read_bytes())
        if self._engine is None or self._engine.num_io_tensors != 3:
            raise ValueError("UNet engine must have sample, encoder_hidden_states and latent")
        for name, mode in (
            ("sample", trt.TensorIOMode.INPUT),
            ("encoder_hidden_states", trt.TensorIOMode.INPUT),
            ("latent", trt.TensorIOMode.OUTPUT),
        ):
            if self._engine.get_tensor_dtype(name) != trt.float16:
                raise ValueError(f"UNet engine tensor {name} must use FP16")
            if self._engine.get_tensor_mode(name) != mode:
                raise ValueError(f"Unexpected UNet tensor mode: {name}")
        self._context = self._engine.create_execution_context()
        if self._context is None:
            raise ValueError("Unable to create UNet execution context")
        self._lock = Lock()
        self._stream = None
        self._failed = False

    @property
    def dtype(self):
        return self.original.dtype

    @torch.no_grad()
    def forward(self, sample, timestep, encoder_hidden_states, **kwargs):
        with self._lock:
            if not self._failed:
                try:
                    if kwargs.keys() - {"return_dict"}:
                        raise ValueError("UNet engine does not implement optional conditioning")
                    if float(timestep) != 0:
                        raise ValueError("UNet engine only implements diffusion step zero")
                    if sample.device.type != "cuda" or sample.dtype != torch.float16:
                        raise ValueError("UNet engine requires CUDA FP16 samples")
                    if encoder_hidden_states.device != sample.device or encoder_hidden_states.dtype != sample.dtype:
                        raise ValueError("UNet feature device/dtype must match samples")
                    n = sample.shape[0]
                    if tuple(sample.shape) != (n, 8, 32, 32) or tuple(encoder_hidden_states.shape) != (n, 50, 384):
                        raise ValueError("Unexpected MuseTalk UNet input shape")
                    inputs = {
                        "sample": sample.contiguous(),
                        "encoder_hidden_states": encoder_hidden_states.contiguous(),
                    }
                    for name, tensor in inputs.items():
                        if not self._context.set_input_shape(name, tuple(tensor.shape)):
                            raise ValueError("UNet batch is outside the engine profile")
                    if tuple(self._context.get_tensor_shape("latent")) != (n, 4, 32, 32):
                        raise ValueError("Unexpected UNet output shape")
                    output = torch.empty((n, 4, 32, 32), device=sample.device, dtype=sample.dtype)
                    for name, tensor in {**inputs, "latent": output}.items():
                        self._context.set_tensor_address(name, tensor.data_ptr())
                    if self._stream is None:
                        self._stream = torch.cuda.Stream(device=sample.device)
                    self._stream.wait_stream(torch.cuda.current_stream(sample.device))
                    if not self._context.execute_async_v3(self._stream.cuda_stream):
                        raise RuntimeError("UNet engine execution failed")
                    # Do not reuse a context or release input buffers until its
                    # private stream finishes. Returned output owns its storage.
                    self._stream.synchronize()
                    return (output,) if kwargs.get("return_dict") is False else SimpleNamespace(sample=output)
                except Exception as exc:
                    if self._stream is not None:
                        self._stream.synchronize()
                    self._failed = True
                    logger.warning("TensorRT UNet disabled; using original predictor: %s", exc)
            return self.original(sample, timestep, encoder_hidden_states=encoder_hidden_states, **kwargs)
