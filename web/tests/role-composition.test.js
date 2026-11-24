// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// 角色組合與交接 (ADR 0023) rendered in memory against a small fake of the
// composition routes: each member, the main avatar and the transitions save
// on their own, and a version conflict stays with the one that caused it.
import assert from 'node:assert/strict'
import test from 'node:test'
import { loadComponent, mount, all, button, textContent, settle } from './helpers/componentHarness.js'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

const url = name => new URL(`../src/components/${name}`, import.meta.url)
const stubs = {
  './RoleHandoffFields.vue': { default: await loadComponent(url('RoleHandoffFields.vue')) },
  './RoleTopology.vue': { default: await loadComponent(url('RoleTopology.vue')) },
  './RoleTransitions.vue': { default: await loadComponent(url('RoleTransitions.vue')) }
}
const Composition = await loadComponent(url('RoleComposition.vue'), stubs)

const profile = (id, name, tts = 'edgetts') => ({ id, name, engine: 'musetalk', avatar_id: 'avatar_1',
  llm: { endpoint: 'local', model: 'gemma' }, tts: { type: tts, ref_file: 'zh-TW-HsiaoChenNeural' } })
const member = (profile_id, extra = {}) => ({ profile_id, revision: 2, enabled: true, description: '', rules: '',
  announcement: `請${profile_id}回答。`, announcement_en: '', tools: { weather: { enabled: false, county: '', town: '' } }, ...extra })

// The routes of ticket 01, enough to check what the console sends.
function server(t, setup = () => {}) {
  const previousFetch = globalThis.fetch
  const library = {
    version: 2, revision: 20, profiles_revision: 5,
    profiles: [profile('main', '接待員'), profile('weather', '氣象員'), profile('guide', '展覽導覽員'),
      profile('transit', '交通導覽', 'breezyvoice'), profile('shop', '客服小幫手')],
    composition: {
      revision: 4, enabled: true,
      main: { profile_id: 'main', revision: 3, description: '一般接待', rules: '', announcement: '請接待員回答。', announcement_en: '' },
      members: [member('weather', { tools: { weather: { enabled: true, county: '臺北市', town: '' } } }),
        member('guide'), member('transit')],
      transitions: { revision: 2, default: { kind: 'effect', effect: 'fade', duration: 0.6, asset_id: '' }, overrides: [] }
    }
  }
  const compatibility = { weather: [], guide: [], transit: ['即時組合需共用語音合成引擎，可分別設定聲線'], shop: [] }
  const requests = []
  const fail = { next: null }
  const dryRun = { next: { target: 'guide', target_name: '展覽導覽員', handoff: true, clarification: '', reason: '展品問題屬於導覽員', decided_by: 'model' } }
  const reply = (status, data) => ({ ok: status < 400, status, json: async () => data })
  const saved = () => reply(200, { code: 0, library: structuredClone(library), compatibility, runtime: { profiles_applied: true, active_revision: 20 } })
  const conflict = (scope, revision, current, extra = {}) => reply(409, { code: -1, msg: '已被其他控制台修改，請重新載入', conflict: { scope, revision, current: structuredClone(current), ...extra } })
  globalThis.fetch = async (path, options = {}) => {
    const method = options.method || 'GET'
    const body = options.body ? JSON.parse(options.body) : undefined
    requests.push({ path, method, body })
    if (fail.next) { const response = fail.next; fail.next = null; return response }
    const composition = library.composition
    const match = path.match(/^\/api\/profiles\/composition\/members\/(.+)$/)
    if (path === '/api/profiles' && method === 'GET') return reply(200, { code: 0, library: structuredClone(library), compatibility, media: [], runtime: { profiles_applied: true, active_revision: 20 } })
    if (match && method === 'PUT') {
      const stored = composition.members.find(m => m.profile_id === match[1])
      if (body.expected_revision !== stored.revision) return conflict('member', stored.revision, stored, { profile_id: stored.profile_id })
      Object.assign(stored, body.member, { revision: stored.revision + 1 })
    } else if (path === '/api/profiles/composition/main') {
      if (body.expected_revision !== composition.main.revision) return conflict('main', composition.main.revision, composition.main)
      Object.assign(composition.main, body.main, { revision: composition.main.revision + 1 })
    } else if (path === '/api/profiles/composition' && method === 'PUT') {
      if (body.expected_revision !== composition.revision) return conflict('composition', composition.revision, composition)
      Object.assign(composition, { enabled: body.enabled ?? composition.enabled, revision: composition.revision + 1 })
    } else if (path === '/api/profiles/composition/members' && method === 'POST') {
      composition.members.push({ ...member(body.member.profile_id), ...body.member, revision: 1 })
      composition.revision += 1
    } else if (path === '/api/profiles/composition/transitions') {
      if (body.expected_revision !== composition.transitions.revision) return conflict('transitions', composition.transitions.revision, composition.transitions)
      Object.assign(composition.transitions, body.transitions, { revision: composition.transitions.revision + 1 })
    } else if (path === '/api/profiles/composition/dry-run') {
      return reply(200, { code: 0, revision: library.revision, current_profile_id: body.current_profile_id, ...dryRun.next })
    } else throw Error(`Unexpected ${method} ${path}`)
    library.revision += 1
    return saved()
  }
  setup(library)
  const view = mount(Composition, {})
  t.after(() => { view.unmount(); globalThis.fetch = previousFetch })
  return { view, library, requests, fail, dryRun, conflict, writes: () => requests.filter(r => r.method !== 'GET') }
}

