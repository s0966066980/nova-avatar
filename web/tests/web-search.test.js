// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'
import { webSearchState, receiveWebSearch, safeWebLink } from '../src/webSearchState.js'
import { all, loadComponent, mount, settle, textContent } from './helpers/componentHarness.js'
const Sources = await loadComponent(new URL('../src/components/WebSearchSources.vue', import.meta.url))

test('搜尋事件只更新目前輪次，取消、換角及清場丟棄舊來源', () => {
  const state = webSearchState()
  const event = data => receiveWebSearch(state, data)
  event({ type: 'web_search_clear', turn_id: 'one' })
  event({ type: 'state', state: 'searching', turn_id: 'one' })
  assert.equal(state.phase, 'searching')
  event({ type: 'web_search_clear', turn_id: 'two' })
  event({ type: 'web_search_result', turn_id: 'one', sources: [{ title: 'late' }] })
  assert.equal(state.result, null)
  event({ type: 'web_search_result', turn_id: 'two', sources: [] })
  assert.ok(state.result)
  event({ type: 'turn_cancelled', turn_id: 'two' })
  assert.equal(state.result, null)
  for (const type of ['role_clear', 'conversation_reset', 'answer_clear']) {
    event({ type: 'web_search_clear', turn_id: 'new' })
    event({ type: 'web_search_result', turn_id: 'new', sources: [] })
    event({ type })
    event({ type: 'web_search_result', turn_id: 'new', sources: [{ title: 'late' }] })
    assert.equal(state.result, null)
  }
})

test('來源元件區分全文與摘要，網址只接受安全 HTTP 連結', async t => {
  const result = reactive({ status: 'snippets', turn_id: 'one', reused: true, sources: [
    { id: '1', title: '<script>untrusted</script>', url: 'javascript:alert(1)', snippet: '摘要', kind: 'snippet' },
    { id: '2', title: '官網', url: 'https://example.com/', snippet: '全文摘要', kind: 'page' }
  ] })
  const view = mount(Sources, { result })
  t.after(view.unmount)
  await settle()
  assert.equal(all(view.root, n => n.type === 'a').length, 1)
  assert.match(textContent(view.root), /搜尋摘要，未核對全文/)
  assert.match(textContent(view.root), /已讀取網頁/)
  assert.match(textContent(view.root), /五分鐘/)
  assert.equal(all(view.root, n => n.type === 'script').length, 0)
  view.props.locale = 'en-US'
  view.props.phase = 'searching'
  await settle()
  assert.match(textContent(view.root), /Searching the web/)
  for (const value of ['javascript:alert(1)', 'file:///etc/passwd', 'https://user:pass@example.com/']) assert.equal(safeWebLink(value), '')
})

test('舊角色設定預設不搜尋，編輯開關與網域保留為角色自己的政策', async t => {
  const { h } = await import('vue')
  const { useRuntimeSettings } = await import('../src/composables/useRuntimeSettings.js')
  const Editor = await loadComponent(new URL('../src/components/AvatarProfileEditor.vue', import.meta.url), {
    './RagFlowSettings.vue': { default: { setup: () => () => h('div') } },
    './VoiceLibraryManager.vue': { default: { setup: () => () => h('div') } },
    '../composables/useRuntimeSettings': { useRuntimeSettings }
  })
  const profile = reactive({ id: 'main', name: '接待員', engine: 'musetalk', avatar_id: '',
    llm: {}, assistant_profile: { system_prompt: '', forbidden_self_names: [] }, reply_rules: {},
    tts: { type: 'edgetts' }, rag: {} })
  const view = mount(Editor, { modelValue: profile, initialSection: 'web' })
  t.after(view.unmount)
  const label = all(view.root, n => n.type === 'label' && textContent(n).includes('允許此數位人'))[0]
  const toggle = all(label, n => n.type === 'input')[0]
  assert.equal(toggle.props.checked, false)
  toggle.props.onChange({ target: { checked: true } })
  await settle()
  assert.equal(profile.web_search.enabled, true)
  const domains = all(view.root, n => n.type === 'textarea' && n.props.placeholder === '例如 gov.tw')[0]
  domains.props.onInput({ target: { value: 'gov.tw\npython.org' } })
  assert.deepEqual(profile.web_search.allowed_domains, ['gov.tw', 'python.org'])
})

test('整理階段顯示進度，直接播出事實後清除等待且保留來源', async t => {
  const state = webSearchState()
  receiveWebSearch(state, { type: 'web_search_clear', turn_id: 'one' })
  receiveWebSearch(state, { type: 'web_search_result', turn_id: 'one', sources: [] })
  receiveWebSearch(state, { type: 'state', state: 'summarizing', turn_id: 'one' })
  assert.equal(state.phase, 'summarizing')
  const view = mount(Sources, { result: state.result, phase: state.phase })
  t.after(view.unmount)
  await settle()
  assert.match(textContent(view.root), /正在整理資料/)
  receiveWebSearch(state, { type: 'state', state: 'tts_ready', turn_id: 'one' })
  assert.equal(state.phase, '')
  assert.ok(state.result)
})
