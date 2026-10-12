// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import { stageErrorMessage } from '../src/stageErrorMessage.js'
import {
  isKioskMode,
  kioskReconnectDelayMs,
  KIOSK_UNAVAILABLE_TITLE,
  KIOSK_UNAVAILABLE_TEXT
} from '../src/stageKiosk.js'

const html = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)?.[1]

function stageHarness({ search = '' } = {}) {
  const elements = new Map()
  const element = (id) => {
    if (!elements.has(id)) {
      const handlers = new Map()
      elements.set(id, {
        id,
        hidden: false,
        disabled: id === 'mic',
        dataset: {},
        style: { setProperty() {} },
        classList: { add() {}, remove() {}, toggle() {} },
        textContent: '',
        clientWidth: 360,
        clientHeight: 640,
        addEventListener(type, handler) { handlers.set(type, handler) },
        dispatch(type) { handlers.get(type)?.({ preventDefault() {} }) },
        setAttribute() {},
        async play() {},
      })
    }
    return elements.get(id)
  }
  const sent = []
  const fetchCalls = []
  const timers = []
  const track = { enabled: false, stop() {} }
  let channel
  let peer
  class Peer {
    constructor() { this.connectionState = 'new'; peer = this }
    createDataChannel() {
      channel = { readyState: 'open', send(raw) { sent.push(JSON.parse(raw)) }, close() {} }
      return channel
    }
    addTrack() {}
    addTransceiver() {}
    async createOffer() { return { sdp: 'offer', type: 'offer' } }
    async setLocalDescription(value) { this.localDescription = value }
    async setRemoteDescription() {}
    close() {}
  }
  const context = {
    document: { getElementById: element },
    window: { ResizeObserver: null, location: { search } },
    navigator: { mediaDevices: { getUserMedia: async () => ({
      getAudioTracks: () => [track], getTracks: () => [track]
    }) } },
    RTCPeerConnection: Peer,
    RTCSessionDescription: class { constructor(value) { Object.assign(this, value) } },
    MediaStream: class { getTracks() { return [] } addTrack() {} },
    StageCaptionWindow: class {},
    StageCaptionView: class { clear() {} destroy() {} },
    DEFAULT_STAGE_CAPTION_MAX_CHARS: 200,
    shouldFadeStageReply: () => false,
    stageErrorMessage,
    isKioskMode,
    kioskReconnectDelayMs,
    KIOSK_UNAVAILABLE_TITLE,
    KIOSK_UNAVAILABLE_TEXT,
    console,
    boardReopenPresentation: () => ({ style: {}, edge: 'top', icon: '▣' }),
    captionStyle: () => ({}),
    previewScale: () => 1,
    STAGE_CAPTION_RATIO: 0.9,
    STAGE_BOARD_PREVIEW_ITEMS: [],
    STAGE_BOARD_PREVIEW_TITLE: '',
    placeStageBoard: () => ({ width: 200, height: 200, left: 0, top: 0 }),
    fetch: async (url) => (fetchCalls.push(url), { ok: true, json: async () => {
      if (url === '/api/vad') return { data: { enabled: true } }
      if (url === '/api/stage') return { data: {} }
      return { sessionid: 7, sdp: 'answer', type: 'answer' }
    } }),
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length },
    clearTimeout() {},
    setInterval() {},
    addEventListener() {},
  }
  const body = script.replace(/^import[\s\S]*?from '[^']+';\s*/gm, '')
  vm.runInNewContext(body, context)
  return {
    sent,
    fetchCalls,
    timers,
    peerState(value) { peer.connectionState = value; peer.onconnectionstatechange() },
    track,
    element,
    async connect() {
      await element('veilBtn').onclick()
      peer.connectionState = 'connected'
      peer.onconnectionstatechange()
      channel.onopen()
    },
    event(data) { channel.onmessage({ data: JSON.stringify(data) }) },
  }
}

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
    { type: 'capture', enabled: true, finalize: false },
    { type: 'interrupt' },
  ])
})

const flush = () => new Promise((resolve) => setImmediate(resolve))

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
