// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  MAX_ENABLED, enabledCount, isDirty, liveMemberIds, newMemberScope, readFailure, reconcile, ringLayout,
  savePlan, scopesFrom, weatherHolder
} from '../src/roles/roleComposition.js'

const member = (profile_id, extra = {}) => ({
  profile_id, revision: 1, enabled: true, description: '', rules: '', announcement: `交給${profile_id}`, announcement_en: '',
  tools: { weather: { enabled: false, county: '', town: '' } }, ...extra
})
const library = (members = [member('weather'), member('transit')], extra = {}) => ({
  version: 2, revision: 10, profiles_revision: 4,
  profiles: [{ id: 'main', name: '接待員' }, { id: 'weather', name: '天氣助手' }, { id: 'transit', name: '交通導覽' }, { id: 'shop', name: '客服' }],
  composition: {
    revision: 3, enabled: true,
    main: { profile_id: 'main', revision: 2, description: '', rules: '', announcement: '請主數位人回答。', announcement_en: '' },
    members,
    transitions: { revision: 1, default: { kind: 'effect', effect: 'fade', duration: 0.6, asset_id: '' }, overrides: [] }
  },
  ...extra
})

test('每位成員、主數位人與轉場各自一份草稿，只有被編輯的那一份變成未儲存', () => {
  const scopes = scopesFrom(library())
  assert.deepEqual(Object.keys(scopes.members), ['weather', 'transit'])
  assert.equal(scopes.main.draft.enabled, true, '主數位人草稿含角色交接開關')
  scopes.members.weather.draft.rules = '天氣問題交給這位'
  assert.equal(isDirty(scopes.members.weather), true)
  assert.equal(isDirty(scopes.members.transit), false)
  assert.equal(isDirty(scopes.main), false)
  assert.equal(isDirty(scopes.transitions), false)
})

test('重新整理時保留未儲存的草稿與它原本的修訂版本，其他位改用伺服器的新內容', () => {
  const scopes = scopesFrom(library())
  scopes.members.weather.draft.rules = '我的草稿'
  const fresh = library([member('weather', { revision: 5, rules: '另一個控制台' }), member('transit', { revision: 2, rules: '新規則' })])
  const next = reconcile(scopes, fresh)
  assert.equal(next.members.weather.draft.rules, '我的草稿')
  assert.equal(next.members.weather.base.revision, 1, '草稿仍以原本的修訂版本儲存，伺服器才能偵測衝突')
  assert.equal(next.members.transit.draft.rules, '新規則')
  assert.equal(next.members.transit.base.revision, 2)
  const removed = reconcile(next, library([member('weather', { revision: 5 })]))
  assert.equal(removed.members.transit, undefined, '移出且沒有草稿的成員不再顯示')
  assert.ok(removed.members.weather, '有草稿的成員保留')
})

test('儲存計畫：成員只送自己的修訂；改啟用或換設定檔才附組合修訂', () => {
  const lib = library()
  const scopes = scopesFrom(lib)
  const weather = scopes.members.weather
  weather.draft.rules = '新規則'
  assert.deepEqual(savePlan(weather, lib), [{ path: '/composition/members/weather', method: 'PUT',
    body: { expected_revision: 1, member: { ...weather.draft } } }])
  weather.draft.enabled = false
  assert.equal(savePlan(weather, lib)[0].body.expected_composition_revision, 3)
  weather.draft.tools.weather.town = '台北'
  assert.equal(savePlan(weather, lib)[0].body.member.tools.weather.town, '臺北', '台 一律改為 臺')

  const main = scopes.main
  main.draft.announcement = '交回接待員。'
  main.draft.enabled = false
  assert.deepEqual(savePlan(main, lib), [
    { path: '/composition/main', method: 'PUT', body: { expected_revision: 2, main: {
      description: '', rules: '', announcement: '交回接待員。', announcement_en: '' } } },
    { path: '/composition', method: 'PUT', body: { expected_revision: 3, enabled: false } }
  ])

  const fresh = newMemberScope('shop', '客服')
  assert.equal(fresh.draft.enabled, false, '新加入預設未啟用')
  assert.match(fresh.draft.announcement, /客服/)
  assert.deepEqual(savePlan(fresh, lib), [{ path: '/composition/members', method: 'POST',
    body: { expected_revision: 3, member: fresh.draft } }])

  scopes.transitions.draft.overrides.push({ source: 'main', target: 'weather', kind: 'effect', effect: 'zoom', duration: 1, asset_id: '' })
  assert.deepEqual(savePlan(scopes.transitions, lib), [{ path: '/composition/transitions', method: 'PUT',
    body: { expected_revision: 1, transitions: scopes.transitions.draft } }])
})

test('生效中的成員：交接開啟、成員啟用且與主數位人相容；天氣工具同時只限一位', () => {
  const lib = library([member('weather', { tools: { weather: { enabled: true, county: '臺北市', town: '' } } }),
    member('transit'), member('shop', { enabled: false })])
  assert.deepEqual(liveMemberIds(lib, { transit: ['語音合成引擎不同'] }), ['weather'])
  assert.equal(enabledCount(lib), 2)
  assert.equal(MAX_ENABLED, 5)
  assert.equal(weatherHolder(lib), 'weather')
  assert.deepEqual(liveMemberIds({ ...lib, composition: { ...lib.composition, enabled: false } }, {}), [])
})

test('伺服器錯誤轉為欄位錯誤、版本衝突或需確認停用的成員', () => {
  const failure = (status, data) => Object.assign(new Error(data.msg), { status, data })
  assert.deepEqual(readFailure(failure(400, { msg: '交接說明不可空白', field: 'announcement' })),
    { message: '交接說明不可空白', field: 'announcement', conflict: null, reasons: [], disableRequired: [] })
  const conflict = readFailure(failure(409, { msg: '已被其他控制台修改', conflict: { scope: 'member', revision: 4, current: member('weather') } }))
  assert.equal(conflict.conflict.scope, 'member')
  assert.deepEqual(readFailure(failure(409, { msg: '不相容', field: 'main', disable_required: ['transit'] })).disableRequired, ['transit'])
  assert.equal(readFailure(new Error('網路中斷')).message, '網路中斷')
})

test('交接路線的節點環狀排列：主數位人在正上方，其他依序分布', () => {
  const nodes = ringLayout(6, { cx: 150, cy: 110, r: 70 })
  assert.equal(nodes.length, 6)
  assert.deepEqual([Math.round(nodes[0].x), Math.round(nodes[0].y)], [150, 40])
  const distances = nodes.map(n => Math.hypot(n.x - 150, n.y - 110))
  assert.ok(distances.every(d => Math.abs(d - 70) < 1e-6))
  assert.ok(nodes[1].x > 150 && nodes[5].x < 150, '順時針排列')
})
