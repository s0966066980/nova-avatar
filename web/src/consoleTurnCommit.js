// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

const ERROR_REASONS = new Set([
  'tts_error_before_commit',
  'tts_error_after_commit',
  'playback_error_before_commit',
  'playback_error_after_commit',
  'pipeline_error',
])

export function isTurnCommitError(reason) {
  return ERROR_REASONS.has(String(reason || ''))
}

export function applyTurnCommitted(messages, event) {
  const list = Array.isArray(messages) ? messages : []
  if (!event || event.type !== 'turn_committed' || !event.turn_id) {
    return list
  }

  const playedText = typeof event.played_text === 'string' ? event.played_text : ''
  const index = list.findIndex(
    (item) => item.type === 'ai' && item.voiceTurnId === event.turn_id
  )

  if (index === -1) {
    if (!playedText) {
      return list
    }
    return [
      ...list,
      {
        type: 'ai',
        text: playedText,
        voiceTurnId: event.turn_id,
        streamingPreview: false,
        terminalReason: event.reason,
      },
    ]
  }

  if (!playedText) {
    return list.filter((_, itemIndex) => itemIndex !== index)
  }

  return list.map((item, itemIndex) => {
    if (itemIndex !== index) {
      return item
    }
    return {
      ...item,
      text: playedText,
      streamingPreview: false,
      terminalReason: event.reason,
    }
  })
}