const slot = (root, name) => all(root, n => n.type === 'button' && n.props.class?.includes?.('rc-slot') && textContent(n).includes(name))[0]
const byId = (root, id) => all(root, n => n.props.id === id)[0]
async function open(root, name) { slot(root, name).props.onClick(); await settle() }
async function type(root, id, value) { byId(root, id).props['onUpdate:modelValue'](value); await settle() }

test('名單列出主數位人、啟用／不相容成員與空位，不相容原因來自伺服器', async t => {
  const { view } = server(t)
  await settle()
  const text = textContent(view.root)
  assert.match(text, /已啟用 3／5/)
  assert.match(textContent(slot(view.root, '接待員')), /開場／兜底/)
  assert.match(textContent(slot(view.root, '氣象員')), /已啟用.*天氣/)
  assert.match(textContent(slot(view.root, '交通導覽')), /不相容.*即時組合需共用語音合成引擎/)
  assert.equal(all(view.root, n => n.type === 'button' && textContent(n).includes('空位')).length, 2)
  await open(view.root, '交通導覽')
  assert.match(textContent(view.root), /無法啟用：與主數位人不相容/)
  // Saved as enabled before it became incompatible: it may be switched off, not on again.
  const enabled = () => byId(view.root, 'rc-member-enabled')
  assert.equal(enabled().props.disabled, false)
  assert.match(textContent(view.root), /已啟用 · 不相容，暫不參與/)
  enabled().props['onUpdate:modelValue'](false)
  await settle()
  assert.equal(enabled().props.disabled, true, '不相容者不能開啟')
  assert.match(textContent(view.root), /無法啟用/)
})

test('Matcha 設定檔的聲音顯示聲線模型名稱與使用限制標示', async t => {
  const { speech } = useRuntimeSettings()
  const previous = speech.tts.voice_models
  speech.tts.voice_models = [{ id: 'zh-tw-hsiaochen-edge', name: '曉臻（Edge 蒸餾）', usage: 'Development only', languages: ['zh-TW', 'en-US'], source: '' }]
  t.after(() => { speech.tts.voice_models = previous })
  const { view } = server(t, library => {
    for (const p of library.profiles.filter(p => ['main', 'guide'].includes(p.id))) p.tts = { type: 'matcha', ref_file: 'zh-tw-hsiaochen-edge' }
    library.profiles.find(p => p.id === 'weather').tts = { type: 'matcha', ref_file: 'removed-voice' }
  })
  await settle()
  assert.match(textContent(view.root), /Matcha-TTS · 曉臻（Edge 蒸餾） · Development only/, '主數位人的預設聲音')
  await open(view.root, '展覽導覽員')
  assert.match(textContent(view.root), /設定檔 guide · Matcha-TTS · 曉臻（Edge 蒸餾） · Development only/)
  await open(view.root, '氣象員')
  assert.match(textContent(view.root), /Matcha-TTS · removed-voice（未安裝的聲線模型）/)
})

