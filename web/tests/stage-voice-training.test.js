// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// 聲線訓練進行中，後端以 409／voice_training_active 拒絕舞台 offer（規格決定 14）。
// 舞台要顯示暫停服務的說明並照重連節奏自動重試，訓練結束後自己連上。
import assert from 'node:assert/strict'
import test from 'node:test'
import { kioskReconnectDelayMs } from '../src/stageKiosk.js'
import { stageText } from '../src/stageLocale.js'
import { flush, stageHarness } from './helpers/stageHarness.js'

const PAUSED = '聲線訓練進行中，數位人暫停服務'
const never = () => new Promise(() => {})
const offerCount = stage => stage.fetchCalls.filter(url => url === '/offer').length
const training = () => ({
  ok: false, status: 409,
  json: async () => ({ code: -1, reason: 'voice_training_active', msg: PAUSED })
})

function trainingUntil(offers, respondAfter = null) {
  let count = 0
  return url => {
    if (url !== '/offer') return null
    count += 1
    return count <= offers ? training() : respondAfter?.()
  }
}

for (const search of ['', '?kiosk=1']) {
  test(`訓練中的舞台${search ? '（kiosk）' : ''}顯示暫停服務，不當成錯誤，並依重連節奏自動重試`, async () => {
    const stage = stageHarness({ search, respond: trainingUntil(2) })
    if (!search) await stage.element('veilBtn').onclick()
    await flush()
    assert.equal(stage.element('veil').hidden, false)
    assert.equal(stage.element('veilTitle').textContent, PAUSED)
    assert.equal(stage.element('veilBtn').hidden, true, '不需要現場人員按重試')
    assert.equal(stage.element('veilAlt').hidden, true)
    assert.equal(stage.pending(kioskReconnectDelayMs(0)).length, 1)

    await stage.elapse(kioskReconnectDelayMs(0))
    assert.equal(offerCount(stage), 2)
    assert.equal(stage.element('veilTitle').textContent, PAUSED, '重試時說明保持不變')
    assert.equal(stage.pending(kioskReconnectDelayMs(1)).length, 1)

    // 訓練結束：下一次重試自動連上。
    await stage.elapse(kioskReconnectDelayMs(1))
    assert.equal(offerCount(stage), 3)
    stage.peerState('connected')
    assert.equal(stage.element('veil').hidden, true)
  })
}

test('重試的 offer 還在等回應時，畫面仍是暫停服務的說明，不閃回「連線中」', async () => {
  const stage = stageHarness({ respond: trainingUntil(1, never) })
  await stage.element('veilBtn').onclick()
  await stage.elapse(kioskReconnectDelayMs(0))
  assert.equal(offerCount(stage), 2)
  assert.equal(stage.element('veilTitle').textContent, PAUSED)
})

test('其他 409 原因仍顯示原本的「尚未就緒」', async () => {
  const stage = stageHarness({
    respond: url => (url === '/offer'
      ? { ok: false, status: 409, json: async () => ({ code: -1, msg: '請先在設定中選擇並套用數字人引擎與角色' }) }
      : null)
  })
  await stage.element('veilBtn').onclick()
  assert.equal(stage.element('veilTitle').textContent, '數字人尚未就緒')
})

test('暫停服務的說明有英文介面文字', () => {
  assert.equal(stageText(PAUSED, 'en-US'), 'Voice training in progress. The avatar is paused.')
  assert.notEqual(stageText('訓練結束後會自動連線，請稍候。', 'en-US'), '訓練結束後會自動連線，請稍候。')
})
