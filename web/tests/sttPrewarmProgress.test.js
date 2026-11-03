import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)
const app = readFileSync(
  new URL('../src/App.vue', import.meta.url),
  'utf8'
)
const runtimeSettings = readFileSync(
  new URL('../src/composables/useRuntimeSettings.js', import.meta.url),
  'utf8'
)

test('STT 預熱期間顯示可存取的不確定進度條', () => {
  assert.match(panel, /v-if="applyingStt"[\s\S]*class="stt-prewarm-progress"/)
  assert.match(panel, /role="progressbar"/)
  assert.match(panel, /prewarmProgressLabel/)
  assert.match(panel, /speech\.stt\.local_model_ready/)
  assert.match(panel, /localPrewarmProgressHint/)
  assert.match(panel, /progress-fill-indeterminate/)
})

test('STT 預熱進度尊重減少動態效果偏好', () => {
  assert.match(panel, /@media \(prefers-reduced-motion: reduce\)[\s\S]*progress-fill-indeterminate/)
})

test('FunASR 可選擇臺灣繁體或原始簡體輸出', () => {
  assert.match(panel, /sttDraft\.type === 'funasr'/)
  assert.match(panel, /v-model="sttDraft\.output_script"/)
  assert.match(panel, /value="traditional-tw"/)
  assert.match(panel, /value="simplified"/)
})

test('語音活動與辨識提供英文 STT 辨識語言與中／英文雙語 Edge-TTS 聲線設定', () => {
  assert.match(panel, /id="stt-language"[\s\S]*v-model="sttDraft\.language"/)
  assert.match(panel, /<option value="auto">自動偵測 \(中 \/ 英\)<\/option>/)
  assert.match(panel, /<option value="en">English \(en\)<\/option>/)
  assert.match(panel, /id="tts-voice-zh-tw"[\s\S]*v-model="ttsDraft\.ref_file"/)
  assert.match(panel, /中文語音設定 \(zh-TW\)/)
  assert.match(panel, /id="tts-voice-en-us"[\s\S]*v-model="ttsDraft\.voice_en_us"/)
  assert.match(panel, /英文語音設定 \(en-US\)/)
  assert.ok(runtimeSettings.includes('const EDGE_VOICE_ID = /^(?:zh-TW|en-US)-.+Neural$/'))
})

test('頂部導航列不顯示 v2.0 版本號且系統設定左側欄不顯示模型徽章字樣', () => {
  assert.doesNotMatch(app, /nav-version-pill/)
  assert.doesNotMatch(app, />v2\.0</)
  const tabsBlock = panel.match(/const settingsTabs = computed\(\(\) => \[[\s\S]*?\]\)/)
  assert.ok(tabsBlock, 'settingsTabs definition should exist')
  assert.doesNotMatch(tabsBlock[0], /badge:/)
})
