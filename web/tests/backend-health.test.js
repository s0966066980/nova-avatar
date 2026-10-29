// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import { readBackendHealth } from '../src/backendHealth.js'

test('LLM 未全 GPU 執行時，控制台要顯示警告', () => {
  const health = readBackendHealth({ ready: true, model_ready: true, llm_full_gpu: false })
  assert.deepEqual(health, { ready: true, modelReady: true, llmPartialGpu: true })
})

test('全 GPU 或後端未回報時不顯示警告', () => {
  assert.equal(readBackendHealth({ ready: true, llm_full_gpu: true }).llmPartialGpu, false)
  assert.equal(readBackendHealth({ ready: true }).llmPartialGpu, false)
  assert.deepEqual(readBackendHealth(null), { ready: false, modelReady: false, llmPartialGpu: false })
})
