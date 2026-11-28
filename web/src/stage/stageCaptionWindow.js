// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export const DEFAULT_STAGE_CAPTION_MAX_CHARS = 120
export const MIN_STAGE_CAPTION_MAX_CHARS = 20
export const MAX_STAGE_CAPTION_MAX_CHARS = 2000

const graphemeSegmenter = typeof Intl !== 'undefined' && Intl.Segmenter
  ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  : null

export function countGraphemes(value) {
  const text = String(value ?? '')
  return graphemeSegmenter ? Array.from(graphemeSegmenter.segment(text)).length : Array.from(text).length
}

export class StageCaptionWindow {
  constructor(maxChars = DEFAULT_STAGE_CAPTION_MAX_CHARS) {
    this.maxChars = maxChars
    this.turnId = null
    this.fragments = []
    this.nextId = 0
  }

  beginTurn(turnId, maxChars = this.maxChars) {
    this.turnId = turnId || null
    this.maxChars = maxChars
    this.fragments = []
  }

  append(text, turnId, maxChars = this.maxChars) {
    const normalizedText = String(text ?? '')
    const normalizedTurnId = turnId || null
    const newTurn = normalizedTurnId !== this.turnId
    if (newTurn) this.beginTurn(normalizedTurnId, maxChars)

    if (!normalizedText) return { newTurn, added: null, removed: [] }

    const added = { id: this.nextId++, text: normalizedText }
    this.fragments.push(added)
    const removed = []
    while (this.fragments.length > 1 && this.totalChars > this.maxChars) {
      removed.push(this.evictOldest())
    }
    return { newTurn, added, removed }
  }

  evictOldest() {
    return this.fragments.shift() ?? null
  }

  clear() {
    this.turnId = null
    this.fragments = []
  }

  get totalChars() {
    return this.fragments.reduce((total, fragment) => total + countGraphemes(fragment.text), 0)
  }

  get text() {
    return this.fragments.map((fragment) => fragment.text).join('')
  }
}
