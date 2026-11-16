// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { setImmediate } from 'node:timers/promises'
import vm from 'node:vm'
import test from 'node:test'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import * as attachments from '../src/conversationAttachments.js'
import { useWebRTC } from '../src/composables/useWebRTC.js'
import { stageText, stageItemCount } from '../src/stageLocale.js'
import { configureReplyPlayout } from '../src/replyPlayout.js'
import { mountPresentation, presentationPlayer, exportSceneRecording } from '../src/prerecordedPlayer.js'

const html = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)?.[1]

function stageTakeoverHarness({ offerHandler } = {}) {
  const elements = new Map()
  const element = (id) => {
    if (!elements.has(id)) {
      const handlers = new Map()
      elements.set(id, {
        id,
        hidden: false,
        disabled: id === 'mic',
        value: id === 'stageLocale' ? 'zh-TW' : '',
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
  const offers = [], releases = [], scheduledTimeouts = []
  const track = { enabled: false, stop() {} }
  let channel, peer, timerSeq = 0
  class Peer {
    constructor() { this.connectionState = 'new'; peer = this }
    createDataChannel() {
      channel = { readyState: 'open', send() {}, close() {} }
      return channel
    }
    addTrack() {}
    addTransceiver() {}
    async createOffer() { return { sdp: 'offer', type: 'offer' } }
    async setLocalDescription(value) { this.localDescription = value }
    async setRemoteDescription() {}
    close() { this.connectionState = 'closed' }
  }
  const context = {
    stageText, stageItemCount,
    newClientId: () => 'stage-device-1',
    releaseSession: async (sid, cid) => { releases.push({ sid, cid }) },
    avatarIsReady: async () => true,
    downloadMedia: async () => {},
    configureReplyPlayout,
    mountPresentation, presentationPlayer, exportSceneRecording,
    document: {
      documentElement: { setAttribute() {} },
      getElementById: (id) => id === 'scene-record-controls' ? elements.get(id) || null : element(id)
    },
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
    fetch: async (url, options = {}) => {
      if (url === '/api/vad') return { ok: true, json: async () => ({ data: { enabled: true } }) }
      if (url === '/api/stage') return { ok: true, json: async () => ({ data: {} }) }
      if (url === '/offer') {
        const body = JSON.parse(options.body)
        offers.push(body)
        if (offerHandler) return offerHandler(body)
        return { ok: true, status: 200, json: async () => ({ sessionid: 7, sdp: 'answer', type: 'answer' }) }
      }
      return { ok: true, status: 200, json: async () => ({}) }
    },
    setTimeout: (fn, delay) => {
      const id = ++timerSeq
      scheduledTimeouts.push({ id, delay, fn })
      return id
    },
    clearTimeout() {},
    setInterval() {},
    addEventListener() {},
  }
  const body = script.replace(/^import[\s\S]*?from '[^']+';\s*/gm, '')
  vm.runInNewContext(body, context)
  return {
    offers,
    releases,
    scheduledTimeouts,
    element,
    get peer() { return peer },
    get channel() { return channel },
    async enter() {
      await element('veilBtn').onclick()
    },
    markConnected() {
      peer.connectionState = 'connected'
      peer.onconnectionstatechange()
      channel.onopen()
    },
    event(data) { channel.onmessage({ data: JSON.stringify(data) }) },
  }
}

test('舞台被佔用 (409 stage_occupied) 時不自動重連，顯示接管按鈕並在點擊後以 takeover=true 連線', async () => {
  let attempt = 0
  const stage = stageTakeoverHarness({
    offerHandler: (body) => {
      attempt += 1
      if (attempt === 1) {
        return {
          ok: false,
          status: 409,
          json: async () => ({ code: 'stage_occupied', msg: '目前已有其他裝置正在使用舞台' }),
        }
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ sessionid: 19, sdp: 'answer', type: 'answer' }),
      }
    },
  })

  await stage.enter()
  assert.equal(stage.offers.length, 1)
  assert.equal(Boolean(stage.offers[0].takeover), false)
  assert.equal(stage.scheduledTimeouts.filter(t => t.delay === 1000).length, 0)
  assert.equal(stage.element('veil').hidden, false)
  assert.match(stage.element('veilText').textContent, /其他裝置/)
  assert.equal(stage.element('veilBtn').hidden, false)
  assert.equal(stage.element('veilBtn').textContent, '接管此舞台')

  await stage.element('veilBtn').onclick()
  assert.equal(stage.offers.length, 2)
  assert.equal(stage.offers[1].takeover, true)
  stage.markConnected()
  assert.equal(stage.element('veil').hidden, true)
})

test('舊舞台收到 session_displaced 後立即停止自動重連並顯示被接管提示', async () => {
  const stage = stageTakeoverHarness()
  await stage.enter()
  stage.markConnected()
  assert.equal(stage.element('veil').hidden, true)

  const currentPeer = stage.peer
  const currentChannel = stage.channel
  stage.event({ seq: 1, type: 'session_displaced', reason: 'takeover' })

  assert.equal(stage.releases.length, 0)
  assert.equal(stage.element('veil').hidden, false)
  assert.match(stage.element('veilTitle').textContent, /舞台已由其他裝置接管/)
  assert.equal(stage.element('veilBtn').hidden, false)
  assert.equal(stage.element('veilBtn').textContent, '重新接管此舞台')

  // Subsequent close/failure callbacks on the old peer must not schedule auto-reconnect.
  currentChannel.onclose?.()
  currentPeer.connectionState = 'failed'
  currentPeer.onconnectionstatechange?.()
  assert.equal(stage.scheduledTimeouts.filter(t => t.delay === 1000).length, 0)

  await stage.element('veilBtn').onclick()
  assert.equal(stage.offers.at(-1).takeover, true)
})

test('一般 409 (非 stage_occupied) 仍維持原本的重試與自動重連行為', async () => {
  const stage = stageTakeoverHarness({
    offerHandler: () => ({
      ok: false,
      status: 409,
      json: async () => ({ code: -1, msg: '正在製作或切換數位人，請稍候' }),
    }),
  })

  await stage.enter()
  assert.equal(stage.element('veilTitle').textContent, '數字人尚未就緒')
  assert.equal(stage.scheduledTimeouts.filter(t => t.delay === 1000).length, 1)
})

test('ConversationComposer 在提供 clientId 時對會話路由夾帶 X-Client-Id 標頭', async (t) => {
  const composerSource = readFileSync(new URL('../src/components/ConversationComposer.vue', import.meta.url), 'utf8')
  const setup = composerSource.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const props = reactive({
    sessionId: 12,
    clientId: 'stage-client-xyz',
    connected: true,
    enabled: true,
    stage: false,
    locale: 'en-US',
    settings: { ...attachments.composerDefaults },
    modelValue: ''
  })
  const calls = []
  const cleanup = []
  const scope = effectScope()
  const context = {
    ...attachments, computed, nextTick, ref, watch,
    defineProps: () => props,
    defineEmits: () => () => {},
    defineExpose() {}, onMounted() {}, onBeforeUnmount: fn => cleanup.push(fn),
    crypto: webcrypto, FormData, AbortController,
    window: { matchMedia: () => ({ matches: true }), visualViewport: null },
    document: { activeElement: null },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    setTimeout: () => 1, clearTimeout() {}, clearInterval() {},
    async attachmentRequest(url, options = {}) {
      calls.push({ url, options })
      if (url.endsWith('/attachments')) return { files: [], selection: [], bytes: 0, vision_ready: true }
      if (url === '/human') return { turn_id: 't-1' }
      return {}
    }
  }
  const comp = scope.run(vm.runInNewContext(`(function () { ${setup}; return { text, send, cancel, refresh } })`, context))
  t.after(() => { cleanup.forEach(fn => fn()); scope.stop() })

  await comp.refresh()
  comp.text.value = 'Hello'
  await comp.send()
  await comp.cancel()
  await nextTick(); await setImmediate()

  for (const call of calls) {
    assert.equal(call.options?.headers?.['X-Client-Id'], 'stage-client-xyz', `${call.url} 應夾帶 X-Client-Id`)
  }
})

test('stage.html 與 console App.vue 傳遞 clientId 且 console 未連線時維持管理模式不佔用 GPU', () => {
  const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const rtc = useWebRTC()
  assert.ok(typeof rtc.clientId === 'string' && rtc.clientId.length > 0)
  assert.match(html, /composerState\s*=\s*reactive\(\{[^}]*clientId:\s*stageClientId/)
  assert.match(appSource, /<ConversationComposer[^>]*:client-id="clientId"/)
  assert.match(appSource, /'X-Client-Id':\s*clientId/)
  assert.match(appSource, /管理模式就緒/)
})
