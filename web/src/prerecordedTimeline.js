// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Events follow the decoded transport clock, never packet arrival or audio RMS.
export class PresentationTimeline {
  constructor({ silenceMs = 300 } = {}) {
    this.silenceMs = silenceMs
    this.generation = -1
    this.cancelled = new Set()
    this.reset()
  }

  reset() {
    this.events = []
    this.state = 'idle'
    this.silentSince = null
  }

  receive(event) {
    if (event.type === 'turn_cancelled' || event.type === 'error') {
      if (event.turn_id) this.cancelled.add(event.turn_id)
      while (this.cancelled.size > 64) this.cancelled.delete(this.cancelled.values().next().value)
      this.reset()
      return
    }
    if (!['presentation_activity', 'speaking_start', 'speaking_end'].includes(event.type)) return
    if (!Number.isFinite(event.media_ms) || this.cancelled.has(event.turn_id)) return
    const generation = Number(event.generation)
    if (!Number.isInteger(generation) || generation < this.generation) return
    if (generation > this.generation) {
      this.generation = generation
      this.reset()
    }
    this.events.push(event)
    this.events.sort((a, b) => a.media_ms - b.media_ms || a.seq - b.seq)
    if (this.events.length > 512) this.events.splice(0, this.events.length - 512)
  }

  advance(mediaMs) {
    while (this.events.length && this.events[0].media_ms <= mediaMs) {
      const event = this.events.shift()
      if (event.type === 'speaking_end') {
        this.state = 'idle'
        this.silentSince = null
      } else if (event.type === 'presentation_activity' && event.active) {
        this.state = 'talking'
        this.silentSince = null
      } else if (event.type === 'presentation_activity' && this.silentSince === null) {
        this.silentSince = event.media_ms
      }
    }
    if (this.silentSince !== null && mediaMs - this.silentSince > this.silenceMs) this.state = 'idle'
    return this.state
  }
}

export function decodeClock(rgba) {
  let value = 0
  for (let bit = 0; bit < 32; bit++) {
    const x = (bit % 8) * 8 + 4
    const y = Math.floor(bit / 8) * 8 + 4
    value = (value * 2 + (rgba[(y * 64 + x) * 4] > 127 ? 1 : 0)) >>> 0
  }
  return (value >>> 24) === 0xa5 ? value & 0xffffff : null
}

// Both estimates use the sender's NTP clock. This accounts for the receiver's
// actual audio/video playout difference, including its initial jitter buffer.
export function audioPlayoutOffset(reports) {
  const inbound = [...reports].filter((entry) => entry.type === 'inbound-rtp')
  const audio = inbound.find((entry) => entry.kind === 'audio')?.estimatedPlayoutTimestamp
  const video = inbound.find((entry) => entry.kind === 'video')?.estimatedPlayoutTimestamp
  if (!Number.isFinite(audio) || !Number.isFinite(video) || audio <= 0 || video <= 0) return null
  const offset = audio - video
  return Math.abs(offset) <= 5000 ? offset : null
}
