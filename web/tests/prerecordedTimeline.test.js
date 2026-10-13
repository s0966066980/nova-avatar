// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test'
import assert from 'node:assert/strict'
import { PresentationTimeline, decodeClock, audioPlayoutOffset } from '../src/prerecordedTimeline.js'

const event = (media_ms, active, extra = {}) => ({ type: 'presentation_activity', media_ms, active, generation: 1, turn_id: 'first', seq: media_ms, ...extra })

test('a speaking marker before effective PCM does not open the mouth', () => {
  const timeline = new PresentationTimeline()
  timeline.receive({ ...event(1000, true), type: 'speaking_start' })
  assert.equal(timeline.advance(1100), 'idle')
  timeline.receive(event(1120, true))
  assert.equal(timeline.advance(1120), 'talking')
})

test('packet arrival does not move the mouth ahead of decoded media', () => {
  const timeline = new PresentationTimeline()
  timeline.receive(event(1000, true))
  assert.equal(timeline.advance(900), 'idle')
  assert.equal(timeline.advance(1000), 'talking')
  timeline.receive(event(1300, false))
  assert.equal(timeline.advance(1500), 'talking')
  assert.equal(timeline.advance(1601), 'idle')
})

test('brief silence stays talking and next speech clears the silence timer', () => {
  const timeline = new PresentationTimeline()
  timeline.receive(event(0, true))
  timeline.receive(event(100, false))
  timeline.receive(event(300, true))
  assert.equal(timeline.advance(1000), 'talking')
})

test('cancelled and superseded generations never restart an old clip', () => {
  const timeline = new PresentationTimeline()
  timeline.receive(event(1000, true))
  timeline.receive({ type: 'turn_cancelled', turn_id: 'first' })
  timeline.receive(event(1100, true))
  assert.equal(timeline.advance(1200), 'idle')
  timeline.receive(event(1300, true, { generation: 2, turn_id: 'second' }))
  timeline.receive(event(1400, false, { generation: 1 }))
  assert.equal(timeline.advance(1800), 'talking')
})

test('a normal finish uses its media timestamp rather than event delivery time', () => {
  const timeline = new PresentationTimeline()
  timeline.receive(event(0, true))
  timeline.receive({ ...event(2000, false), type: 'speaking_end' })
  assert.equal(timeline.advance(1999), 'talking')
  assert.equal(timeline.advance(2000), 'idle')
})

test('clock signature excludes ordinary avatar frames', () => {
  assert.equal(decodeClock(new Uint8ClampedArray(64 * 32 * 4)), null)
  const rgba = new Uint8ClampedArray(64 * 32 * 4)
  const word = 0xa5000000 | 15400
  for (let bit = 0; bit < 32; bit++) {
    const x = (bit % 8) * 8 + 4, y = Math.floor(bit / 8) * 8 + 4
    rgba[(y * 64 + x) * 4] = word & (1 << (31 - bit)) ? 255 : 0
  }
  assert.equal(decodeClock(rgba), 15400)
})

test('receiver playout timestamps correct both audio lag and audio lead', () => {
  const reports = (audio, video) => [
    {type:'inbound-rtp',kind:'audio',estimatedPlayoutTimestamp:audio},
    {type:'inbound-rtp',kind:'video',estimatedPlayoutTimestamp:video},
  ]
  assert.equal(audioPlayoutOffset(reports(10000, 10580)), -580)
  assert.equal(audioPlayoutOffset(reports(10200, 10000)), 200)
  assert.equal(audioPlayoutOffset(reports(undefined, 10000)), null)
  assert.equal(audioPlayoutOffset(reports(10000, NaN)), null)
  assert.equal(audioPlayoutOffset(reports(0, 10000)), null)
  assert.equal(audioPlayoutOffset(reports(10000, 20000)), null)
})
