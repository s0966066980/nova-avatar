// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'

import { systemStatusRows } from '../src/systemStatus.js'

const base = {
  connectionStatus: 'disconnected',
  sessionId: 0,
  llmPartialGpu: false,
  loading: false,
  error: '',
  runtime: { ready: true, model_ready: true, session_count: 0, llm: { model: 'gemma-3' }, pending_settings: { items: [] } },
  stt: { type: 'whisper', model_size: 'small' }
}
const row = (rows, id) => rows.find(item => item.id === id)

test('每列都有名稱、文字、圖示與語氣，不只靠顏色', () => {
  for (const item of systemStatusRows(base)) {
    assert.ok(item.name && item.text, `${item.id} 需有名稱與說明`)
    assert.match(item.icon, /^bi bi-/, `${item.id} 需有圖示`)
    assert.ok(['ok', 'warn', 'danger', 'busy', 'idle'].includes(item.tone), `${item.id} 語氣 ${item.tone}`)
  }
})

test('控制台連線依 WebRTC 狀態顯示', () => {
  assert.equal(row(systemStatusRows(base), 'console').tone, 'idle')
  const connecting = row(systemStatusRows({ ...base, connectionStatus: 'connecting' }), 'console')
  assert.equal(connecting.tone, 'busy')
  const connected = row(systemStatusRows({ ...base, connectionStatus: 'connected', sessionId: 42 }), 'console')
  assert.equal(connected.tone, 'ok')
  assert.match(connected.text, /#42/)
})

test('本機 LLM 未全部載入 GPU 時顯示警示', () => {
  assert.equal(row(systemStatusRows(base), 'llm').tone, 'ok')
  assert.match(row(systemStatusRows(base), 'llm').text, /gemma-3/)
  const partial = row(systemStatusRows({ ...base, llmPartialGpu: true }), 'llm')
  assert.equal(partial.tone, 'warn')
  assert.match(partial.text, /GPU/)
})

test('後端模型載入中、讀取失敗與待套用設定各有語氣', () => {
  const loadingModel = { ...base, runtime: { ...base.runtime, model_ready: false } }
  assert.equal(row(systemStatusRows(loadingModel), 'backend').tone, 'busy')
  assert.equal(row(systemStatusRows({ ...base, error: 'HTTP 500' }), 'backend').tone, 'danger')
  assert.equal(row(systemStatusRows({ ...base, loading: true }), 'backend').tone, 'busy')
  assert.equal(row(systemStatusRows(base), 'pending'), undefined)
  const pending = { ...base, runtime: { ...base.runtime, pending_settings: { items: ['語音辨識'] } } }
  assert.equal(row(systemStatusRows(pending), 'pending').tone, 'warn')
})

test('舞台場次與語音辨識引擎', () => {
  assert.equal(row(systemStatusRows(base), 'stage').tone, 'idle')
  const live = { ...base, runtime: { ...base.runtime, session_count: 2 } }
  assert.equal(row(systemStatusRows(live), 'stage').tone, 'ok')
  assert.match(row(systemStatusRows(live), 'stage').text, /2/)
  assert.match(row(systemStatusRows(base), 'stt').text, /Whisper/)
  assert.match(row(systemStatusRows(base), 'stt').text, /small/)
})
