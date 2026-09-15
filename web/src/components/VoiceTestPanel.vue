<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->
<template>
  <section class="voice-test-panel" aria-labelledby="voiceTestTitle">
    <header class="test-header">
      <div>
        <div class="test-eyebrow">LIVE PIPELINE VALIDATION</div>
        <h2 id="voiceTestTitle"><i class="bi bi-speedometer2"></i> 語音一鍵驗證</h2>
        <p>以目前 LLM、TTS、數字人與 WebRTC 設定實際播放，並保存每次結果。</p>
      </div>
      <button class="icon-button" type="button" title="收合面板" aria-label="收合測試面板" @click="$emit('close')">
        <i class="bi bi-x-lg"></i>
      </button>
    </header>

    <div class="test-grid">
      <form class="test-form" @submit.prevent="runTest">
        <label for="voiceTestLabel">測試名稱（選填）</label>
        <input
          id="voiceTestLabel"
          v-model.trim="label"
          maxlength="80"
          placeholder="例如：MuseTalk 首音複驗"
        >

        <div class="field-heading">
          <label for="voiceTestPrompt">測試 Prompt</label>
          <span>{{ prompt.length }} / 2000</span>
        </div>
        <textarea
          id="voiceTestPrompt"
          v-model="prompt"
          maxlength="2000"
          rows="5"
          placeholder="輸入要讓數字人實際回答的內容"
          required
        ></textarea>

        <div class="preset-row" aria-label="Prompt 範本">
          <button
            v-for="preset in presets"
            :key="preset.label"
            type="button"
            class="preset-button"
            @click="prompt = preset.prompt"
          >
            {{ preset.label }}
          </button>
        </div>

        <div v-if="runningTurnId" class="run-progress" role="status" aria-live="polite">
          <span class="progress-spinner" aria-hidden="true"></span>
          <span><strong>{{ voicePhaseLabel(voiceState) }}</strong><small>請等待數字人完整播放，結果會自動寫入。</small></span>
        </div>
        <p v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</p>

        <button
          class="run-button"
          type="submit"
          :disabled="!canRun"
          :title="runDisabledReason"
        >
          <i class="bi" :class="runningTurnId ? 'bi-hourglass-split' : 'bi-play-fill'"></i>
          {{ runningTurnId ? '測試執行中' : '執行一次完整測試' }}
        </button>
        <p class="privacy-note"><i class="bi bi-database-lock"></i> Prompt 與實際播放文字會保存在伺服器本機；不保存音訊檔。</p>
      </form>

      <div class="baseline-card">
        <div class="card-title"><i class="bi bi-bullseye"></i> 既有驗收 Gate</div>
        <dl>
          <div><dt>首音延遲</dt><dd>≤ 2.5 s</dd></div>
          <div><dt>A/V 偏差</dt><dd>≤ 0.08 s</dd></div>
          <div><dt>媒體債務</dt><dd>≤ 2.0 s</dd></div>
          <div><dt>stale output</dt><dd>= 0</dd></div>
        </dl>
        <p>單次測試以 P95 Gate 判定。插話停止與恢復收音需多輪情境測試，本頁標示為不適用。</p>
      </div>
    </div>

    <section v-if="selectedResult" class="result-card" aria-live="polite">
      <div class="result-heading">
        <div>
          <span class="status-badge" :class="`status-${selectedResult.status}`">
            <i class="bi" :class="statusIcon(selectedResult.status)"></i>
            {{ statusLabel(selectedResult.status) }}
          </span>
          <h3>{{ selectedResult.label || '未命名測試' }}</h3>
        </div>
        <time>{{ formatDate(selectedResult.started_at) }}</time>
      </div>

      <div class="metric-grid">
        <div><span>首音</span><strong>{{ formatSeconds(selectedResult.metrics?.first_audio_seconds) }}</strong></div>
        <div><span>LLM 首字</span><strong>{{ formatSeconds(selectedResult.metrics?.stage_seconds?.llm_first_token) }}</strong></div>
        <div><span>TTS 首 PCM</span><strong>{{ formatSeconds(selectedResult.metrics?.stage_seconds?.tts_first_pcm) }}</strong></div>
        <div><span>A/V 最大偏差</span><strong>{{ formatSeconds(selectedResult.metrics?.max_abs_av_offset_seconds) }}</strong></div>
        <div><span>最大媒體債務</span><strong>{{ formatSeconds(selectedResult.metrics?.max_media_debt_seconds) }}</strong></div>
      </div>

      <div class="content-pair">
        <div><span>Prompt</span><p>{{ selectedResult.prompt }}</p></div>
        <div><span>實際播放回覆</span><p>{{ selectedResult.assistant_response || '尚無播放內容' }}</p></div>
      </div>

      <div class="checks-grid">
        <div
          v-for="(check, key) in selectedResult.checks"
          :key="key"
          class="check-row"
        >
          <i class="bi" :class="checkIcon(check)"></i>
          <span>{{ check.label }}</span>
          <strong>{{ checkSummary(check) }}</strong>
        </div>
      </div>

      <details>
        <summary>查看完整階段延遲與執行環境</summary>
        <div class="detail-grid">
          <div class="stage-list">
            <div v-for="stage in stageRows(selectedResult.metrics)" :key="stage.key">
              <span>{{ stage.label }}</span><strong>{{ formatSeconds(stage.value) }}</strong>
            </div>
          </div>
          <dl class="environment-list">
            <div v-for="(value, key) in selectedResult.environment" :key="key">
              <dt>{{ environmentLabel(key) }}</dt><dd>{{ value || '—' }}</dd>
            </div>
          </dl>
        </div>
      </details>
    </section>

    <section class="history-section" aria-labelledby="voiceTestHistoryTitle">
      <div class="history-heading">
        <div>
          <h3 id="voiceTestHistoryTitle">測試紀錄</h3>
          <span>最近 {{ results.length }} 筆，伺服器最多保留 200 筆</span>
        </div>
        <div class="history-actions">
          <button type="button" :disabled="loading" @click="loadHistory"><i class="bi bi-arrow-clockwise"></i> 重新整理</button>
          <button type="button" class="danger-button" :disabled="!results.length || Boolean(runningTurnId)" @click="clearHistory"><i class="bi bi-trash3"></i> 清除</button>
        </div>
      </div>

      <p v-if="loading" class="empty-state" role="status">正在讀取測試紀錄…</p>
      <p v-else-if="!results.length" class="empty-state">尚無紀錄。連線後執行第一筆完整測試。</p>
      <div v-else class="history-list">
        <button
          v-for="record in results"
          :key="record.id"
          type="button"
          class="history-item"
          :class="{ selected: record.id === selectedId }"
          @click="selectedId = record.id"
        >
          <span class="history-status" :class="`status-${record.status}`"><i class="bi" :class="statusIcon(record.status)"></i></span>
          <span class="history-copy">
            <strong>{{ record.label || record.prompt }}</strong>
            <small>{{ formatDate(record.started_at) }} · {{ record.environment?.avatar || 'avatar' }} · {{ record.pipeline_mode || '—' }}</small>
          </span>
          <span class="history-latency">{{ formatSeconds(record.metrics?.first_audio_seconds) }}</span>
          <i class="bi bi-chevron-right"></i>
        </button>
      </div>
    </section>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { formatSeconds, stageRows, statusLabel, voicePhaseLabel } from '../voiceTestMetrics.js'

