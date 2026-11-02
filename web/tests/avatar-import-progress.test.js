// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)

test('角色匯入期間顯示即時進度條與階段訊息', () => {
  assert.match(panel, /v-if="importing && importJob"[\s\S]*role="progressbar"/)
  assert.match(panel, /importJob\.progress/)
  assert.match(panel, /importJob\.message/)
})

test('角色匯入失敗時於卡片內保留錯誤訊息提示', () => {
  assert.match(panel, /v-if="importError"[\s\S]*role="alert"/)
  assert.match(panel, /\{\{\s*importError\s*\}\}/)
})
