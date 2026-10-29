// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { stageText, stageItemCount } from '../../src/stageLocale.js'
import { composerSettings } from '../../src/conversationAttachments.js'
import { stageErrorMessage } from '../../src/stageErrorMessage.js'
import { canRoleInput, canRoleReturn } from '../../src/roleState.js'
import { StageCaptionWindow } from '../../src/stageCaptionWindow.js'
import {
  isKioskMode,
  kioskReconnectDelayMs,
  KIOSK_UNAVAILABLE_TITLE,
  KIOSK_UNAVAILABLE_TEXT
} from '../../src/stageKiosk.js'
import {
  fetchJsonWithTimeout,
  STAGE_CONNECT_TIMEOUT_MS,
  STAGE_OFFER_TIMEOUT_MS,
  STAGE_POLL_TIMEOUT_MS
} from '../../src/stageConnection.js'

const html = readFileSync(new URL('../../stage.html', import.meta.url), 'utf8')
const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)?.[1]

export const flush = () => new Promise((resolve) => setImmediate(resolve))

// Run the real inline stage script against in-memory DOM, WebRTC and timer
// fakes. Timers are recorded instead of scheduled so tests decide when they fire.
export function stageHarness({
  search = '',
  composerEnabled = false,
  microphoneDenied = false,
  respond = null,
  getUserMedia = null,
} = {}) {
  const elements = new Map()
  const element = (id) => {
    if (!elements.has(id)) {
      const handlers = new Map()
      elements.set(id, {
        id,
        hidden: false,
        disabled: id === 'mic',
        dataset: {},
        querySelectorAll: () => [],
        style: { setProperty() {} },
        classList: { add() {}, remove() {}, toggle() {} },
        textContent: '',
        clientWidth: 360,
        clientHeight: 640,
        addEventListener(type, handler) { handlers.set(type, handler) },
        dispatch(type) { handlers.get(type)?.({ preventDefault() {} }) },
        setAttribute() {},
        paused: true, muted: false, volume: 1,
        async play() { this.paused = false; this.dispatch('playing') },
      })
    }
    return elements.get(id)
  }
  const sent = []
  const fetchCalls = []
  const offers = []
  const microphoneRequests = []
  const timers = []
  const track = { enabled: false, readyState: 'live', muted: false, stopped: false, stop() { this.stopped = true } }
  let channel
  let peer
  class Peer {
    constructor() { this.connectionState = 'new'; this.closed = false; peer = this }
    createDataChannel() {
      channel = { readyState: 'open', send(raw) { sent.push(JSON.parse(raw)) }, close() { this.readyState = 'closed' } }
      return channel
    }
    addTrack() {}
    addTransceiver() {}
    async createOffer() { return { sdp: 'offer', type: 'offer' } }
    async setLocalDescription(value) { this.localDescription = value }
    async setRemoteDescription() {}
    close() { this.closed = true }
  }
  const defaultResponse = (url) => ({ ok: true, status: 200, json: async () => {
    if (url === '/api/vad') return { data: { enabled: true } }
    if (url === '/api/stage') return { data: { composer_enabled: composerEnabled } }
    return { sessionid: 7, sdp: 'answer', type: 'answer' }
  } })
  const stream = { getAudioTracks: () => [track], getTracks: () => [track] }
  const context = {
    stageText, stageItemCount, composerSettings,
    reactive: value => value, createApp: () => ({ mount() {} }), h: () => null,
    queueMicrotask,
    document: { getElementById: element },
    window: { ResizeObserver: null, location: { search } },
    navigator: { mediaDevices: { getUserMedia: async options => {
      microphoneRequests.push(options)
      if (getUserMedia) return getUserMedia(stream)
      if (microphoneDenied) throw new Error('Permission denied')
      return stream
    } } },
    RTCPeerConnection: Peer,
    RTCSessionDescription: class { constructor(value) { Object.assign(this, value) } },
    MediaStream: class { getTracks() { return [] } addTrack() {} },
    StageCaptionWindow,
    StageCaptionView: class {
      constructor({ container, captionWindow }) { this.container = container; this.window = captionWindow }
      append(text, turnId) { this.window.append(text, turnId); this.container.textContent = this.window.text }
      clear() { this.container.textContent = '' }
      destroy() {}
    },
    DEFAULT_STAGE_CAPTION_MAX_CHARS: 200,
    shouldFadeStageReply: () => false,
    stageErrorMessage,
    canRoleInput,
    canRoleReturn,
    isKioskMode,
    kioskReconnectDelayMs,
    KIOSK_UNAVAILABLE_TITLE,
    KIOSK_UNAVAILABLE_TEXT,
    STAGE_CONNECT_TIMEOUT_MS,
    STAGE_OFFER_TIMEOUT_MS,
    STAGE_POLL_TIMEOUT_MS,
    fetchJsonWithTimeout: (url, options, timeoutMs) => fetchJsonWithTimeout(url, options, timeoutMs, {
      fetchImpl: context.fetch, setTimer: context.setTimeout, clearTimer: context.clearTimeout,
    }),
    console,
    boardReopenPresentation: () => ({ style: {}, edge: 'top', icon: '▣' }),
    captionStyle: () => ({}),
    previewScale: () => 1,
    STAGE_CAPTION_RATIO: 0.9,
    STAGE_BOARD_PREVIEW_ITEMS: [],
    STAGE_BOARD_PREVIEW_TITLE: '',
    placeStageBoard: () => ({ width: 200, height: 200, left: 0, top: 0 }),
    fetch: async (url, options) => {
      fetchCalls.push(url)
      if (url === '/offer') offers.push(JSON.parse(options.body))
      return (respond && await respond(url, options)) || defaultResponse(url)
    },
    setTimeout: (fn, ms) => { timers.push({ fn, ms, cleared: false }); return timers.length },
    clearTimeout(id) { if (timers[id - 1]) timers[id - 1].cleared = true },
    setInterval() {},
    addEventListener() {},
  }
  const body = script.replace(/^import[\s\S]*?from '[^']+';\s*/gm, '')
  vm.runInNewContext(body, context)
  return {
    sent,
    fetchCalls,
    offers,
    microphoneRequests,
    timers,
    peerState(value) { peer.connectionState = value; peer.onconnectionstatechange() },
    get peer() { return peer },
    get channel() { return channel },
    track,
    element,
    // Fire every pending timer scheduled with this delay, as if it elapsed.
    async elapse(ms) {
      for (const timer of timers.filter(item => item.ms === ms && !item.cleared)) {
        timer.cleared = true
        timer.fn()
      }
      await flush()
    },
    pending(ms) { return timers.filter(item => item.ms === ms && !item.cleared) },
    async connect() {
      await element('veilBtn').onclick()
      peer.connectionState = 'connected'
      peer.onconnectionstatechange()
      channel.onopen()
    },
    event(data) { channel.onmessage({ data: JSON.stringify(data) }) },
  }
}
