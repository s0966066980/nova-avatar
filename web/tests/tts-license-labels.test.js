// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { h } from 'vue'
import { loadComponent, mount, all, textContent, settle } from './helpers/componentHarness.js'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

const Editor = await loadComponent(new URL('../src/components/AvatarProfileEditor.vue', import.meta.url), {
  './RagFlowSettings.vue': { default: { setup: () => () => h('div') } },
  '../composables/useRuntimeSettings': { useRuntimeSettings }
})

test('角色聲音引擎選單顯示伺服器目錄的授權限制標示', async t => {
  const { speech } = useRuntimeSettings()
  const previous = speech.tts.engines
  speech.tts.engines = [
    { id: 'edgetts', label: 'Edge TTS (Development only)' },
    { id: 'breezyvoice', label: 'BreezyVoice' }
  ]
  const profile = { id: 'main', name: '接待員', avatar_id: '', engine: 'musetalk',
    llm: { endpoint: '', model: '' }, assistant_profile: { system_prompt: '', forbidden_self_names: [] }, reply_rules: {},
    tools: { weather: false },
    tts: { type: 'breezyvoice', ref_file: '' },
    rag: { enabled: false, dataset_ids: [], document_scope: 'all', document_ids: [] } }
  const view = mount(Editor.default ?? Editor, { modelValue: profile, initialSection: 'voice' })
  t.after(() => { view.unmount(); speech.tts.engines = previous })
  await settle()
  const options = all(view.root, node => node.type === 'option').map(textContent)
  assert.ok(options.includes('Edge TTS (Development only)'))
  assert.ok(options.includes('BreezyVoice'))
  assert.ok(!options.some(option => /cosyvoice|piper|xtts/i.test(option)), '只列出 BreezyVoice 與 Edge TTS')
})
