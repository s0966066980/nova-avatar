import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const consoleWebRTC = readFileSync(
  new URL('../src/composables/useWebRTC.js', import.meta.url),
  'utf8'
)
const stage = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const startup = readFileSync(
  new URL('../../scripts/start-all.sh', import.meta.url),
  'utf8'
)
const settingsPanel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)

test('控制台與舞台 offer 帶有不同 client role', () => {
  assert.match(consoleWebRTC, /client_role:\s*['"]console['"]/) // console offer
  assert.match(stage, /client_role:\s*['"]stage['"]/) // stage offer
})

test('啟動資訊只把控制台列為區網網址，舞台僅限本機', () => {
  assert.match(startup, /控制台 Local:/)
  assert.match(startup, /控制台 Network:/)
  assert.match(startup, /數字人舞台 Local:/)
  assert.doesNotMatch(startup, /舞台 Network:/)
})

test('整合啟動先建置前端，由後端同源提供，不再啟動 Vite 開發伺服器', () => {
  const viteConfig = readFileSync(
    new URL('../vite.config.js', import.meta.url),
    'utf8'
  )
  assert.match(startup, /npm --silent run build/)
  assert.doesNotMatch(startup, /run dev/)
  assert.match(viteConfig, /process\.env\.VITE_CONFIG_QUIET/)
  assert.match(viteConfig, /let webHost = '127\.0\.0\.1'/)
})

test('舞台字幕只接受播放提交事件並取消舊淡出計時', () => {
  assert.doesNotMatch(stage, /ev\.type === 'assistant_text'/)
  assert.match(stage, /ev\.type === 'assistant_fragment'/)
  assert.match(
    stage,
    /function showReply\(text, turnId\)\{[\s\S]*?clearTimeout\(replyTimer\);[\s\S]*?replyRevision\+\+;/
  )
  assert.match(
    stage,
    /function fadeReply\(turnId=replyTurnId\)\{[\s\S]*?revision === replyRevision[\s\S]*?turnId === replyTurnId/
  )
  assert.match(
    stage,
    /if\(ev\.type === 'turn_cancelled'\)\{[\s\S]*?clearReply\(\);[\s\S]*?\}/
  )
  assert.match(stage, /StageCaptionWindow/)
  assert.match(stage, /StageCaptionView/)
  assert.match(stage, /fetchJsonWithTimeout\('\/api\/stage'/)
  assert.doesNotMatch(stage, /reply\.scrollTop\s*=/)
  assert.match(stage, /overflow:clip/)
  assert.match(stage, /reply-exit-layer/)
  assert.doesNotMatch(stage, /overflow-y:auto/)
})

test('控制台提供獨立舞台字幕設定與套用操作', () => {
  assert.match(settingsPanel, /id: 'stage'/)
  assert.match(settingsPanel, /id="settings-panel-stage"/)
  assert.match(settingsPanel, /id="stage-caption-max-chars"/)
  assert.match(settingsPanel, /@click="handleApplyStage"/)
  assert.match(settingsPanel, /min="20"/)
  assert.match(settingsPanel, /max="2000"/)
  assert.match(settingsPanel, /stage-board-style-\$\{style\.id\}/)
  assert.match(settingsPanel, /id: 'glass'/)
  assert.match(settingsPanel, /id: 'slate'/)
  assert.match(settingsPanel, /id: 'cue'/)
  assert.match(settingsPanel, /id="stage-board-preview"/)
  assert.match(settingsPanel, /id="stage-mic-x"/)
  assert.match(settingsPanel, /stage-layout-preview/)
})

test('舞台讀取控制台套用的看板視窗樣式', () => {
  assert.match(stage, /class="float-board"/)
  assert.match(stage, /board_style/)
  assert.match(stage, /data-board-style/)
  assert.match(stage, /board_begin/)
  assert.match(stage, /micLayout/)
  assert.match(stage, /STAGE_BOARD_PREVIEW_ITEMS/)
  assert.match(stage, /placeStageBoard/)
})

test('控制台與舞台在看板項目完成渲染後回傳一次顯示收據', () => {
  assert.match(consoleWebRTC, /board_displayed/)
  assert.match(consoleWebRTC, /presenter:\s*'console'/)
  assert.match(stage, /board_displayed/)
  assert.match(stage, /presenter:'stage'/)
})

test('控制台不會把舊模式完整回覆與播放提交片段重複顯示', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(app, /event\.type === 'assistant_text'/)
  assert.match(app, /event\.type === 'assistant_fragment'/)
  assert.match(app, /lastMessage\.voiceTurnId === event\.turn_id/)
  assert.match(app, /replyMode:\s*event\.mode\s*\|\|\s*'legacy'/)
  assert.match(app, /lastMessage\.replyMode === 'legacy'/)
})
