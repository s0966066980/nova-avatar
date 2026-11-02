// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { canRoleInput, canRoleReturn } from '../src/roleState.js'

test('每一頁只依自己的角色狀態決定能否輸入', () => {
  for (const presenter of ['console', 'stage']) {
    for (const phase of ['ready', 'announcement', 'disabled']) {
      assert.equal(canRoleInput({ enabled: true, phase }, presenter), true)
    }
    assert.equal(canRoleInput({ enabled: true, phase: 'transition' }, presenter), false)
    assert.equal(canRoleInput({ phase: 'ready', applying: true }, presenter), false)
  }
})

test('返回僅在專門角色就緒時可操作', () => {
  assert.equal(canRoleReturn({ enabled: true, can_return: true, phase: 'ready' }), true)
  assert.equal(canRoleReturn({ enabled: true, can_return: true, phase: 'transition' }), false)
})

test('單角色與招呼不再引入跨頁輸入權', () => {
  for (const presenter of ['console', 'stage']) {
    assert.equal(canRoleInput({ enabled: false, phase: 'disabled' }, presenter), true)
  }
})