test('每位成員各自儲存：只送自己的修訂，其他成員的草稿保留', async t => {
  const field = server(t)
  await settle()
  const { root } = field.view
  await open(root, '展覽導覽員')
  await type(root, 'rc-m-guide-rules', '展覽問題交給導覽員')
  await open(root, '氣象員')
  await type(root, 'rc-m-weather-rules', '天氣問題交給氣象員')
  assert.match(textContent(root), /2 處未儲存：氣象員、展覽導覽員/)
  button(root, '儲存這位').props.onClick()
  await settle()
  assert.deepEqual(field.writes().map(r => [r.method, r.path]), [['PUT', '/api/profiles/composition/members/weather']])
  const { body } = field.writes()[0]
  assert.equal(body.expected_revision, 2)
  assert.equal('expected_composition_revision' in body, false, '只改文字不檢查組合版本')
  assert.equal(body.member.rules, '天氣問題交給氣象員')
  assert.equal(field.library.composition.members[1].rules, '', '其他成員未被送出')
  assert.match(textContent(root), /1 處未儲存：展覽導覽員/)
  await open(root, '展覽導覽員')
  assert.equal(byId(root, 'rc-m-guide-rules').value, '展覽問題交給導覽員')
})

test('版本衝突只影響那一位：顯示另一個控制台的版本，可載入或以草稿覆寫', async t => {
  const field = server(t)
  await settle()
  const { root } = field.view
  await open(root, '展覽導覽員')
  await type(root, 'rc-m-guide-rules', '我的草稿')
  await open(root, '氣象員')
  await type(root, 'rc-m-weather-rules', '我的天氣規則')
  // Another console saved this member meanwhile.
  Object.assign(field.library.composition.members[0], { rules: '另一個控制台的規則', revision: 3 })
  button(root, '儲存這位').props.onClick()
  await settle()
  assert.match(textContent(root), /儲存失敗：「氣象員」已被另一個控制台更新/)
  assert.match(textContent(root), /其他成員不受影響/)
  assert.match(textContent(slot(root, '展覽導覽員')), /未儲存/, '其他位的草稿不受影響')
  assert.equal(byId(root, 'rc-m-weather-rules').value, '我的天氣規則', '草稿仍保留')
  button(root, '以草稿覆寫').props.onClick()
  await settle()
  const last = field.writes().at(-1)
  assert.equal(last.body.expected_revision, 3, '覆寫時以伺服器回報的新版本為基準')
  assert.equal(field.library.composition.members[0].rules, '我的天氣規則')
  assert.equal(field.writes().filter(r => r.path.endsWith('/guide')).length, 0)
})

test('主數位人與成員有相同的交接欄位；交接說明必填，交接開關另存組合', async t => {
  const field = server(t)
  await settle()
  const { root } = field.view
  await open(root, '接待員')
  await type(root, 'rc-main-announcement', '  ')
  button(root, '儲存這位').props.onClick()
  await settle()
  assert.equal(field.writes().length, 0, '空白交接說明不送出')
  assert.match(textContent(root), /請填寫中文交接說明/)
  assert.equal(byId(root, 'rc-main-announcement').props['aria-invalid'], true)
  await type(root, 'rc-main-announcement', '其他問題我請接待員回答。')
  byId(root, 'rc-handoff').props['onUpdate:modelValue'](false)
  await settle()
  button(root, '儲存這位').props.onClick()
  await settle()
  assert.deepEqual(field.writes().map(r => [r.path, r.body.expected_revision]), [
    ['/api/profiles/composition/main', 3], ['/api/profiles/composition', 4]])
  assert.equal(field.library.composition.main.announcement, '其他問題我請接待員回答。')
  assert.equal(field.library.composition.enabled, false)
  assert.match(textContent(root), /角色交接已關閉/)
})

test('天氣工具同時只限一位；場域預設地點屬於持有者', async t => {
  const field = server(t)
  await settle()
  const { root } = field.view
  await open(root, '展覽導覽員')
  assert.equal(byId(root, 'rc-member-weather').props.disabled, true)
  assert.match(textContent(root), /天氣工具目前由「氣象員」提供/)
  await open(root, '氣象員')
  await type(root, 'rc-weather-town', '台北市中正區')
  button(root, '儲存這位').props.onClick()
  await settle()
  assert.equal(field.writes()[0].body.member.tools.weather.town, '臺北市中正區')
})

