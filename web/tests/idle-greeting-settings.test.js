// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadComponent, mount, all, button, textContent, settle } from './helpers/componentHarness.js'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

const Editor = await loadComponent(new URL('../src/components/IdleGreetingEditor.vue', import.meta.url))
const Page = await loadComponent(new URL('../src/components/IdleGreetingSettings.vue', import.meta.url), {
  './IdleGreetingEditor.vue': { default: Editor }
})
function fixture(t, { enabled = false, failApply = false } = {}) {
  const previousFetch = globalThis.fetch
  let library = { version: 1, revision: 7, enabled: false, pair: { main: 'main', specialist: 'specialist' }, profiles: [
    { id: 'main', name: '接待員', tts: { type: 'edgetts' }, greeting: { mode: 'scripts', scripts: ['歡迎光臨'], prompt: '', min_chars: 20, max_chars: 60 } },
    { id: 'specialist', name: '氣象員', greeting: { mode: 'scripts', scripts: ['未修改的專門角色文案'], prompt: '', min_chars: 20, max_chars: 60 } }
  ] }
  let stage = { idle_greeting_enabled: enabled, idle_greeting_seconds: 60, idle_reset_seconds: 10, caption_max_chars: 120 }
  const requests = []
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : undefined
    requests.push({ url, method: options.method || 'GET', body })
    const ok = data => ({ ok: true, json: async () => ({ code: 0, ...data }) })
    if (url === '/api/profiles') {
      if (options.method === 'PUT') {
        assert.equal(body.expected_revision, library.revision)
        library = { ...body.library, revision: library.revision + 1 }
      }
      return ok({ library: structuredClone(library), runtime: { mode: 'visitor', phase: 'disabled', active_revision: library.revision, profiles_applied: true } })
    }
    if (url === '/api/profiles/greeting/apply') {
      if (failApply) return { ok: false, json: async () => ({ code: -1, msg: '目前無法套用' }) }
      assert.ok(!stage.idle_greeting_enabled || library.profiles[0].greeting.prompt || library.profiles[0].greeting.scripts.some(Boolean))
      return ok({ runtime: { active_revision: library.revision } })
    }
    if (url === '/api/stage') { if (body) stage = { ...stage, ...body }; return ok({ data: { ...stage }, greetings: [] }) }
    if (url === '/api/profiles/greeting/preview') return ok({ text: '您好，我可以協助導覽，歡迎向我提問。', length: 19, in_range: true })
    throw Error(`Unexpected API ${url}`)
  }
  const view = mount(Page, { active: true })
  t.after(() => { view.unmount(); globalThis.fetch = previousFetch })
  return { view, requests, get library() { return library }, get stage() { return stage } }
}
const input = (root, id) => all(root, node => node.props.id === id)[0]
const set = async (root, id, value) => { input(root, id).props['onUpdate:modelValue'](value); await settle() }
async function chooseAI(root) {
  const radio = all(root, node => node.type === 'input' && node.props.type === 'radio' && node.props.value === 'ai')[0]
  radio.props['onUpdate:modelValue']('ai')
  await settle()
}

