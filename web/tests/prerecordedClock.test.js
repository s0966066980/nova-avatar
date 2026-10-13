// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { PrerecordedPlayer } from '../src/prerecordedPlayer.js'
import { PresentationTimeline } from '../src/prerecordedTimeline.js'

test('a delayed first RTCP clock recovers without permanently disabling talking and recording', async () => {
  const names=['performance','setTimeout','setInterval','clearInterval']
  const saved=new Map(names.map(n=>[n,Object.getOwnPropertyDescriptor(globalThis,n)]))
  const set=(n,v)=>Object.defineProperty(globalThis,n,{value:v,configurable:true,writable:true})
  let now=0, poll, ready=false
  const player=Object.create(PrerecordedPlayer.prototype)
  Object.assign(player,{disposed:false,state:'idle',videos:{idle:{readyState:2}},gl:{isContextLost:()=>false},
    clockOffset:null,timeline:new PresentationTimeline(),onError:()=>{},
    peerConnection:{getStats:async()=>new Map(ready ? [['audio',{type:'inbound-rtp',kind:'audio',estimatedPlayoutTimestamp:1000}],['video',{type:'inbound-rtp',kind:'video',estimatedPlayoutTimestamp:1000}]] : [])}})
  try {
    set('performance',{now:()=>now})
    set('setTimeout',fn=>{now+=100;queueMicrotask(fn);return 1})
    set('setInterval',fn=>{poll=fn;return 1})
    set('clearInterval',()=>{})
    await player.prepareClock().catch(error=>player.fail(error))
    assert.equal(player.clockOffset,null)
    ready=true;poll()
    await new Promise(resolve=>setImmediate(resolve))
    assert.equal(player.clockOffset,0)
    assert.equal(Boolean(player.errorReported),false,'healthy late clock remained in a permanent media error')
  } finally {for(const [n,d] of saved)Object.defineProperty(globalThis,n,d)}
})
