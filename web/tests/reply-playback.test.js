// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'

import { useWebRTC } from '../src/composables/useWebRTC.js'

async function withBrowser(run) {
  const names = ['navigator', 'RTCPeerConnection', 'RTCSessionDescription', 'MediaStream', 'fetch', 'document']
  const previous = names.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)])
  const setGlobal = (name, value) => Object.defineProperty(globalThis, name, {
    value, configurable: true, writable: true
  })
  const peers = []
  const microphone = { enabled: true, stop() {} }
  const states = []
  let source = null
  let bindings = 0
  let allowed = false
  const video = {
    muted: false,
    volume: 1,
    paused: true,
    get srcObject() { return source },
    set srcObject(value) { source = value; if (value) bindings += 1 },
    async play() {
      if (!allowed) throw new DOMException('User gesture required', 'NotAllowedError')
      this.paused = false
      this.onplaying?.()
    }
  }
  class FakeStream {
    tracks = []
    getTracks() { return this.tracks }
    addTrack(track) { this.tracks.push(track) }
  }
  class FakePeer {
    constructor() { peers.push(this) }
    createDataChannel() { return { readyState: 'connecting', close() {} } }
    addTrack() {}
    addTransceiver() {}
    async createOffer() { return { sdp: 'offer', type: 'offer' } }
    async setLocalDescription(value) { this.localDescription = value }
    async setRemoteDescription() {}
    close() {}
  }
  let rtc
  try {
    setGlobal('navigator', { mediaDevices: { getUserMedia: async () => ({
      getAudioTracks: () => [microphone], getTracks: () => [microphone]
    }) } })
    setGlobal('RTCPeerConnection', FakePeer)
    setGlobal('RTCSessionDescription', class { constructor(value) { Object.assign(this, value) } })
    setGlobal('MediaStream', FakeStream)
    setGlobal('fetch', async () => ({
      ok: true, json: async () => ({ sessionid: 7, sdp: 'answer', type: 'answer' })
    }))
    setGlobal('document', { getElementById: (id) => id === 'video' ? video : null })
    rtc = useWebRTC({ onPlaybackState: (state) => states.push(state) })
    await rtc.startPlay()
    await run({ rtc, video, peers, microphone, states,
      allowPlayback: () => { allowed = true },
      bindings: () => bindings,
      settle: () => new Promise((resolve) => setImmediate(resolve))
    })
  } finally {
    rtc?.stopPlay()
    for (const [name, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor)
      else delete globalThis[name]
    }
  }
}

test('blocked reply playback is reported and a direct user action restores sound', async () => {
  await withBrowser(async ({ rtc, video, peers, microphone, states, allowPlayback, settle }) => {
    peers[0].ontrack({ track: { id: 'audio', kind: 'audio' }, receiver: {} })
    await settle()
    assert.equal(states.at(-1), 'blocked')
    assert.equal(video.paused, true)
    assert.equal(microphone.enabled, false)

    video.muted = true
    video.volume = 0
    allowPlayback()
    assert.equal(await rtc.resumePlayback(), true)
    assert.equal(video.paused, false)
    assert.equal(video.muted, false)
    assert.equal(video.volume, 1)
    assert.equal(states.at(-1), 'playing')
    assert.equal(microphone.enabled, false)
    assert.equal(peers.length, 1)
  })
})

test('audio and video tracks share one binding and pauses expose playback recovery', async () => {
  await withBrowser(async ({ video, peers, states, bindings, allowPlayback, settle }) => {
    allowPlayback()
    peers[0].ontrack({ track: { id: 'audio', kind: 'audio' }, receiver: {} })
    await settle()
    const stream = video.srcObject
    peers[0].ontrack({ track: { id: 'video', kind: 'video' }, receiver: {} })
    await settle()
    assert.equal(video.srcObject, stream)
    assert.equal(bindings(), 1)
    assert.equal(stream.getTracks().length, 2)
    assert.equal(states.at(-1), 'playing')
    video.paused = true
    video.onpause?.()
    assert.equal(states.at(-1), 'blocked')
  })
})

test('old playback promises cannot change the state of a new connection', async () => {
  await withBrowser(async ({ rtc, video, peers, states, settle }) => {
    let rejectOldPlayback
    video.play = () => new Promise((resolve, reject) => { rejectOldPlayback = reject })
    peers[0].ontrack({ track: { id: 'old-audio', kind: 'audio' }, receiver: {} })
    await rtc.startPlay()
    const currentStates = [...states]
    rejectOldPlayback(new DOMException('Old connection blocked', 'NotAllowedError'))
    await settle()
    assert.deepEqual(states, currentStates)
    rtc.stopPlay()
    assert.equal(states.at(-1), 'idle')
    assert.equal(video.srcObject, null)
    assert.equal(video.onpause, null)
  })
})
