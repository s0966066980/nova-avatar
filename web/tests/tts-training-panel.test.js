// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/TtsTrainingPanel.vue', import.meta.url),
  'utf8'
)
const settingsPanel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)
const zhTw = readFileSync(new URL('../src/locales/zh-TW.js', import.meta.url), 'utf8')
const zhCn = readFileSync(new URL('../src/locales/zh-CN.js', import.meta.url), 'utf8')
const enUs = readFileSync(new URL('../src/locales/en-US.js', import.meta.url), 'utf8')

test('TtsTrainingPanel 提供 4 個訓練步驟、即時日誌、試聽聲線與 Edge-TTS 非商業警語', () => {
  assert.match(panel, /class="setting-card full-span tts-training-card"/)
  for (const step of ['corpus', 'distill', 'train', 'export', 'full']) {
    assert.ok(panel.includes(`runStep('${step}')`), `missing action for step ${step}`)
  }
  assert.match(panel, /Research \/ Non-commercial/)
  assert.match(panel, /NOTICE-NON-COMMERCIAL\.txt/)
  assert.match(panel, /role="progressbar"/)
  assert.match(panel, /job-log-tail/)
  assert.match(panel, /\/api\/tts\/training\/step/)
  assert.match(panel, /\/api\/tts\/training\/cancel/)
  assert.match(panel, /\/api\/tts\/training\/preview/)
  assert.match(panel, /previewEdgeVoice/)
})

test('SettingsPanel 語音分頁整合 TtsTrainingPanel 與套用匯出模型回呼', () => {
  assert.match(settingsPanel, /import TtsTrainingPanel from '\.\/TtsTrainingPanel\.vue'/)
  assert.match(settingsPanel, /<TtsTrainingPanel[\s\S]*@apply-model="handleApplyTrainedTtsModel"/)
  assert.match(settingsPanel, /ttsDraft\.type = 'matcha'/)
})

test('語系檔皆包含 ttsTraining 本地化鍵值', () => {
  for (const [name, content] of [['zh-TW', zhTw], ['zh-CN', zhCn], ['en-US', enUs]]) {
    assert.match(content, /ttsTraining:\s*\{/, `${name} missing ttsTraining locale section`)
    assert.match(content, /exportDoneNotice:/, `${name} missing exportDoneNotice`)
  }
})