const props = defineProps({
  sessionId: { type: Number, default: 0 },
  connected: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  voiceState: { type: String, default: '' },
})
const emit = defineEmits(['close', 'started', 'finished', 'notification'])

const presets = [
  { label: '快速 Smoke Test', prompt: '請只回答「語音測試正常」。不要補充其他內容。' },
  { label: '簡短自我介紹', prompt: '請用一句話簡短介紹 Nova Avatar，並完整說完。' },
  { label: '規格條列', prompt: '請簡短說明目前數字人的語音與影像推論流程。' },
  { label: '長句完整性', prompt: '請用三句完整的話說明即時語音數字人的延遲、同步與穩定性。' },
]
const prompt = ref(presets[0].prompt)
const label = ref('')
const results = ref([])
const selectedId = ref('')
const runningTurnId = ref('')
const loading = ref(false)
const errorMessage = ref('')
let timeoutId = null
let pollId = null

const selectedResult = computed(() => (
  results.value.find(record => record.id === selectedId.value) || results.value[0] || null
))
const canRun = computed(() => (
  props.connected && props.sessionId > 0 && !props.busy && !runningTurnId.value && prompt.value.trim()
))
const runDisabledReason = computed(() => {
  if (!props.connected || props.sessionId <= 0) return '請先建立 WebRTC 連線'
  if (props.busy) return '目前對話尚未完成'
  if (runningTurnId.value) return '測試正在執行'
  if (!prompt.value.trim()) return '請輸入測試 Prompt'
  return ''
})

