// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  kioskReconnectDelayMs,
  KIOSK_UNAVAILABLE_TITLE,
  KIOSK_UNAVAILABLE_TEXT
} from '../src/stageKiosk.js'
import { flush, stageHarness } from './helpers/stageHarness.js'

test('啟用文字附件的舞台進入後也會自動收音，不必再點麥克風', async () => {
  const stage = stageHarness({ composerEnabled: true })
  await stage.connect()
  assert.equal(stage.microphoneRequests.length, 1)
  assert.equal(stage.offers[0].has_microphone, true)
  assert.equal(stage.track.enabled, true)
  assert.deepEqual(stage.sent.filter(message => message.type === 'capture').at(-1), {
    type: 'capture', enabled: true, finalize: false, manual_pause: false
  })
})

test('舞台拒絕麥克風權限時仍可連線使用文字附件', async () => {
  const stage = stageHarness({ composerEnabled: true, microphoneDenied: true })
  await stage.connect()
  assert.equal(stage.microphoneRequests.length, 1)
  assert.equal(stage.offers[0].has_microphone, false)
  assert.equal(stage.track.enabled, false)
  assert.equal(stage.sent.some(message => message.type === 'capture' && message.enabled), false)
  assert.equal(stage.element('veil').hidden, true)
})

test('舞台暫停後重新進入會恢復自動收音', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.element('mic').dispatch('pointerdown')
  stage.element('mic').dispatch('pointerup')
  assert.equal(stage.track.enabled, false)
  stage.peerState('failed')
  await stage.connect()
  assert.equal(stage.track.enabled, true)
  assert.deepEqual(stage.sent.filter(message => message.type === 'capture').at(-1), {
    type: 'capture', enabled: true, finalize: false, manual_pause: false
  })
})

test('舞台插話的按下與鬆開不會在多輪後關閉收音', async () => {
  const stage = stageHarness()
  await stage.connect()
  const mic = stage.element('mic')

  for (let turn = 1; turn <= 3; turn += 1) {
    stage.event({ seq: turn * 2 - 1, type: 'speaking_start', turn_id: `turn-${turn}` })
    mic.dispatch('pointerdown')
    assert.deepEqual(stage.sent.at(-1), { type: 'interrupt' })
    stage.event({ seq: turn * 2, type: 'turn_cancelled', turn_id: `turn-${turn}` })
    mic.dispatch('pointerup')
    assert.equal(stage.track.enabled, true, `插話第 ${turn} 輪後音軌仍需收音`)
    assert.notEqual(stage.sent.at(-1)?.enabled, false, `插話第 ${turn} 輪後伺服器仍需收音`)
  }
})

test('暫停中的舞台插話會同步恢復前後端收音狀態', async () => {
  const stage = stageHarness()
  await stage.connect()
  const mic = stage.element('mic')
  mic.dispatch('pointerdown')
  mic.dispatch('pointerup')
  assert.equal(stage.track.enabled, false)

  stage.event({ seq: 1, type: 'speaking_start', turn_id: 'text-turn' })
  mic.dispatch('pointerdown')
  stage.event({ seq: 2, type: 'turn_cancelled', turn_id: 'text-turn' })
  mic.dispatch('pointerup')

  assert.equal(stage.track.enabled, true)
  assert.equal(stage.element('hint').textContent, '直接說話')
  assert.deepEqual(stage.sent.slice(-2), [
    { type: 'capture', enabled: true, finalize: false, manual_pause: false },
    { type: 'interrupt' },
  ])
})

test('一般開啟舞台時維持點擊進入，不會自動連線', async () => {
  const stage = stageHarness()
  await flush()
  assert.equal(stage.fetchCalls.includes('/offer'), false)
})

test('kiosk 標記開啟舞台時不需點擊就自動連線', async () => {
  const stage = stageHarness({ search: '?kiosk=1' })
  await flush()
  assert.equal(stage.fetchCalls.includes('/offer'), true)
})

test('kiosk 連線中斷時顯示簡短提示並自動重連', async () => {
  const stage = stageHarness({ search: '?kiosk=1' })
  await flush()
  stage.peerState('failed')

  assert.equal(stage.element('veilTitle').textContent, KIOSK_UNAVAILABLE_TITLE)
  assert.equal(stage.element('veilText').textContent, KIOSK_UNAVAILABLE_TEXT)
  const retry = stage.timers.at(-1)
  assert.equal(retry.ms, kioskReconnectDelayMs(0))

  const offers = () => stage.fetchCalls.filter((url) => url === '/offer').length
  const before = offers()
  retry.fn()
  await flush()
  assert.equal(offers(), before + 1)
})

