// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

const json = body => ({ ok: true, status: 200, json: async () => ({ code: 0, data: body }) })

const catalog = {
  current: { endpoint: 'local-ollama', provider: 'ollama', model: 'qwen3.5:4b', base_url: 'http://localhost:11434/v1' },
  endpoints: [],
  providers: {
    ollama: { name: 'local-ollama', provider: 'ollama', base_url: 'http://localhost:11434/v1', reachable: true, models: [{ name: 'qwen3.5:4b' }] },
    llamacpp: { name: 'local-llama', provider: 'llamacpp', base_url: 'http://127.0.0.1:8080/v1', reachable: true, models: [{ name: 'gemma.gguf' }] }
  }
}

function withFetch(t) {
  const previous = globalThis.fetch
  const applied = []
  globalThis.fetch = async (url, init = {}) => {
    if (url === '/api/llm/models') return json(catalog)
    const body = JSON.parse(init.body)
    applied.push(body)
    const provider = body.endpoint === 'local-llama' ? 'llamacpp' : 'ollama'
    return json({ model: body.model, endpoint: body.endpoint, provider, system_prompt: 'p', assistant_profile: {} })
  }
  t.after(() => { globalThis.fetch = previous })
  return applied
}

test('套用模型時送出控制台所選 provider 的端點，而非目前端點', async t => {
  const applied = withFetch(t)
  const settings = useRuntimeSettings()
  settings.runtime.llm.endpoint = 'local-ollama'
  settings.runtime.llm.provider = 'ollama'
  await settings.loadOllamaModels()

  settings.selectProvider('llamacpp')
  await settings.applyLlmModel()
  assert.equal(applied.at(-1).endpoint, 'local-llama')
  assert.equal(applied.at(-1).model, 'gemma.gguf')

  settings.selectProvider('ollama')
  await settings.applyLlmModel()
  assert.equal(applied.at(-1).endpoint, 'local-ollama')
})

test('所選 provider 沒有設定端點時拒絕套用，不改送目前端點', async t => {
  const applied = withFetch(t)
  const settings = useRuntimeSettings()
  await settings.loadOllamaModels()
  settings.runtime.llm.endpoint = 'local-ollama'
  settings.runtime.llm.provider = 'ollama'
  settings.llamacpp.endpoint = ''
  settings.selectProvider('llamacpp')
  settings.selectedLlm.value = 'gemma.gguf'
  await assert.rejects(settings.applyLlmModel(), /llama\.cpp/)
  assert.equal(applied.length, 0)
})
