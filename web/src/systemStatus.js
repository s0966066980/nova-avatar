// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Rows for the settings center's "系統狀態" list. Each row carries an icon,
// a name and a sentence, so the state never depends on colour alone.
// Tones: ok, warn, danger, busy (in progress) and idle (nothing running).
const STT_LABELS = { whisper: 'Whisper', funasr: 'FunASR' }

function consoleRow(connectionStatus, sessionId) {
  const name = '控制台連線'
  if (connectionStatus === 'connected') {
    return { tone: 'ok', icon: 'bi bi-broadcast', name, text: `WebRTC 已連線${sessionId > 0 ? ` · #${sessionId}` : ''}` }
  }
  if (connectionStatus === 'connecting') return { tone: 'busy', icon: 'bi bi-arrow-repeat', name, text: '連線中…' }
  return { tone: 'idle', icon: 'bi bi-broadcast', name, text: '尚未連線' }
}

function backendRow({ loading, error, runtime }) {
  const name = '後端服務'
  if (error) return { tone: 'danger', icon: 'bi bi-x-octagon', name, text: '無法讀取目前設定' }
  if (loading) return { tone: 'busy', icon: 'bi bi-arrow-repeat', name, text: '正在讀取設定…' }
  if (!runtime?.model_ready) return { tone: 'busy', icon: 'bi bi-hourglass-split', name, text: '數位人模型載入中' }
  return { tone: 'ok', icon: 'bi bi-check-circle', name, text: '模型已就緒' }
}

function llmRow(llmPartialGpu, runtime) {
  const name = '本機 LLM'
  const model = runtime?.llm?.model || ''
  if (llmPartialGpu) {
    return { tone: 'warn', icon: 'bi bi-exclamation-triangle', name, text: '未全部載入 GPU，回覆會變慢' }
  }
  return model
    ? { tone: 'ok', icon: 'bi bi-cpu', name, text: model }
    : { tone: 'idle', icon: 'bi bi-cpu', name, text: '尚未選擇模型' }
}

function sttRow(stt) {
  const engine = (stt?.engines || []).find(item => item.id === stt?.type)
  const label = engine?.label || STT_LABELS[stt?.type] || stt?.type || '未設定'
  return { tone: 'ok', icon: 'bi bi-mic', name: '語音辨識', text: [label, stt?.model_size].filter(Boolean).join(' · ') }
}

function stageRow(runtime) {
  const count = Number(runtime?.session_count) || 0
  return count > 0
    ? { tone: 'ok', icon: 'bi bi-display', name: '舞台場次', text: `${count} 個場次連線中` }
    : { tone: 'idle', icon: 'bi bi-display', name: '舞台場次', text: '目前沒有場次' }
}

export function systemStatusRows({ connectionStatus, sessionId, llmPartialGpu, loading, error, runtime, stt }) {
  const rows = [
    { id: 'console', ...consoleRow(connectionStatus, sessionId) },
    { id: 'stage', ...stageRow(runtime) },
    { id: 'backend', ...backendRow({ loading, error, runtime }) },
    { id: 'llm', ...llmRow(llmPartialGpu, runtime) },
    { id: 'stt', ...sttRow(stt) }
  ]
  const pending = runtime?.pending_settings?.items || []
  if (pending.length) {
    rows.push({ id: 'pending', tone: 'warn', icon: 'bi bi-clock-history', name: '待套用設定', text: `${pending.length} 項，斷線後更新` })
  }
  return rows
}