async function responsePayload(response) {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) return response.json()
  return { msg: await response.text() }
}

async function loadHistory() {
  loading.value = true
  try {
    const response = await fetch('/api/voice-tests?limit=50')
    const data = await responsePayload(response)
    if (!response.ok || data.code !== 0) throw new Error(data.msg || `HTTP ${response.status}`)
    results.value = data.results || []
    if (!selectedId.value && results.value.length) selectedId.value = results.value[0].id
  } catch (error) {
    errorMessage.value = `讀取測試紀錄失敗：${error.message}`
  } finally {
    loading.value = false
  }
}

async function runTest() {
  if (!canRun.value) return
  errorMessage.value = ''
  try {
    const response = await fetch('/api/voice-tests/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sessionid: props.sessionId,
        prompt: prompt.value.trim(),
        label: label.value,
      }),
    })
    const data = await responsePayload(response)
    if (!response.ok || data.code !== 0) throw new Error(data.msg || `HTTP ${response.status}`)
    runningTurnId.value = data.turn_id
    results.value = [data.record, ...results.value.filter(item => item.id !== data.record.id)]
    selectedId.value = data.record.id
    emit('started', { prompt: data.record.prompt, turnId: data.turn_id })
    timeoutId = window.setTimeout(async () => {
      errorMessage.value = '等待結果超過 120 秒；後端仍會在輪次結束後保存紀錄，可稍後重新整理。'
      runningTurnId.value = ''
      clearRunTimers()
      await loadHistory()
    }, 120000)
    pollId = window.setInterval(refreshRunningResult, 1500)
  } catch (error) {
    errorMessage.value = `無法開始測試：${error.message}`
    emit('notification', errorMessage.value, 'error')
  }
}

async function handleVoiceEvent(event) {
  if (event.type !== 'turn_metrics' || event.turn_id !== runningTurnId.value) return
  const completedTurnId = runningTurnId.value
  await loadHistory()
  finishRun(completedTurnId)
}

async function refreshRunningResult() {
  const turnId = runningTurnId.value
  if (!turnId) return
  await loadHistory()
  const record = results.value.find(item => item.turn_id === turnId)
  if (record && record.status !== 'running') finishRun(turnId)
}

function finishRun(turnId) {
  if (!turnId || runningTurnId.value !== turnId) return
  const completed = results.value.find(item => item.turn_id === turnId)
  if (!completed || completed.status === 'running') return
  runningTurnId.value = ''
  clearRunTimers()
  selectedId.value = completed.id
  emit('finished', completed)
}

function clearRunTimers() {
  if (timeoutId) window.clearTimeout(timeoutId)
  if (pollId) window.clearInterval(pollId)
  timeoutId = null
  pollId = null
}

async function clearHistory() {
  if (!window.confirm('確定清除所有語音測試紀錄？此操作無法復原。')) return
  try {
    const response = await fetch('/api/voice-tests', { method: 'DELETE' })
    const data = await responsePayload(response)
    if (!response.ok || data.code !== 0) throw new Error(data.msg || `HTTP ${response.status}`)
    results.value = []
    selectedId.value = ''
    emit('notification', `已清除 ${data.cleared} 筆測試紀錄`, 'success')
  } catch (error) {
    errorMessage.value = `清除測試紀錄失敗：${error.message}`
  }
}

function formatDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-TW', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

function statusIcon(status) {
  return {
    running: 'bi-hourglass-split',
    passed: 'bi-check-circle-fill',
    failed: 'bi-x-circle-fill',
    interrupted: 'bi-exclamation-circle-fill',
  }[status] || 'bi-question-circle'
}

function checkIcon(check) {
  if (check.operator === 'info') return 'bi-info-circle'
  if (!check.applicable) return 'bi-dash-circle'
  return check.passed ? 'bi-check-circle-fill check-pass' : 'bi-x-circle-fill check-fail'
}

function checkSummary(check) {
  if (check.operator === 'info') return `觀測值：${check.value ?? '—'}（不計入 Gate）`
  if (!check.applicable) return `不適用（Gate ${check.operator} ${check.threshold}${check.unit || ''}）`
  const value = typeof check.value === 'number'
    ? `${Number(check.value).toFixed(3)}${check.unit || ''}`
    : String(check.value ?? '—')
  return `${value} / ${check.operator} ${check.threshold}${check.unit || ''}`
}

function environmentLabel(key) {
  return {
    llm: 'LLM provider',
    llm_model: 'LLM model',
    avatar: '數字人引擎',
    avatar_id: '角色',
    asr: 'ASR',
    tts: 'TTS',
    reply_mode: '回覆模式',
  }[key] || key
}

onMounted(loadHistory)
onUnmounted(() => {
  clearRunTimers()
})

defineExpose({ handleVoiceEvent, loadHistory })
</script>