test('同一招呼頁編輯開關、時間、Prompt、字數並預覽，儲存後留在本頁', async t => {
  const field = fixture(t)
  await settle()
  const { root } = field.view
  assert.ok(input(root, 'greeting-enabled'))
  assert.ok(input(root, 'greeting-seconds'))
  await chooseAI(root)
  await set(root, 'greeting-prompt', '用親切口吻介紹服務，邀請訪客提問。')
  await set(root, 'greeting-min-chars', 15)
  await set(root, 'greeting-max-chars', 50)
  await set(root, 'greeting-enabled', true)
  await set(root, 'greeting-seconds', 30)
  await button(root, '預覽草稿').props.onClick()
  await settle()
  const preview = field.requests.find(request => request.url.endsWith('/greeting/preview'))
  assert.equal(preview.body.profile.greeting.prompt, '用親切口吻介紹服務，邀請訪客提問。')
  assert.equal(field.requests.filter(request => request.method === 'PUT').length, 0)
  await button(root, '儲存並套用招呼設定').props.onClick()
  await settle()
  assert.equal(field.library.profiles[0].greeting.mode, 'ai')
  assert.equal(field.library.profiles[0].greeting.max_chars, 50)
  assert.deepEqual(field.library.profiles[1].greeting.scripts, ['未修改的專門角色文案'])
  assert.equal(field.stage.idle_greeting_seconds, 30)
  assert.equal(field.stage.idle_greeting_enabled, true)
  const writes = field.requests.filter(request => ['PUT', 'POST'].includes(request.method) && !request.url.endsWith('/preview'))
  assert.deepEqual(writes.map(request => request.url), ['/api/profiles', '/api/profiles/greeting/apply', '/api/stage'])
  assert.deepEqual(writes.at(-1).body, { idle_greeting_enabled: true, idle_greeting_seconds: 30 })
  assert.ok(input(root, 'greeting-prompt'), '套用後 Prompt 應留在原頁')
  assert.match(textContent(root), /招呼設定已儲存並套用/)
})

test('停用與清空內容可在同一頁儲存，先停止招呼再套用空草稿', async t => {
  const field = fixture(t, { enabled: true })
  await settle()
  const { root } = field.view
  await chooseAI(root)
  await set(root, 'greeting-enabled', false)
  await set(root, 'greeting-prompt', '')
  await button(root, '儲存並套用招呼設定').props.onClick()
  await settle()
  const writes = field.requests.filter(request => ['PUT', 'POST'].includes(request.method))
  assert.equal(writes[0].url, '/api/stage')
  assert.deepEqual(writes[0].body, { idle_greeting_enabled: false })
  assert.equal(field.stage.idle_greeting_enabled, false)
  assert.equal(field.library.profiles[0].greeting.prompt, '')
  assert.match(textContent(root), /招呼設定已儲存並套用/)
})

test('套用失敗會保留同頁草稿並說明哪些步驟未完成', async t => {
  const field = fixture(t, { failApply: true })
  await settle()
  const { root } = field.view
  await chooseAI(root)
  await set(root, 'greeting-prompt', '尚未成功套用的草稿')
  await button(root, '儲存並套用招呼設定').props.onClick()
  await settle()
  assert.match(textContent(root), /內容已儲存，尚未完成全部套用/)
  assert.equal(input(root, 'greeting-prompt').value, '尚未成功套用的草稿')
  assert.equal(field.requests.filter(request => request.url === '/api/stage' && request.method === 'POST').length, 0)
})

test('套用舞台排版不會送出其他頁的招呼或清場草稿', async t => {
  const settings = useRuntimeSettings(), requests = [], oldFetch = globalThis.fetch
  const oldReset = settings.selectedVisitorResetSeconds.value
  t.after(() => { globalThis.fetch = oldFetch; settings.selectedVisitorResetSeconds.value = oldReset })
  settings.selectedVisitorResetSeconds.value = 90
  globalThis.fetch = async (_url, options) => { const body = JSON.parse(options.body); requests.push(body); return { ok: true, json: async () => ({ code: 0, data: { ...settings.runtime.stage, ...body } }) } }
  await settings.applyStageSettings()
  assert.ok(requests[0].caption_max_chars)
  assert.equal('idle_reset_seconds' in requests[0], false)
  assert.equal('idle_greeting_enabled' in requests[0], false)
  assert.equal('idle_greeting_seconds' in requests[0], false)
  assert.equal(settings.selectedVisitorResetSeconds.value, 90)
  assert.equal(settings.visitorDirty.value, true)
  requests.length = 0
  await settings.applyVisitorSettings()
  assert.deepEqual(requests[0], { idle_reset_seconds: 90 })
  assert.equal(settings.visitorDirty.value, false)
})
