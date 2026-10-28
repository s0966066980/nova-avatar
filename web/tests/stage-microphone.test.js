// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import { stageText, stageItemCount } from '../src/stageLocale.js'
import { configureReplyPlayout } from '../src/replyPlayout.js'
import { mountPresentation, presentationPlayer, exportSceneRecording } from '../src/prerecordedPlayer.js'

const html = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)?.[1]

function stageHarness() {
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
  const sent = [], offers = []
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
    stageText, stageItemCount,
    newClientId: () => 'stage-test',
    releaseSession: async () => {},
    avatarIsReady: async () => true,
    downloadMedia: async () => {},
    configureReplyPlayout,
    mountPresentation, presentationPlayer, exportSceneRecording,
    document: { getElementById: (id) => id === 'scene-record-controls' ? elements.get(id) || null : element(id) },
    window: { ResizeObserver: null },
    navigator: { mediaDevices: { getUserMedia: async () => ({
      getAudioTracks: () => [track], getTracks: () => [track]
    }) } },
    RTCPeerConnection: Peer,
    RTCSessionDescription: class { constructor(value) { Object.assign(this, value) } },
    MediaStream: class { getTracks() { return [] } addTrack() {} },
    StageCaptionWindow: class {},
    StageCaptionView: class {
      constructor({ container }) { this.container = container }
      append(text) { this.container.textContent += text }
      clear() { this.container.textContent = '' }
      destroy() {}
    },
    DEFAULT_STAGE_CAPTION_MAX_CHARS: 200,
    reactive: value => value,
    createApp: () => ({ mount() {} }),
    h: () => null,
    composerSettings: values => ({ composer_enabled: false, ...values }),
    shouldFadeStageReply: () => false,
    boardReopenPresentation: () => ({ style: {}, edge: 'top', icon: '▣' }),
    captionStyle: () => ({}),
    placeStageCaption: () => ({}),
    previewScale: () => 1,
    STAGE_CAPTION_RATIO: 0.9,
    STAGE_BOARD_PREVIEW_ITEMS: [],
    STAGE_BOARD_PREVIEW_TITLE: '',
    placeStageBoard: () => ({ width: 200, height: 200, left: 0, top: 0 }),
    fetch: async (url, options = {}) => ({ ok: true, json: async () => {
      if (url === '/api/vad') return { data: { enabled: true } }
      if (url === '/api/stage') return { data: {} }
      if (url === '/offer') offers.push(JSON.parse(options.body))
      return { sessionid: 7, sdp: 'answer', type: 'answer' }
    } }),
    setTimeout: () => 1,
    clearTimeout() {},
    setInterval() {},
    addEventListener() {},
  }
  const body = script.replace(/^import[\s\S]*?from '[^']+';\s*/gm, '')
  vm.runInNewContext(body, context)
  return {
    offers,
    sent,
    track,
    element,
    async connect() {
      await element('veilBtn').onclick()
      peer.connectionState = 'connected'
      peer.onconnectionstatechange()
      channel.onopen()
    },
    event(data) { channel.onmessage({ data: JSON.stringify(data) }) },
    reopenChannel() { channel.onopen() },
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

test('舞台重新開啟通道時保留使用者暫停收音的選擇', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.element('mic').dispatch('pointerup')
  assert.equal(stage.track.enabled, false)
  stage.reopenChannel()
  assert.equal(stage.track.enabled, false)
  assert.equal(stage.sent.at(-1).enabled, false)
})

test('舞台英文入口傳遞語系，切換確認前暫停收音且不翻譯既有內容', async () => {
  const stage = stageHarness()
  const selector = stage.element('stageLocale')
  selector.value = 'en-US'
  selector.onchange()
  await stage.connect()
  assert.equal(stage.offers[0].locale, 'en-US')
  assert.equal(stage.element('modeText').textContent, 'Hands-free')
  stage.event({ seq: 1, type: 'user_transcript', text: '請記住這段中文' })
  selector.value = 'zh-TW'
  selector.onchange()
  assert.deepEqual(stage.sent.at(-1), { type: 'conversation_settings', settings: { locale: 'zh-TW' } })
  assert.equal(stage.track.enabled, false)
  assert.equal(selector.disabled, true)
  stage.event({ seq: 2, type: 'conversation_settings', locale: 'zh-TW' })
  assert.equal(selector.value, 'zh-TW')
  assert.equal(selector.disabled, false)
  assert.equal(stage.track.enabled, true)
  assert.equal(stage.element('said').textContent, '請記住這段中文')
})

test('舞台語系切換失敗恢復原語系與收音', async () => {
  const stage = stageHarness()
  await stage.connect()
  const selector = stage.element('stageLocale')
  selector.value = 'en-US'
  selector.onchange()
  assert.equal(stage.track.enabled, false)
  stage.event({ seq: 1, type: 'conversation_settings_error', locale: 'zh-TW', error: 'voice_unavailable' })
  assert.equal(selector.value, 'zh-TW')
  assert.equal(selector.disabled, false)
  assert.equal(stage.track.enabled, true)
  assert.match(stage.element('languageStatus').textContent, /保留原設定/)
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

test('訪客重置清除字幕、看板與使用者字句，保持連線和收音', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.event({ seq: 1, type: 'user_transcript', text: '上一位訪客的問題' })
  stage.event({ seq: 2, type: 'assistant_fragment', turn_id: 'old', text: '上一位訪客的回答' })
  stage.event({ seq: 3, type: 'assistant_board', turn_id: 'old', board: {
    title: '上一輪看板', items: [{ title: '舊內容', body: '內容' }]
  } })
  assert.equal(stage.element('said').textContent, '上一位訪客的問題')
  assert.equal(stage.element('reply').textContent, '上一位訪客的回答')
  assert.equal(stage.element('board').hidden, false)
  const sentBeforeReset = stage.sent.length

  stage.event({ seq: 4, type: 'conversation_reset' })

  assert.equal(stage.element('said').textContent, '')
  assert.equal(stage.element('reply').textContent, '')
  assert.equal(stage.element('boardList').innerHTML, '')
  assert.equal(stage.element('board').hidden, true)
  assert.equal(stage.element('hint').textContent, '直接說話')
  assert.equal(stage.track.enabled, true)
  assert.equal(stage.element('veil').hidden, true)
  assert.equal(stage.sent.length, sentBeforeReset)
  stage.event({ seq: 5, type: 'assistant_fragment', turn_id: 'new', text: '下一位訪客的回答' })
  assert.equal(stage.element('reply').textContent, '下一位訪客的回答')
})

test('訪客重置保留舞台使用者暫停收音的選擇', async () => {
  const stage = stageHarness()
  await stage.connect()
  stage.element('mic').dispatch('pointerup')
  stage.event({ seq: 1, type: 'conversation_reset' })
  assert.equal(stage.track.enabled, false)
  assert.equal(stage.element('hint').textContent, '已暫停收音，點一下恢復')
  assert.equal(stage.element('veil').hidden, true)
})