test('加入專門數位人：選設定檔後預設未啟用，儲存時才建立', async t => {
  const field = server(t)
  await settle()
  const { root } = field.view
  button(root, '加入專門數位人').props.onClick()
  await settle()
  const add = all(root, n => n.props.class?.includes?.('rc-cand') && textContent(n).includes('客服小幫手'))[0]
  button(add, '加入').props.onClick()
  await settle()
  assert.match(textContent(root), /新加入，尚未儲存/)
  assert.equal(field.writes().length, 0)
  button(root, '儲存這位').props.onClick()
  await settle()
  const [request] = field.writes()
  assert.deepEqual([request.method, request.path, request.body.expected_revision, request.body.member.enabled],
    ['POST', '/api/profiles/composition/members', 4, false])
  assert.match(textContent(slot(root, '客服小幫手')), /未啟用 · 保留設定/)
})

test('角色轉場：預設＋個別方向，重複方向不新增，另存轉場修訂', async t => {
  const field = server(t)
  await settle()
  const { root } = field.view
  const pick = async (label, value) => { all(root, n => n.type === 'select' && n.props['aria-label'] === label)[0].props['onUpdate:modelValue'](value); await settle() }
  for (let i = 0; i < 2; i++) {
    await pick('來源角色', 'main')
    await pick('目的角色', 'guide')
    button(root, '新增').props.onClick()
    await settle()
  }
  assert.match(textContent(root), /「接待員 → 展覽導覽員」已有個別設定/)
  button(root, '儲存轉場').props.onClick()
  await settle()
  const [request] = field.writes()
  assert.equal(request.path, '/api/profiles/composition/transitions')
  assert.equal(request.body.expected_revision, 2)
  assert.deepEqual(request.body.transitions.overrides.map(e => [e.source, e.target]), [['main', 'guide']])
})

test('交接試算以已儲存的組合詢問路由並顯示由誰回答與原因', async t => {
  const field = server(t)
  await settle()
  const { root } = field.view
  const block = () => byId(root, 'rc-dry-run')
  assert.match(textContent(block()), /交接試算.*已儲存版本 20/)
  const options = all(byId(root, 'rc-sim-from'), n => n.type === 'option').map(textContent)
  assert.deepEqual(options, ['接待員', '氣象員', '展覽導覽員'], '只列主數位人與生效成員')
  assert.equal(button(block(), '試算由誰回答').props.disabled, true, '沒有問題時不能試算')
  await type(root, 'rc-sim-from', 'weather')
  await type(root, 'rc-sim-question', '這件展品的故事是什麼？')
  block().props.onSubmit({ preventDefault() {} })
  await settle()
  const [request] = field.requests.filter(r => r.path.includes('dry-run'))
  assert.equal(request.method, 'POST')
  assert.deepEqual(request.body, { current_profile_id: 'weather', text: '這件展品的故事是什麼？' })
  assert.match(textContent(block()), /交給展覽導覽員.*展品問題屬於導覽員（模型判斷）/)
  assert.ok(field.writes().every(r => r.path.includes('dry-run')), '試算不儲存任何設定')

  field.dryRun.next = { target: null, target_name: '', handoff: false, clarification: '請問您想先問天氣還是展覽？', reason: '混合主題', decided_by: 'model' }
  block().props.onSubmit({ preventDefault() {} })
  await settle()
  assert.match(textContent(block()), /先向訪客釐清：請問您想先問天氣還是展覽？/)

  field.fail.next = { ok: false, status: 503, json: async () => ({ code: -1, msg: '回答模型服務暫時無法使用' }) }
  block().props.onSubmit({ preventDefault() {} })
  await settle()
  assert.match(textContent(block()), /回答模型服務暫時無法使用/)
})

test('沒有生效成員時交接試算停用並說明原因', async t => {
  const field = server(t, library => { library.composition.enabled = false })
  await settle()
  const block = byId(field.view.root, 'rc-dry-run')
  assert.match(textContent(block), /至少啟用一位相容的專門數位人/)
  assert.ok(all(block, n => ['select', 'input', 'button'].includes(n.type)).every(n => n.props.disabled === true))
  assert.ok(field.requests.every(r => !r.path.includes('dry-run')))
})
