// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test'
import assert from 'node:assert/strict'
import { greetingError, visibleLength } from '../src/greeting.js'

test('招呼字數以字素計數，包含標點並忽略空白', () => {
  for (const [text, expected] of [['你好，世界！', 6], ['a e\u0301 👨‍👩‍👧‍👦 🇹🇼\n', 4], ['\t\n　', 0], ['👍🏽！', 2], ['a\u0085b', 2]]) assert.equal(visibleLength(text), expected)
})
test('草稿驗證接受超限文案，但拒絕空內容及無效範圍', () => {
  const settings = { mode: 'scripts', scripts: ['你好'], prompt: '', min_chars: 20, max_chars: 60 }
  assert.equal(greetingError(settings), '')
  assert.ok(greetingError({ ...settings, scripts: [' '] }))
  assert.ok(greetingError({ ...settings, min_chars: 61 }))
  assert.ok(greetingError({ ...settings, min_chars: 1.2 }))
  assert.ok(greetingError({ ...settings, max_chars: 0 }))
  assert.ok(greetingError({ ...settings, mode: 'ai' }))
  assert.equal(greetingError({ ...settings, mode: 'ai', prompt: '介紹服務' }), '')
})

const { loadComponent, mount, all, button, textContent, settle } = await import('./helpers/componentHarness.js')
const { reactive } = await import('vue')
const runtime = reactive({ mode: 'visitor' })
let requests = []
const Editor = await loadComponent(new URL('../src/components/IdleGreetingEditor.vue', import.meta.url), {
  '../composables/useRoles.js': { useRoles: () => ({ roleRuntime: runtime, roleRequest: async (path, method, body) => {
    requests.push({ path, method, body: JSON.parse(JSON.stringify(body)) })
    if (path === '/mode') { runtime.mode = body.mode; return {} }
    return { code: 0, text: body.profile.greeting.scripts[0], length: 2, in_range: false }
  } }) }
})

test('預覽與試播使用未儲存草稿，不切換舞台輸入', async t => {
  requests = []; runtime.mode = 'visitor'
  const previousDocument = globalThis.document
  globalThis.document = { activeElement: null, getElementById: () => ({ value: '7' }) }
  const profile = { name: '主角色', greeting: { mode: 'scripts', scripts: ['你好'], prompt: '', min_chars: 20, max_chars: 60 } }
  const view = mount(Editor, { profile })
  t.after(() => { view.unmount(); globalThis.document = previousDocument })
  view.props.profile.greeting.scripts[0] = '草稿'
  await settle()
  await button(view.root, '預覽草稿').props.onClick()
  await settle()
  assert.equal(requests[0].path, '/greeting/preview')
  assert.equal(requests[0].body.profile.greeting.scripts[0], '草稿')
  assert.ok(textContent(view.root).includes('2 字'))
  assert.ok(textContent(view.root).includes('超出建議範圍'))
  await button(view.root, '試播草稿').props.onClick()
  await settle()
  assert.deepEqual(requests.slice(1).map(request => request.path), ['/greeting/try'])
  assert.equal(requests.at(-1).body.sessionid, 7)
  assert.equal(requests.at(-1).body.profile.greeting.scripts[0], '草稿')
  assert.equal(all(view.root, node => node.type === 'button' && textContent(node).includes('返回訪客模式')).length, 0)
  assert.ok(requests.every(request => !['', '/apply'].includes(request.path)))
})

const { createSSRApp } = await import('vue')
const { renderToString } = await import('vue/server-renderer')
const LiveEditor = await loadComponent(new URL('../src/components/IdleGreetingEditor.vue', import.meta.url))
for (const mode of ['scripts', 'ai']) {
  test(`閒置時 ${mode} 招呼內容不得輸出原生 disabled 屬性`, async () => {
    const profile = { name: '接待員', greeting: { mode, scripts: ['歡迎光臨'], prompt: '介紹服務', min_chars: 20, max_chars: 60 } }
    const html = await renderToString(createSSRApp(LiveEditor, { profile, disabled: false }))
    assert.doesNotMatch(html, /<fieldset\b[^>]*\sdisabled(?:[\s=>])/u,
      '未執行載入、預覽或試播時，招呼輸入欄位必須可以編輯')
  })
}


test('父頁載入或儲存時，仍正確鎖住招呼欄位', async () => {
  const profile = { name: '接待員', greeting: { mode: 'ai', scripts: [], prompt: '介紹服務', min_chars: 20, max_chars: 60 } }
  const html = await renderToString(createSSRApp(LiveEditor, { profile, disabled: true }))
  assert.match(html, /<fieldset\b[^>]*\sdisabled(?:[\s=>])/u)
})

for (const trial of [false, true]) {
  for (const fails of [false, true]) {
    test(`${trial ? '試播' : '預覽'}${fails ? '失敗' : '完成'}後，招呼內容恢復可編輯`, async t => {
      let resolveRequest, rejectRequest
      const pending = new Promise((resolve, reject) => { resolveRequest = resolve; rejectRequest = reject })
      const PendingEditor = await loadComponent(new URL('../src/components/IdleGreetingEditor.vue', import.meta.url), {
        '../composables/useRoles.js': { useRoles: () => ({ roleRuntime: { mode: 'console' }, roleRequest: () => pending }) }
      })
      const previousDocument = globalThis.document
      globalThis.document = { activeElement: null, getElementById: () => ({ value: '7' }) }
      const profile = { name: '接待員', greeting: { mode: 'ai', scripts: [], prompt: '介紹服務', min_chars: 20, max_chars: 60 } }
      const view = mount(PendingEditor, { profile, disabled: false })
      t.after(() => { view.unmount(); globalThis.document = previousDocument })
      const fieldset = () => all(view.root, node => node.type === 'fieldset')[0]
      assert.equal(fieldset().props.disabled, false)
      const work = button(view.root, trial ? '試播草稿' : '預覽草稿').props.onClick()
      await settle()
      assert.equal(fieldset().props.disabled, true, '只有請求執行期間才鎖住內容')
      if (fails) rejectRequest(new Error('服務暫時無法使用'))
      else resolveRequest({ text: '您好，歡迎參觀。', length: 8, in_range: false })
      await work
      await settle()
      assert.equal(fieldset().props.disabled, false)
      if (fails) assert.match(textContent(view.root), /服務暫時無法使用/)
    })
  }
}
