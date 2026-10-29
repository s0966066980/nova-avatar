// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import { all, loadComponent, mount, settle, textContent } from './helpers/componentHarness.js'

const Panel = await loadComponent(new URL('../src/components/ConversationPanel.vue', import.meta.url))

for (const enabled of [true, false]) {
  test(`控制台記憶面板顯示${enabled ? '本場自動清場及返回時間' : '自動清場已停用'}`, async t => {
    const previousFetch = globalThis.fetch
    const session = { sessionid: 7, role: 'console', locale: 'zh-TW', history_max_messages: 20,
      voice_zh_tw: '', voice_en_us: '', profiles: [], idle_reset_seconds: enabled ? 15 : 0,
      full_reset_seconds: enabled ? 60 : 0, memory: { retained_messages: 2, max_messages: 20, evicted_messages: 0 } }
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ code: 0,
      data: { sessions: [session], defaults: session, voices: {}, model_context: {} } }) })
    const view = mount(Panel, { sessionId: 7 })
    t.after(() => { view.unmount(); globalThis.fetch = previousFetch })
    await settle()
    const text = textContent(view.root)
    if (enabled) {
      assert.match(text, /15 秒清字幕與看板/)
      assert.match(text, /60 秒.*清空.*返回主數位人/)
      assert.doesNotMatch(text, /舞台閒置|控制台對話維持手動清空/)
    } else {
      assert.match(text, /停用自動清場/)
    }
  })
}

test('控制台語系摘要不會被正在檢視的舞台場次取代，並隨重新整理更新', async t => {
  const previousFetch = globalThis.fetch, previousInterval = globalThis.setInterval
  let refresh, locale = 'en-US'
  globalThis.setInterval = callback => { refresh = callback; return 0 }
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ code: 0, data: {
    sessions: [{ sessionid: 7, locale, history_max_messages: 20, memory: {} },
      { sessionid: 9, role: 'stage', locale: 'zh-TW', history_max_messages: 20, memory: {} }],
    defaults: {}, voices: {}, model_context: {}
  } }) })
  const summaries = []
  const view = mount(Panel, { sessionId: 7, onSessionSummary: value => summaries.push(value) })
  t.after(() => { view.unmount(); globalThis.fetch = previousFetch; globalThis.setInterval = previousInterval })
  await settle()
  assert.deepEqual(summaries.at(-1), { sessionId: 7, locale: 'en-US' })
  all(view.root, node => node.type === 'select')[0].props['onUpdate:modelValue']('9')
  await settle()
  assert.deepEqual(summaries.at(-1), { sessionId: 7, locale: 'en-US' })
  locale = 'zh-TW'
  await refresh()
  await settle()
  assert.deepEqual(summaries.at(-1), { sessionId: 7, locale: 'zh-TW' })
  view.props.sessionId = 11
  await settle()
  assert.equal(summaries.at(-1), null, '重連等待新場次時不沿用舊語系')
})
