// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { canRoleInput, canRoleReturn, directedTransition } from '../src/roleState.js'

test('同時只有指定頁面能輸入，轉場及套用期間關閉兩端輸入', () => {
  const role = { enabled: true, phase: 'ready', mode: 'visitor' }
  assert.equal(canRoleInput(role, 'stage'), true)
  assert.equal(canRoleInput(role, 'console'), false)
  role.mode = 'console'
  assert.equal(canRoleInput(role, 'stage'), false)
  assert.equal(canRoleInput(role, 'console'), true)
  for (const phase of ['transition', 'disabled']) {
    assert.equal(canRoleInput({ ...role, phase }, 'console'), false)
  }
  assert.equal(canRoleInput({ ...role, applying: true }, 'console'), false)
  assert.equal(canRoleInput({ enabled: false, applying: true }, 'console'), false)
  assert.equal(canRoleInput({ ...role, phase: 'announcement' }, 'console'), true)
})

test('返回僅在專門角色就緒時可操作，正反向轉場分開保存', () => {
  assert.equal(canRoleReturn({ enabled: true, can_return: true, phase: 'ready' }), true)
  assert.equal(canRoleReturn({ enabled: true, can_return: true, phase: 'transition' }), false)
  const library = { transitions: [] }
  const forward = directedTransition(library, 'main', 'weather')
  forward.kind = 'video'
  forward.asset_id = 'example'
  const reverse = directedTransition(library, 'weather', 'main')
  assert.equal(reverse.kind, 'effect')
  assert.equal(reverse.effect, 'fade')
  assert.equal(directedTransition(library, 'main', 'weather'), forward)
  assert.equal(library.transitions.length, 2)
})


test('單角色啟用閒置招呼時仍遵守訪客／控制台輸入模式', () => {
  const role = { enabled: false, input_mode_managed: true, phase: 'disabled', mode: 'visitor' }
  assert.equal(canRoleInput(role, 'stage'), true)
  assert.equal(canRoleInput(role, 'console'), false)
  assert.equal(canRoleInput({ ...role, mode: 'console' }, 'stage'), false)
  assert.equal(canRoleInput({ ...role, mode: 'console' }, 'console'), true)
  assert.equal(canRoleInput({ ...role, applying: true }, 'stage'), false)
})
