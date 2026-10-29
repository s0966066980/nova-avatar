// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(new URL('../src/components/SettingsPanel.vue', import.meta.url), 'utf8')
const rag = readFileSync(new URL('../src/components/RagFlowSettings.vue', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('RAG 與 AI 編輯整合進數位人設定檔，沿用舊頁籤連結', () => {
  assert.match(panel, /AvatarProfiles/)
  assert.doesNotMatch(panel, /id: 'ai'|id: 'rag'/)
  assert.ok(panel.includes("tabId === 'ai' || tabId === 'rag'"))
  assert.match(rag, /profile_id: props.profileId, selection: selection.value/)
  assert.match(rag, /只使用指定文本/)
  assert.match(rag, /\/api\/ragflow\/datasets/)
  assert.match(rag, /\/api\/ragflow\/test/)
  assert.doesNotMatch(rag, /\/api\/ragflow\/settings|NOVA_RAGFLOW_API_KEY|Authorization.*Bearer/)
})

test('檢索參考與故障可顯示，但空結果不混入對話', () => {
  assert.match(app, /event\.type === 'rag_retrieval'/)
  assert.match(app, /event\.type === 'turn_cancelled'[\s\S]*delete ragByTurn\[event\.turn_id\]/)
  assert.match(app, /ragByTurn\[msg\.voiceTurnId\]\.status === 'unavailable'/)
  assert.match(app, /<details[^>]*class="rag-turn-references"/)
  assert.match(app, /status === 'unavailable'[\s\S]*\|\| ragByTurn\[msg\.voiceTurnId\]\.sources\.length/)
  // ADR 0022: retrieval past its 400 ms budget is reported, not waited for.
  assert.match(app, /status === 'timeout'"[^>]*class="rag-turn-warning"[\s\S]*?本輪未取得檢索/)
  assert.doesNotMatch(app, /ragByTurn\[msg\.voiceTurnId\]\.status === 'empty'/)
  assert.doesNotMatch(app, /本輪是一般回答/)
  assert.doesNotMatch(app, /put_msg_txt\(source\.content/)
})
