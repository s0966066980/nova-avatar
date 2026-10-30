// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { h } from 'vue'
import { loadComponent, mount, all, button, textContent, settle } from './helpers/componentHarness.js'

const openedSections = []
const Editor = { default: {
  props: ['modelValue'],
  setup(props, { expose }) {
    expose({ openSection: section => openedSections.push(section) })
    return () => h('input', { id: 'profile-name', value: props.modelValue.name, onInput: e => { props.modelValue.name = e.target.value } })
  }
} }
const Component = await loadComponent(new URL('../src/components/AvatarProfiles.vue', import.meta.url), { './AvatarProfileEditor.vue': Editor })

test('切換設定檔保留各自草稿，複製互不影響，儲存與套用使用同一份版本', async t => {
  const previousFetch = globalThis.fetch
  const makeProfile = (id, name) => ({ id, name, avatar_id: 'shared_visual', engine: 'musetalk',
    llm: { endpoint: 'local', model: 'local-model' },
    tts: { type: 'edgetts' }, rag: { enabled: false, dataset_ids: [], document_scope: 'all', document_ids: [] } })
  let library = { enabled: false, revision: 1, profiles: [makeProfile('main','接待員'), makeProfile('weather','氣象員')],
    pair: { main: 'main', specialist: 'weather' }, transitions: [],
    handoff: { description: '天氣專長', rules: '交接規則', announcement: '交接說明' }, weather: { county: '', town: '' } }
  let activeRevision = 1
  const requests = []
  const runtime = () => ({ enabled: false, phase: 'disabled', profiles_applied: true, active_revision: activeRevision })
  globalThis.fetch = async (url, options = {}) => {
    const result = data => ({ ok: true, json: async () => data })
    if (url === '/api/profiles') {
      if (options.method === 'PUT') {
        const body = JSON.parse(options.body); requests.push(body)
        assert.equal(body.expected_revision, library.revision)
        library = { ...body.library, revision: library.revision + 1 }
      }
      return result({ code: 0, library: structuredClone(library), runtime: runtime(), media: [] })
    }
    if (url === '/api/profiles/apply') { requests.push('apply'); activeRevision = library.revision; return result({ code: 0, runtime: runtime() }) }
    if (url === '/api/llm/models') return result({ code: 0, data: { endpoints: [{ name: 'local', provider: 'llamacpp', base_url: 'http://127.0.0.1:8080/v1', models: [] }] } })
    if (url === '/api/llm/rules') return result({ code: 0, data: { defaults: {} } })
    throw Error(`Unexpected endpoint: ${url}`)
  }
  const view = mount(Component, {})
  t.after(() => { view.unmount(); globalThis.fetch = previousFetch })
  await settle()
  assert.equal(button(view.root, '僅儲存草稿').props.disabled, true)
  const input = () => all(view.root, n => n.props.id === 'profile-name')[0]
  input().props.onInput({ target: { value: '更新的接待員' } })
  await settle()
  button(view.root, '氣象員').props.onClick()
  await settle()
  assert.equal(input().props.value, '氣象員')
  button(view.root, '更新的接待員').props.onClick()
  await settle()
  assert.equal(input().props.value, '更新的接待員')
  button(view.root, '複製為新設定檔').props.onClick()
  await settle()
  input().props.onInput({ target: { value: '第三位數位人' } })
  await settle()
  button(view.root, '角色組合、交接與轉場').props.onClick()
  await settle()
  for (const [label, value] of [
    ['中文返回交接說明', '接下來請主數位人為您介紹。'],
    ['英文返回交接說明', 'Our main avatar will introduce our services.']
  ]) {
    const field = all(view.root, n => n.type === 'label' && textContent(n).includes(label))[0]
    assert.ok(field, `提供有標籤的${label}欄位`)
    all(field, n => n.type === 'textarea')[0].props['onUpdate:modelValue'](value)
  }
  await settle()
  all(view.root, n => n.type === 'form')[0].props.onSubmit({ preventDefault() {} })
  await settle()
  assert.equal(library.profiles.length, 3)
  assert.equal(library.profiles[0].name, '更新的接待員')
  assert.equal(library.profiles[2].name, '第三位數位人')
  assert.equal(library.handoff.return_announcement, '接下來請主數位人為您介紹。')
  assert.equal(library.handoff.return_announcement_en, 'Our main avatar will introduce our services.')
  assert.ok(textContent(view.root).includes('已儲存，尚未套用'))
  button(view.root, '儲存並套用').props.onClick()
  await settle()
  assert.equal(requests[0].expected_revision, 1)
  assert.equal(requests[1], 'apply')
  assert.equal(activeRevision, 2)
  assert.ok(textContent(view.root).includes('下一場對話採用'))
})

test('數位人設定檔只選擇伺服器設定的 LLM 端點，不能填寫服務網址', () => {
  const editor = readFileSync(new URL('../src/components/AvatarProfileEditor.vue', import.meta.url), 'utf8')
  assert.match(editor, /v-model="profile\.llm\.endpoint"/)
  assert.doesNotMatch(editor, /v-model="profile\.llm\.(base_url|provider)"/)
  const profiles = readFileSync(new URL('../src/components/AvatarProfiles.vue', import.meta.url), 'utf8')
  assert.match(profiles, /\['endpoint','model'\]/)
})

test('BreezyVoice 設定檔未選參考音檔時阻擋儲存並提示，不送出儲存或套用', async t => {
  const previousFetch = globalThis.fetch
  const makeProfile = (id, name, tts) => ({ id, name, avatar_id: 'shared_visual', engine: 'musetalk',
    llm: { endpoint: 'local', model: 'local-model' }, tts,
    rag: { enabled: false, dataset_ids: [], document_scope: 'all', document_ids: [] } })
  const library = { enabled: false, revision: 1, pair: { main: 'main', specialist: 'weather' }, transitions: [],
    handoff: { description: '', rules: '', announcement: '' }, weather: { county: '', town: '' },
    profiles: [makeProfile('main', '接待員', { type: 'edgetts', ref_file: 'zh-TW-HsiaoChenNeural' }),
      makeProfile('weather', '氣象員', { type: 'breezyvoice', ref_file: '' })] }
  const requests = []
  globalThis.fetch = async (url, options = {}) => {
    const result = data => ({ ok: true, json: async () => data })
    if (url === '/api/profiles' && options.method === 'GET') return result({ code: 0, library: structuredClone(library), runtime: { profiles_applied: true, active_revision: 1 }, media: [] })
    if (url === '/api/speech/voices') return result({ code: 0, data: { items: [] } })
    if (url === '/api/llm/models' || url === '/api/llm/rules') return result({ code: 0, data: {} })
    requests.push(url)
    return result({ code: 0, library, runtime: {} })
  }
  const view = mount(Component, {})
  t.after(() => { view.unmount(); globalThis.fetch = previousFetch })
  await settle()
  all(view.root, n => n.props.id === 'profile-name')[0].props.onInput({ target: { value: '新接待員' } })
  await settle()
  button(view.root, '儲存並套用').props.onClick()
  await settle()
  assert.deepEqual(requests, [])
  assert.match(textContent(view.root), /「氣象員」請選擇有逐字稿的參考音檔/)
  assert.equal(all(view.root, n => n.props.id === 'profile-name')[0].props.value, '氣象員', '切到需要修正的設定檔')
  assert.equal(openedSections.at(-1), 'voice')
  all(view.root, n => n.type === 'form')[0].props.onSubmit({ preventDefault() {} })
  await settle()
  assert.deepEqual(requests, [])
})
