// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { canRoleInput, canRoleReturn, directedTransition } from '../src/roleState.js'

test('每一頁只依自己的角色狀態決定能否輸入', () => {
  for (const presenter of ['console', 'stage']) {
    for (const phase of ['ready', 'announcement', 'disabled']) {
      assert.equal(canRoleInput({ enabled: true, phase }, presenter), true)
    }
    assert.equal(canRoleInput({ enabled: true, phase: 'transition' }, presenter), false)
    assert.equal(canRoleInput({ phase: 'ready', applying: true }, presenter), false)
  }
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


test('單角色與招呼不再引入跨頁輸入權', () => {
  for (const presenter of ['console', 'stage']) {
    assert.equal(canRoleInput({ enabled: false, phase: 'disabled' }, presenter), true)
  }
})
