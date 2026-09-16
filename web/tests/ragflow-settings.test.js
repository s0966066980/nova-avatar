// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(new URL('../src/components/SettingsPanel.vue', import.meta.url), 'utf8')
const rag = readFileSync(new URL('../src/components/RagFlowSettings.vue', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('RAG 設定是獨立頁籤並按數位人保存選擇', () => {
  assert.match(panel, /RagFlowSettings/)
  assert.match(rag, /avatar_id: avatarId, enabled: draft\.enabled, dataset_ids: draft\.datasetIds/)
  assert.match(rag, /\/api\/ragflow\/settings/)
  assert.match(rag, /\/api\/ragflow\/datasets/)
  assert.match(rag, /\/api\/ragflow\/test/)
  assert.doesNotMatch(rag, /NOVA_RAGFLOW_API_KEY|Authorization.*Bearer/)
})

test('檢索結果只在控制台回覆顯示，並處理空結果、故障與取消', () => {
  assert.match(app, /event\.type === 'rag_retrieval'/)
  assert.match(app, /event\.type === 'turn_cancelled'[\s\S]*delete ragByTurn\[event\.turn_id\]/)
  assert.match(app, /ragByTurn\[msg\.voiceTurnId\]\.status === 'empty'/)
  assert.match(app, /ragByTurn\[msg\.voiceTurnId\]\.status === 'unavailable'/)
  assert.match(app, /<details[^>]*class="rag-turn-references"/)
  assert.doesNotMatch(app, /put_msg_txt\(source\.content/)
})
