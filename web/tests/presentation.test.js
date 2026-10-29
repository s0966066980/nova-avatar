// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import { applyConsoleBoardEvent } from '../src/consoleBoardState.js'
import { applyTurnCommitted } from '../src/consoleTurnCommit.js'

// Exercise the console's actual event handler without opening speech devices.
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const handler = app.slice(app.indexOf('const handleVoiceEvent ='), app.indexOf('const handleVoiceTestStarted ='))

test('控制台忽略另一端問答與重置，只重播自己對話的已播內容', () => {
  const context = {
    composerRef: { value: null },
    roleEvent() {}, voiceTestPanelRef: { value: null },
    voiceState: { value: '' }, isRecordingVoice: { value: false }, isThinking: { value: false },
    chatMessages: { value: [] }, assistantStreamState: new Map(), ragByTurn: {},
    captionEpoch: { value: 0 }, stageBoard: { items: [] },
    applyConsoleBoardEvent, applyTurnCommitted,
    scrollMessagesToEnd() {},
    addMessage(text, type, properties) { context.chatMessages.value.push({ text, type, ...properties }) },
  }
  vm.runInNewContext(`${handler}\nglobalThis.onEvent = handleVoiceEvent`, context)
  context.onEvent({ type: 'user_transcript', turn_id: 'visitor', text: '訪客正在問的問題', mirrored: true })
  context.onEvent({ type: 'assistant_fragment', turn_id: 'visitor', text: '舞台實際播出的回答', mirrored: true })
  assert.equal(context.chatMessages.value.length, 0)
  context.onEvent({ type: 'board_begin', turn_id: 'visitor', title: '目前看板', mirrored: true })
  context.onEvent({ type: 'presentation_reset' })
  assert.equal(context.chatMessages.value.length, 0)
  assert.equal(context.stageBoard.items.length, 0)
  context.onEvent({ type: 'user_transcript', turn_id: 'console', text: '目前的控制台對話', replay: true })
  context.onEvent({ type: 'assistant_fragment', turn_id: 'console', text: '控制台已播回答', replay: true })
  assert.deepEqual(Array.from(context.chatMessages.value, message => message.text), ['目前的控制台對話', '控制台已播回答'])
  context.onEvent({ type: 'conversation_reset', mirrored: true })
  assert.equal(context.chatMessages.value.length, 2)
  context.onEvent({ type: 'conversation_reset' })
  assert.equal(context.chatMessages.value.length, 0)
})
