// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import { isKioskMode, kioskReconnectDelayMs } from '../src/stageKiosk.js'

test('只有 kiosk=1 才進入 kiosk 模式', () => {
  assert.equal(isKioskMode('?kiosk=1'), true)
  assert.equal(isKioskMode('?a=b&kiosk=1'), true)
  for (const search of ['', '?kiosk=0', '?kiosk=true', '?kiosk', undefined, null]) {
    assert.equal(isKioskMode(search), false, String(search))
  }
})

test('重連延遲逐步拉長並設上限', () => {
  const delays = [0, 1, 2, 3, 4, 5, 50].map(kioskReconnectDelayMs)
  assert.deepEqual(delays, [2000, 3000, 5000, 8000, 10000, 10000, 10000])
  assert.equal(kioskReconnectDelayMs(-1), 2000)
  assert.equal(kioskReconnectDelayMs(Number.NaN), 2000)
})
