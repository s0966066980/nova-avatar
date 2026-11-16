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

function stageHarness({
  playAllowed = true,
  mediaDevices = undefined,
  isSecureContext = true,
  audioContextTracker = null
} = {}) {
  const elements = new Map()
  const element = (id) => {
    if (!elements.has(id)) {
      const handlers = new Map()
      elements.set(id, {
        id,
        hidden: id === 'audioUnlock',
        disabled: id === 'mic',
        muted: false,
        volume: 1,
        paused: true,
        srcObject: null,
        dataset: {},
        style: { setProperty() {} },
        classList: { add() {}, remove() {}, toggle() {} },
        textContent: '',
        clientWidth: 360,
        clientHeight: 640,
        addEventListener(type, handler) { handlers.set(type, handler) },
        dispatch(type) { handlers.get(type)?.({ preventDefault() {} }) },
        setAttribute() {},
      })
    }
    return elements.get(id)
  }

  let allowed = playAllowed
  const video = element('video')
  video.play = async () => {
    if (!allowed) {
      const err = new Error('User gesture required')
      err.name = 'NotAllowedError'
      throw err
    }
    video.paused = false
    video.onplaying?.()
  }

  const transceivers = []
  let peer
  let channel
  class Peer {
    constructor() { this.connectionState = 'new'; peer = this }
    createDataChannel() {
      channel = { readyState: 'open', send() {}, close() {} }
      return channel
    }
    addTrack() {}
    addTransceiver(kind, init) { transceivers.push({ kind, init }) }
    getTransceivers() { return [] }
    async createOffer() { return { sdp: 'offer', type: 'offer' } }
    async setLocalDescription(value) { this.localDescription = value }
    async setRemoteDescription() {}
    close() {}
  }

  class FakeAudioContext {
    constructor() {
      this.state = 'suspended'
      audioContextTracker?.created?.push(this)
    }
    async resume() {
      this.state = 'running'
      audioContextTracker?.resumed?.push(this)
    }
  }

  const defaultTrack = { enabled: false, stop() {} }
  const defaultMediaDevices = {
    getUserMedia: async () => ({ getAudioTracks: () => [defaultTrack], getTracks: () => [defaultTrack] })
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
    window: { ResizeObserver: null, isSecureContext, AudioContext: FakeAudioContext },
    isSecureContext,
    AudioContext: FakeAudioContext,
    navigator: { mediaDevices: mediaDevices === undefined ? defaultMediaDevices : mediaDevices },
    RTCPeerConnection: Peer,
    RTCSessionDescription: class { constructor(value) { Object.assign(this, value) } },
    MediaStream: class {
      constructor() { this.tracks = [] }
      getTracks() { return this.tracks }
      addTrack(track) { this.tracks.push(track) }
    },
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
    fetch: async (url) => ({ ok: true, json: async () => {
      if (url === '/api/vad') return { data: { enabled: true } }
      if (url === '/api/stage') return { data: { composer_enabled: false } }
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
    element,
    transceivers,
    allowPlayback() { allowed = true },
    async connect(locale = 'zh-TW') {
      element('stageLocale').value = locale
      element('stageLocale').onchange()
      await element('veilBtn').onclick()
      peer.connectionState = 'connected'
      peer.onconnectionstatechange()
      peer.ontrack({ track: { id: 'audio-1', kind: 'audio' }, receiver: {} })
      await new Promise((r) => setImmediate(r))
      channel.onopen()
    },
    disconnect() {
      peer.connectionState = 'failed'
      peer.onconnectionstatechange()
    }
  }
}

test('stage exposes tap-to-unmute prompt when mobile autoplay blocks video.play() and clears on user tap', async () => {
  assert.match(html, /id="audioUnlock"/)
  const ac = { created: [], resumed: [] }
  const stage = stageHarness({ playAllowed: false, audioContextTracker: ac })
  await stage.connect('zh-TW')

  const audioUnlock = stage.element('audioUnlock')
  assert.equal(audioUnlock.hidden, false)
  assert.match(audioUnlock.textContent, /聲音/)
  assert.ok(ac.resumed.length >= 1, 'AudioContext should attempt resume during user gesture')

  stage.allowPlayback()
  stage.element('video').muted = true
  stage.element('video').volume = 0
  await audioUnlock.onclick()

  assert.equal(stage.element('video').paused, false)
  assert.equal(stage.element('video').muted, false)
  assert.equal(stage.element('video').volume, 1)
  assert.equal(audioUnlock.hidden, true)

  stage.element('video').paused = true
  stage.element('video').onpause()
  assert.equal(audioUnlock.hidden, false)
})

test('stage handles missing mediaDevices / untrusted HTTPS without crashing and explains HTTPS trust', async () => {
  const stage = stageHarness({ mediaDevices: null, isSecureContext: false })
  await stage.connect('zh-TW')

  assert.equal(stage.transceivers.some((t) => t.kind === 'audio' && t.init.direction === 'recvonly'), true)
  assert.match(stage.element('said').textContent, /HTTPS/)

  const stageEn = stageHarness({ mediaDevices: null, isSecureContext: false })
  await stageEn.connect('en-US')
  assert.match(stageEn.element('said').textContent, /HTTPS/i)
})

test('stage shows permission-denied guidance when getUserMedia rejects with NotAllowedError', async () => {
  const deniedErr = new Error('Permission denied')
  deniedErr.name = 'NotAllowedError'
  const stage = stageHarness({
    mediaDevices: { getUserMedia: async () => { throw deniedErr } }
  })
  await stage.connect('zh-TW')
  assert.match(stage.element('said').textContent, /權限/)

  stage.element('mic').dispatch('pointerdown')
  await new Promise((r) => setImmediate(r))
  assert.match(stage.element('said').textContent, /權限/)
})
