// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
export function webSearchState() { return { turnId: null, phase: '', result: null } }
export function receiveWebSearch(state, event) {
  if (['conversation_reset', 'presentation_reset', 'role_clear', 'answer_clear'].includes(event.type)) Object.assign(state, webSearchState())
  if (event.type === 'web_search_clear') Object.assign(state, { turnId: event.turn_id, phase: '', result: null })
  if (event.turn_id !== state.turnId) return
  if (event.type === 'state' && ['search_planning', 'searching', 'summarizing'].includes(event.state)) state.phase = event.state
  if (event.type === 'web_search_result') { state.result = event; state.phase = '' }
  if (event.type === 'turn_cancelled' || (event.type === 'state' && ['llm', 'tts_ready', 'error'].includes(event.state))) state.phase = ''
  if (event.type === 'turn_cancelled') state.result = null
}
export function safeWebLink(value) {
  try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : '' } catch { return '' }
}
