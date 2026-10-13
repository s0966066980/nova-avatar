// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { useWebRTC } from '../src/composables/useWebRTC.js'

const source = readFileSync(
  new URL('../src/composables/useWebRTC.js', import.meta.url),
  'utf8'
)
const appSource = readFileSync(
  new URL('../src/App.vue', import.meta.url),
  'utf8'
)

test('WebRTC 同時承載麥克風上行與語音事件', () => {
  assert.match(source, /getUserMedia/)
  assert.match(source, /pc\.addTrack\(microphoneStream\.getAudioTracks\(\)\[0\]/)
  assert.match(source, /createDataChannel\('voice-events'/)
})

test('麥克風請求啟用瀏覽器迴音與噪音處理', () => {
  assert.match(source, /echoCancellation:\s*true/)
  assert.match(source, /noiseSuppression:\s*true/)
  assert.match(source, /autoGainControl:\s*true/)
})

test('資料通道失效時會關閉收音並進入重連狀態', () => {
  assert.match(source, /eventChannel\.onclose/)
  assert.match(source, /setCaptureEnabled\(false\)/)
  assert.match(source, /notifyConnection\('reconnecting'\)/)
})

test('控制台連線後維持收音關閉，需由麥克風按鈕手動開啟', () => {
  assert.match(source, /startPlay = \(stunServer = null, initialCapture = false\)/)
  assert.match(appSource, /startPlay\(null, false\)/)
})

test('連線準備期間的重複 startPlay 共用同一次 offer', async () => {
  const globalNames = [
    'navigator', 'RTCPeerConnection', 'RTCSessionDescription',
    'MediaStream', 'fetch', 'document'
  ]
  const previous = Object.fromEntries(
    globalNames.map((name) => [name, Object.getOwnPropertyDescriptor(globalThis, name)])
  )
  const setGlobal = (name, value) => {
    Object.defineProperty(globalThis, name, {
      value, configurable: true, writable: true
    })
  }
  let peerCount = 0
  let connectedPeer
  let offerCount = 0
  const microphoneTrack = { enabled: true, stop() {} }
  const microphoneStream = {
    getAudioTracks: () => [microphoneTrack],
    getTracks: () => [microphoneTrack]
  }

  class FakePeerConnection {
    constructor() {
      connectedPeer = this
      peerCount += 1
      this.localDescription = null
    }
    createDataChannel() {
      return { readyState: 'connecting', close() {} }
    }
    addTrack() {}
    addTransceiver() {}
    async createOffer() {
      offerCount += 1
      return { sdp: 'offer', type: 'offer' }
    }
    async setLocalDescription(offer) {
      this.localDescription = offer
    }
    async setRemoteDescription() {}
    close() {}
  }

  try {
    setGlobal('navigator', {
      mediaDevices: { getUserMedia: async () => microphoneStream }
    })
    setGlobal('RTCPeerConnection', FakePeerConnection)
    setGlobal('RTCSessionDescription', class {
      constructor(value) { Object.assign(this, value) }
    })
    setGlobal('MediaStream', class {
      getTracks() { return [] }
      addTrack() {}
    })
    setGlobal('fetch', async () => ({
      ok: true,
      json: async () => ({ sessionid: 7, sdp: 'answer', type: 'answer' })
    }))
    setGlobal('document', { getElementById: () => null })

    const { startPlay, stopPlay } = useWebRTC()
    const first = startPlay()
    const second = startPlay()

    assert.equal(first, second)
    assert.equal(await first, 7)
    assert.equal(peerCount, 1)
    assert.equal(offerCount, 1)
    assert.equal(microphoneTrack.enabled, false)
    const receiver = { jitterBufferTarget: null }
    connectedPeer.ontrack({ track: { id: 'reply', kind: 'audio' }, receiver })
    assert.equal(receiver.jitterBufferTarget, 160)
    const videoReceiver = { jitterBufferTarget: null }
    connectedPeer.ontrack({ track: { id: 'video', kind: 'video' }, receiver: videoReceiver })
    assert.equal(videoReceiver.jitterBufferTarget, null)
    assert.doesNotThrow(() => connectedPeer.ontrack({ track: { id: 'fallback', kind: 'audio' }, receiver: {} }))
    stopPlay()
  } finally {
    for (const name of globalNames) {
      if (previous[name]) {
        Object.defineProperty(globalThis, name, previous[name])
      } else {
        delete globalThis[name]
      }
    }
  }
})

test('stopping during microphone permission cancels only that attempt and permits a fresh connection', async () => {
  const names = ['navigator','RTCPeerConnection','RTCSessionDescription','MediaStream','fetch','document']
  const previous = new Map(names.map(n => [n, Object.getOwnPropertyDescriptor(globalThis, n)]))
  const set = (n,v) => Object.defineProperty(globalThis,n,{value:v,configurable:true,writable:true})
  const peers = [], sessions = [], tracks = []
  let resolveMic, micCalls = 0, offerCalls = 0, rtc, first, second
  const stream = () => { const t={enabled:true,stopped:false,stop(){this.stopped=true}}; tracks.push(t); return {getAudioTracks:()=>[t],getTracks:()=>[t]} }
  class Peer {
    constructor(){peers.push(this)}
    createDataChannel(){return {readyState:'connecting',close(){}}}
    addTrack(){} addTransceiver(){}
    async createOffer(){offerCalls++;return {type:'offer',sdp:'offer'}}
    async setLocalDescription(v){this.localDescription=v}
    async setRemoteDescription(){} close(){}
  }
  try {
    set('navigator',{mediaDevices:{getUserMedia:()=> ++micCalls===1 ? new Promise(r=>{resolveMic=r}) : Promise.resolve(stream())}})
    set('RTCPeerConnection',Peer)
    set('RTCSessionDescription',class{constructor(v){Object.assign(this,v)}})
    set('MediaStream',class{getTracks(){return []} addTrack(){}})
    set('document',{getElementById:()=>null})
    set('fetch',async()=>({ok:true,json:async()=>({sessionid:42,type:'answer',sdp:'answer'})}))
    rtc=useWebRTC({onSessionId:id=>{if(id)sessions.push(id)}})
    first=rtc.startPlay();first.catch(()=>{})
    await new Promise(r=>setImmediate(r))
    rtc.stopPlay()
    second=rtc.startPlay();second.catch(()=>{})
    resolveMic(stream());resolveMic=null
    assert.notEqual(second,first,'startPlay returned a cancelled attempt')
    assert.equal(await second,42)
    await assert.rejects(first,{name:'AbortError'})
    assert.equal(offerCalls,1)
    assert.deepEqual(sessions,[42])
    assert.equal(tracks.at(-1).stopped,true,'late microphone stream leaked')
  } finally {
    resolveMic?.(stream())
    await Promise.allSettled([first,second].filter(Boolean))
    rtc?.stopPlay()
    for(const [n,d] of previous){if(d)Object.defineProperty(globalThis,n,d);else delete globalThis[n]}
  }
})
