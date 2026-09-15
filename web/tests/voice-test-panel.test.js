import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  formatSeconds,
  stageRows,
  statusLabel,
  voicePhaseLabel,
} from '../src/voiceTestMetrics.js'

const panel = readFileSync(
  new URL('../src/components/VoiceTestPanel.vue', import.meta.url),
  'utf8'
)
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('語音驗證面板使用真實 API 並等待相同 turn metrics', () => {
  assert.match(panel, /fetch\('\/api\/voice-tests\/run'/)
  assert.match(panel, /fetch\('\/api\/voice-tests\?limit=50'/)
  assert.match(panel, /event\.type !== 'turn_metrics'/)
  assert.match(panel, /event\.turn_id !== runningTurnId\.value/)
  assert.match(panel, /window\.setInterval\(refreshRunningResult, 1500\)/)
  assert.match(app, /voiceTestPanelRef\.value\?\.handleVoiceEvent\(event\)/)
})

test('自訂 prompt、執行狀態、歷史與內容保存提示都可見', () => {
  assert.match(panel, /id="voiceTestPrompt"/)
  assert.match(panel, /maxlength="2000"/)
  assert.match(panel, /aria-live="polite"/)
  assert.match(panel, /測試紀錄/)
  assert.match(panel, /Prompt 與實際播放文字會保存在伺服器本機/)
  assert.match(panel, /window\.confirm/)
  assert.match(panel, /請只回答「語音測試正常」。不要補充其他內容。/)
  assert.match(app, /voiceState\.value = 'paused'[\s\S]*isRecordingVoice\.value = false/)
})

test('延遲與狀態格式不把缺值顯示成零', () => {
  assert.equal(formatSeconds(null), '—')
  assert.equal(formatSeconds(1.23456), '1.235 s')
  assert.equal(statusLabel('passed'), '通過')
  assert.equal(voicePhaseLabel('avatar_speaking'), '數字人正在播放')
  const rows = stageRows({ stage_seconds: { tts_first_pcm: 0.3 } })
  assert.equal(rows.find(row => row.key === 'tts_first_pcm').value, 0.3)
  assert.equal(rows.find(row => row.key === 'asr').value, undefined)
})

test('單次測試清楚標示 P95 gate 與多輪指標不適用', () => {
  assert.match(panel, /單次測試以 P95 Gate 判定/)
  assert.match(panel, /插話停止與恢復收音需多輪情境測試/)
  assert.match(panel, /首音延遲[\s\S]*≤ 2\.5 s/)
})
