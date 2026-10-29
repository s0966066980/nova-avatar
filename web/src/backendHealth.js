// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// /health is public: it only says whether the local LLM runs fully on the GPU.
// Layer counts and VRAM holders stay in the backend log.
export function readBackendHealth(data) {
  return {
    ready: Boolean(data?.ready),
    modelReady: Boolean(data?.model_ready),
    llmPartialGpu: data?.llm_full_gpu === false
  }
}
