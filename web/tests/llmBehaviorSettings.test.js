// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

async function withSettings(run) {
  const originalFetch = globalThis.fetch
  const requests = []
  let fail = false
  const profile = { assistant_name: '服務助手', system_prompt: '回答使用者的問題。', restriction_prompt: '', output_locale: 'zh-TW', enforce_output_locale: true, forbidden_self_names: [] }
  const rules = { revision: 1, activation: '依問題啟用。', speech: '只說摘要。', board: '細節放看板。' }
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null
    requests.push({ url, body })
    let data
    if (url === '/api/settings') data = { llm: { provider: 'llamacpp', model: 'old-model', system_prompt: profile.system_prompt, assistant_profile: profile, reply_rules: rules }, avatar: {} }
    else if (url === '/api/llm/rules') data = { rules, defaults: rules }
    else if (url === '/api/llm/model') data = { model: body.model, provider: body.provider, system_prompt: profile.system_prompt, assistant_profile: profile }
    else if (url === '/api/llm/behavior') {
      if (fail) return { ok: false, status: 409, json: async () => ({ code: -1, msg: '版本衝突' }) }
      data = { assistant_profile: body.assistant_profile, system_prompt: body.assistant_profile.system_prompt, rules: { ...body.rules, revision: 2 } }
    } else throw new Error(`Unexpected request ${url}`)
    return { ok: true, status: 200, json: async () => ({ code: 0, data }) }
  }
  try {
    const settings = useRuntimeSettings()
    await settings.loadRuntimeSettings()
    await run({ settings, requests, failNextSave: () => { fail = true } })
  } finally { globalThis.fetch = originalFetch }
}

test('switching models preserves saved behavior and unsaved persona and Rule drafts', async () => {
  await withSettings(async ({ settings, requests }) => {
    settings.selectedSystemPrompt.value = '尚未儲存的角色。'
    settings.rulesDraft.speech = '尚未儲存的規則。'
    settings.selectedLlm.value = 'Qwen3.5-2B-UD-Q4_K_XL'
    await settings.applyLlmModel()
    const request = requests.find(({ url }) => url === '/api/llm/model')
    assert.equal(request.body.assistant_profile, undefined)
    assert.equal(request.body.system_prompt, undefined)
    assert.equal(settings.runtime.llm.system_prompt, '回答使用者的問題。')
    assert.equal(settings.selectedSystemPrompt.value, '尚未儲存的角色。')
    assert.equal(settings.rulesDraft.speech, '尚未儲存的規則。')
    assert.equal(settings.llmDirty.value, false)
    assert.equal(settings.promptDirty.value, true)
  })
})

test('persona and Rules save in one request without applying the selected model draft', async () => {
  await withSettings(async ({ settings, requests }) => {
    settings.selectedLlm.value = 'unsaved-model'
    settings.selectedAssistantName.value = '新助手'
    settings.rulesDraft.speech = '只說主要結論。'
    await settings.applyLlmBehavior()
    const mutations = requests.filter(({ body }) => body)
    assert.equal(mutations.length, 1)
    assert.equal(mutations[0].url, '/api/llm/behavior')
    assert.equal(mutations[0].body.expected_revision, 1)
    assert.equal(settings.runtime.llm.model, 'old-model')
    assert.equal(settings.runtime.llm.assistant_profile.assistant_name, '新助手')
    assert.equal(settings.promptDirty.value, false)
    assert.equal(settings.rulesDirty.value, false)
    assert.equal(settings.llmDirty.value, true)
  })
})

test('failed behavior save keeps both drafts and the saved version for retry', async () => {
  await withSettings(async ({ settings, failNextSave }) => {
    settings.selectedRestrictionPrompt.value = '新限制。'
    settings.rulesDraft.board = '新看板原則。'
    failNextSave()
    await assert.rejects(settings.applyLlmBehavior(), /版本衝突/)
    assert.equal(settings.runtime.llm.assistant_profile.restriction_prompt, '')
    assert.equal(settings.rulesApplied.revision, 1)
    assert.equal(settings.rulesDraft.board, '新看板原則。')
    assert.equal(settings.promptDirty.value, true)
    assert.equal(settings.rulesSaving.value, false)
    assert.equal(settings.rulesError.value, '版本衝突')
  })
})
