// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

const STAGE_REPLY_FADE_EVENTS = new Set([
  'speaking_end',
  'turn_committed'
])

export function shouldFadeStageReply(eventType) {
  return STAGE_REPLY_FADE_EVENTS.has(String(eventType || ''))
}