test('一般舞台連線中斷仍顯示原本的重新連線畫面且不自動重連', async () => {
  const stage = stageHarness()
  await stage.connect()
  const timersBefore = stage.timers.length
  stage.peerState('failed')

  assert.equal(stage.element('veilTitle').textContent, '連線中斷')
  assert.equal(stage.timers.length, timersBefore)
})

test('對話重置事件清除舞台字幕、看板與使用者字句，但不斷線也不關收音', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.event({ seq: 1, type: 'user_transcript', text: '上一位訪客的問題' })
  assert.equal(stage.element('said').textContent, '上一位訪客的問題')

  stage.event({ seq: 2, type: 'conversation_reset' })

  assert.equal(stage.element('said').textContent, '')
  assert.equal(stage.element('hint').textContent, '直接說話')
  assert.equal(stage.track.enabled, true)
  assert.equal(stage.element('veil').hidden, true)
})

test('舞台忽略舊同步展示事件並保持自己的收音及問答', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.event({ seq: 1, type: 'role_state', enabled: true, phase: 'ready' })
  stage.event({ seq: 2, type: 'user_transcript', turn_id: 'console-turn', text: '控制台的問題', mirrored: true })
  stage.event({ seq: 3, type: 'assistant_fragment', turn_id: 'console-turn', text: '控制台回答', mirrored: true })
  assert.equal(stage.element('said').textContent, '')
  assert.equal(stage.element('reply').textContent, '')
  assert.equal(stage.track.enabled, true)
  assert.equal(stage.element('mic').disabled, false)
  stage.event({ seq: 4, type: 'user_transcript', turn_id: 'stage-turn', text: '舞台問題' })
  stage.event({ seq: 5, type: 'assistant_fragment', turn_id: 'stage-turn', text: '舞台回答' })
  assert.equal(stage.element('said').textContent, '舞台問題')
  assert.equal(stage.element('reply').textContent, '舞台回答')
})

test('只有此場角色轉場才暫停舞台收音，恢復時不重建連線', async () => {
  const stage = stageHarness()
  await stage.connect()
  const offers = stage.fetchCalls.filter(url => url === '/offer').length
  stage.event({ seq: 1, type: 'role_state', enabled: true, phase: 'ready', mode: 'console' })
  assert.equal(stage.track.enabled, true)
  assert.equal(stage.element('mic').disabled, false)
  stage.event({ seq: 2, type: 'role_state', enabled: true, phase: 'transition', mode: 'visitor' })
  assert.equal(stage.track.enabled, false)
  stage.event({ seq: 3, type: 'role_state', enabled: true, phase: 'ready', mode: 'visitor', can_return: true })
  assert.equal(stage.track.enabled, true)
  assert.equal(stage.element('mic').disabled, false)
  assert.equal(stage.element('roleReturn').hidden, false)
  stage.element('roleReturn').dispatch('click')
  assert.deepEqual(stage.sent.at(-1), { type: 'role_return' })
  assert.equal(stage.fetchCalls.filter(url => url === '/offer').length, offers)
})

test('轉場清畫面後保留連線，返回主角色時隱藏返回按鈕', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.event({ seq: 1, type: 'user_transcript', text: '明天的天氣' })
  stage.event({ seq: 2, type: 'role_clear' })
  assert.equal(stage.element('said').textContent, '')
  assert.equal(stage.element('veil').hidden, true)
  stage.event({ seq: 3, type: 'role_state', enabled: true, phase: 'ready', mode: 'visitor', can_return: false })
  assert.equal(stage.element('roleReturn').hidden, true)
})


test('招呼就緒回報要求有聲播放、麥克風與未手動暫停，斷線立即撤銷', async () => {
  const stage = stageHarness()
  await stage.connect()
  const ready = () => stage.sent.filter(message => message.type === 'stage_ready').at(-1)
  assert.equal(ready().audible, true)
  assert.equal(ready().microphone, true)
  assert.equal(ready().interaction, true)
  stage.element('video').muted = true
  stage.element('video').dispatch('volumechange')
  assert.equal(ready().audible, false)
  stage.element('video').muted = false
  stage.element('video').dispatch('playing')
  stage.element('mic').dispatch('pointerup')
  assert.equal(ready().interaction, false)
  stage.element('mic').dispatch('pointerup')
  assert.equal(ready().interaction, true)
  stage.track.readyState = 'ended'
  stage.element('video').dispatch('playing')
  assert.equal(ready().microphone, false)
  stage.peerState('disconnected')
  assert.equal(ready().audible, false)
})
