import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)

test('STT 預熱期間顯示可存取的不確定進度條', () => {
  assert.match(panel, /v-if="applyingStt"[\s\S]*class="stt-prewarm-progress"/)
  assert.match(panel, /role="progressbar"/)
  assert.match(panel, /prewarmProgressLabel/)
  assert.match(panel, /prewarmProgressHint/)
  assert.match(panel, /progress-fill-indeterminate/)
})

test('STT 預熱進度尊重減少動態效果偏好', () => {
  assert.match(panel, /@media \(prefers-reduced-motion: reduce\)[\s\S]*progress-fill-indeterminate/)
})

test('語音辨識表單依伺服器的引擎資料呈現，不寫死引擎名稱', () => {
  assert.match(panel, /v-for="engine in sttEngineOptions"/)
  assert.doesNotMatch(panel, /sttDraft\.type === '/)
})
