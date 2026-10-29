// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { kioskReconnectDelayMs, KIOSK_UNAVAILABLE_TITLE } from '../src/stageKiosk.js'
import { stageText } from '../src/stageLocale.js'
import {
  STAGE_CONNECT_TIMEOUT_MS,
  STAGE_OFFER_TIMEOUT_MS,
  STAGE_POLL_TIMEOUT_MS
} from '../src/stageConnection.js'
import { flush, stageHarness } from './helpers/stageHarness.js'

const never = () => new Promise(() => {})
const RETRY_MS = kioskReconnectDelayMs(0)
const offerCount = stage => stage.fetchCalls.filter(url => url === '/offer').length

function assertRetryVisible(stage, title) {
  assert.equal(stage.element('veil').hidden, false)
  assert.equal(stage.element('veilTitle').textContent, title)
  assert.equal(stage.element('veilBtn').hidden, false, '逾時後必須露出重試按鈕')
  assert.equal(stage.pending(RETRY_MS).length, 1, '逾時後必須排程自動重連')
}

test('後端接受 /offer 卻不回應時，逾時後顯示重試並自動重連', async () => {
  let offers = 0
  const stage = stageHarness({ respond: url => (url === '/offer' && offers++ === 0 ? never() : null) })
  const entering = stage.element('veilBtn').onclick()
  await flush()
  assert.equal(stage.element('veilTitle').textContent, '連線中')
  assert.equal(stage.element('veilBtn').hidden, true)

  await stage.elapse(STAGE_OFFER_TIMEOUT_MS)
  await entering
  assertRetryVisible(stage, '連線逾時')

  await stage.elapse(RETRY_MS)
  assert.equal(offerCount(stage), 2)
})

test('offer 成功但 WebRTC 一直未連上時，看門狗逾時後顯示重試並自動重連', async () => {
  const stage = stageHarness()
  await stage.element('veilBtn').onclick()
  assert.equal(stage.element('veilBtn').hidden, true)
  const stuckPeer = stage.peer

  await stage.elapse(STAGE_CONNECT_TIMEOUT_MS)
  assertRetryVisible(stage, '連線逾時')
  assert.equal(stuckPeer.closed, true)

  await stage.elapse(RETRY_MS)
  assert.equal(offerCount(stage), 2)
  assert.notEqual(stage.peer, stuckPeer)
})

test('kiosk 卡在連線中時同樣逾時重連，並顯示 kiosk 提示', async () => {
  const stage = stageHarness({ search: '?kiosk=1' })
  await flush()
  await stage.elapse(STAGE_CONNECT_TIMEOUT_MS)
  assertRetryVisible(stage, KIOSK_UNAVAILABLE_TITLE)
  await stage.elapse(RETRY_MS)
  assert.equal(offerCount(stage), 2)
})

test('連上後解除連線看門狗', async () => {
  const stage = stageHarness()
  await stage.connect()
  assert.equal(stage.pending(STAGE_CONNECT_TIMEOUT_MS).length, 0)
  assert.equal(stage.element('veil').hidden, true)
})

test('設定輪詢卡住時，逾時後仍繼續建立連線', async () => {
  const stage = stageHarness({ respond: url => (url === '/api/vad' || url === '/api/stage' ? never() : null) })
  const entering = stage.element('veilBtn').onclick()
  await flush()
  assert.equal(offerCount(stage), 0)
  for (let round = 0; round < 3 && offerCount(stage) === 0; round += 1) {
    await stage.elapse(STAGE_POLL_TIMEOUT_MS)
  }
  await entering
  assert.equal(offerCount(stage), 1)
})

test('看門狗逾時時仍在等麥克風，舊嘗試稍後取得的音軌會釋放且不送出 offer', async () => {
  let release
  let calls = 0
  const stage = stageHarness({
    getUserMedia: stream => (calls++ === 0 ? new Promise(resolve => { release = () => resolve(stream) }) : stream),
  })
  const entering = stage.element('veilBtn').onclick()
  await flush()
  await stage.elapse(STAGE_CONNECT_TIMEOUT_MS)
  release()
  await entering
  await flush()
  assert.equal(stage.track.stopped, true)
  assert.equal(offerCount(stage), 0)
  assertRetryVisible(stage, '連線逾時')
})

for (const kind of ['close', 'error']) {
  test(`data channel ${kind} 而影像仍在時，停用互動並自動重連`, async () => {
    const stage = stageHarness()
    await stage.connect()
    stage.channel[`on${kind}`]()
    assert.equal(stage.element('mic').disabled, true)
    assert.equal(stage.element('veil').hidden, false)
    assert.equal(stage.element('veilBtn').hidden, false)
    assert.equal(stage.pending(RETRY_MS).length, 1)
    await stage.elapse(RETRY_MS)
    assert.equal(offerCount(stage), 2)
  })
}

test('同一連線已處理中斷後，隨後的 data channel 關閉不再重複處理', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.peerState('failed')
  const timersBefore = stage.timers.length
  stage.channel.onclose?.()
  stage.channel.onerror?.()
  assert.equal(stage.timers.length, timersBefore)
  assert.equal(stage.element('veilTitle').textContent, '連線中斷')
})

test('kiosk 連線失敗後通道關閉不會額外拉長退避時間', async () => {
  const stage = stageHarness({ search: '?kiosk=1' })
  await flush()
  stage.peerState('connected')
  stage.peerState('failed')
  stage.channel.onclose?.()
  assert.equal(stage.pending(kioskReconnectDelayMs(0)).length, 1)
  assert.equal(stage.pending(kioskReconnectDelayMs(1)).length, 0)
})

test('逾時提示有英文介面文字', () => {
  for (const text of ['連線逾時', '連線時間過長，正在自動重新連線。']) {
    assert.notEqual(stageText(text, 'en-US'), text)
  }
})

test('npm run lint 涵蓋 stage.html 的 inline 舞台腳本', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
  assert.match(pkg.scripts.lint, /(^|\s)stage\.html(\s|$)/)
  const config = readFileSync(new URL('../eslint.config.js', import.meta.url), 'utf8')
  assert.match(config, /eslint-plugin-html/)
  assert.match(config, /stage\.html/)
})

test('舞台腳本的所有請求都經過逾時包裝', () => {
  const html = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
  const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1]
  assert.doesNotMatch(script, /(^|[^\w.])fetch\(/m)
  assert.equal((script.match(/fetchJsonWithTimeout\(/g) || []).length, 3)
})