<style scoped>
.voice-test-panel { margin: 0 16px 12px; padding: 18px; color: var(--text-primary); background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: var(--radius-lg); box-shadow: var(--shadow-md); overflow: auto; max-height: min(72vh, 760px); }
.test-header, .result-heading, .history-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.test-eyebrow { color: var(--brand-light); font: 700 10px/1.4 var(--font-mono); letter-spacing: .12em; }
h2, h3, p { margin-top: 0; }
h2 { margin-bottom: 4px; font-size: 18px; }
h2 i { color: var(--brand-light); margin-right: 6px; }
.test-header p, .baseline-card p, .privacy-note { color: var(--text-tertiary); font-size: 12px; margin-bottom: 0; }
.icon-button { min-width: 36px; min-height: 36px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); color: var(--text-secondary); background: transparent; }
.test-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(220px, 280px); gap: 14px; margin-top: 16px; }
.test-form, .baseline-card, .result-card, .history-section { padding: 14px; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); background: color-mix(in srgb, var(--bg-surface-elevated) 70%, transparent); }
label, .field-heading { display: block; color: var(--text-secondary); font-size: 12px; font-weight: 700; }
.field-heading { display: flex; justify-content: space-between; margin-top: 12px; }
.field-heading span { color: var(--text-muted); font-family: var(--font-mono); font-weight: 500; }
input, textarea { width: 100%; margin-top: 6px; padding: 10px 11px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); color: var(--text-primary); background: var(--bg-primary); resize: vertical; }
input:focus, textarea:focus, button:focus-visible { outline: 2px solid var(--brand-light); outline-offset: 2px; }
.preset-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 9px 0 12px; }
.preset-button, .history-actions button { min-height: 34px; padding: 6px 9px; border: 1px solid var(--border-subtle); border-radius: 999px; color: var(--text-secondary); background: transparent; font-size: 11px; }
.run-button { width: 100%; min-height: 42px; border: 0; border-radius: var(--radius-sm); color: #fff; background: var(--brand); font-weight: 800; }
button:disabled { cursor: not-allowed; opacity: .45; }
.privacy-note { margin-top: 9px; }
.run-progress { display: flex; gap: 10px; align-items: center; margin: 10px 0; padding: 10px; border-radius: var(--radius-sm); background: var(--brand-surface); }
.run-progress span:last-child { display: grid; gap: 2px; }
.run-progress small { color: var(--text-tertiary); }
.progress-spinner { width: 18px; height: 18px; border: 2px solid var(--border-subtle); border-top-color: var(--brand-light); border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .progress-spinner { animation: none; } }
.error-message { margin: 8px 0; color: var(--danger); font-size: 12px; overflow-wrap: anywhere; }
.card-title { font-weight: 800; font-size: 13px; }
.baseline-card dl, .environment-list { margin: 12px 0; }
.baseline-card dl div, .environment-list div, .stage-list div { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--border-subtle); }
dt, .stage-list span { color: var(--text-tertiary); }
dd { margin: 0; font-family: var(--font-mono); }
.result-card, .history-section { margin-top: 14px; }
.result-heading h3 { display: inline; margin-left: 8px; font-size: 15px; }
.result-heading time { color: var(--text-muted); font-size: 11px; }
.status-badge { display: inline-flex; align-items: center; gap: 5px; padding: 4px 7px; border-radius: 999px; font-size: 11px; font-weight: 800; }
.status-passed { color: var(--success); background: color-mix(in srgb, var(--success) 12%, transparent); }
.status-failed { color: var(--danger); background: color-mix(in srgb, var(--danger) 12%, transparent); }
.status-running { color: var(--warning); background: color-mix(in srgb, var(--warning) 12%, transparent); }
.status-interrupted { color: var(--text-tertiary); background: var(--bg-primary); }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(100px, 1fr)); gap: 8px; margin: 14px 0; }
.metric-grid div { padding: 10px; border-radius: var(--radius-sm); background: var(--bg-primary); }
.metric-grid span, .content-pair span { display: block; color: var(--text-muted); font-size: 10px; margin-bottom: 4px; }
.metric-grid strong { font-family: var(--font-mono); font-size: 13px; }
.content-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.content-pair div { min-width: 0; padding: 10px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); }
.content-pair p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
.checks-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; margin-top: 12px; }
.check-row { display: grid; grid-template-columns: 18px minmax(90px, 1fr) auto; align-items: center; gap: 6px; font-size: 11px; }
.check-row strong { color: var(--text-tertiary); font-family: var(--font-mono); font-size: 10px; text-align: right; }
.check-pass { color: var(--success); }.check-fail { color: var(--danger); }
details { margin-top: 12px; } summary { cursor: pointer; color: var(--brand-light); font-size: 12px; font-weight: 700; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 10px; font-size: 11px; }
.stage-list strong { font-family: var(--font-mono); }
.history-heading h3 { margin-bottom: 2px; font-size: 15px; }.history-heading span { color: var(--text-muted); font-size: 11px; }
.history-actions { display: flex; gap: 6px; }.history-actions .danger-button { color: var(--danger); }
.history-list { display: grid; gap: 5px; margin-top: 12px; }
.history-item { display: grid; grid-template-columns: 26px minmax(0, 1fr) auto 14px; align-items: center; gap: 8px; width: 100%; min-height: 48px; padding: 7px 9px; border: 1px solid transparent; border-radius: var(--radius-sm); color: var(--text-primary); background: transparent; text-align: left; }
.history-item:hover, .history-item.selected { border-color: var(--border-subtle); background: var(--bg-primary); }
.history-copy { display: grid; min-width: 0; }.history-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }.history-copy small { color: var(--text-muted); overflow-wrap: anywhere; }
.history-latency { font: 600 11px/1 var(--font-mono); color: var(--text-secondary); }
.empty-state { padding: 22px; color: var(--text-muted); text-align: center; font-size: 12px; }
@media (max-width: 900px) { .test-grid, .detail-grid, .content-pair { grid-template-columns: 1fr; }.metric-grid { grid-template-columns: repeat(2, 1fr); }.checks-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .voice-test-panel { margin-inline: 8px; padding: 12px; }.history-heading { align-items: stretch; flex-direction: column; }.history-item { grid-template-columns: 24px minmax(0, 1fr) 14px; }.history-latency { display: none; } }
</style>
