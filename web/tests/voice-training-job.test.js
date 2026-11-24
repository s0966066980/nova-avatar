// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  LOG_LIMIT, announcementFor, emptyLog, isActive, jobPercent, logTone, mergeLog, stageRows, transcriptionView
} from '../src/voiceTraining/jobView.js'

const stages = [
  { id: 'environment', label: '準備訓練環境', status: 'done', detail: '', progress: 1, seconds: 3 },
  { id: 'synthesis', label: '合成語料', status: 'running', detail: '已合成 10 / 220 句', progress: 0.045, seconds: null },
  { id: 'quality', label: '品質檢查', status: 'pending', detail: '', progress: 0, seconds: null }
]

test('階段列：狀態有圖示，進行中的轉圈，失敗與取消各有文字代碼', () => {
  const rows = stageRows({ stages: [...stages, { id: 'training', label: '訓練', status: 'failed', detail: 'x', progress: 0.5 }, { id: 'export', label: '寫入', status: 'cancelled', detail: '', progress: 0 }] })
  assert.deepEqual(rows.map(r => [r.id, r.status, r.icon, r.tone]), [
    ['environment', 'done', 'check-circle', 'ok'],
    ['synthesis', 'running', 'spin', 'run'],
    ['quality', 'pending', 'dot', 'idle'],
    ['training', 'failed', 'x-circle', 'bad'],
    ['export', 'cancelled', 'ban', 'idle']
  ])
  assert.equal(rows[1].detail, '已合成 10 / 220 句')
  assert.deepEqual(stageRows(null), [])
})

test('整體進度夾在 0 到 100，進行中與取消中都算有工作', () => {
  assert.equal(jobPercent({ progress: 41.6 }), 42)
  assert.equal(jobPercent({ progress: 140 }), 100)
  assert.equal(jobPercent(null), 0)
  assert.equal(isActive({ status: 'running' }), true)
  assert.equal(isActive({ status: 'cancelling' }), true)
  for (const status of ['done', 'failed', 'cancelled']) assert.equal(isActive({ status }), false)
  assert.equal(isActive(null), false)
})

test('日誌以絕對行號 offset 接續：只附加新行，next 取回應的值', () => {
  let log = emptyLog()
  log = mergeLog(log, { job_id: 'j1', start: 0, lines: ['a', 'b'], next: 2, total: 2 })
  assert.deepEqual(log.lines, ['a', 'b'])
  assert.equal(log.next, 2)
  log = mergeLog(log, { job_id: 'j1', start: 2, lines: ['c'], next: 3, total: 3 })
  assert.deepEqual(log.lines, ['a', 'b', 'c'])
  // A repeated answer adds nothing.
  log = mergeLog(log, { job_id: 'j1', start: 2, lines: ['c'], next: 3, total: 3 })
  assert.deepEqual(log.lines, ['a', 'b', 'c'])
  // An answer that starts before what we hold only adds the unseen tail.
  log = mergeLog(log, { job_id: 'j1', start: 1, lines: ['b', 'c', 'd'], next: 4, total: 4 })
  assert.deepEqual(log.lines, ['a', 'b', 'c', 'd'])
})

test('更早的行已被伺服器丟掉時標記 gap，換了工作就從頭開始', () => {
  let log = mergeLog(emptyLog(), { job_id: 'j1', start: 0, lines: ['a'], next: 1, total: 1 })
  log = mergeLog(log, { job_id: 'j1', start: 5, lines: ['f'], next: 6, total: 6 })
  assert.deepEqual(log.lines, ['a', 'f'])
  assert.equal(log.gap, true)
  log = mergeLog(log, { job_id: 'j2', start: 0, lines: ['x'], next: 1, total: 1 })
  assert.deepEqual(log.lines, ['x'])
  assert.equal(log.gap, false)
  assert.equal(log.jobId, 'j2')
})

test('日誌在記憶體只保留最近的行', () => {
  const lines = Array.from({ length: LOG_LIMIT + 50 }, (_, i) => `line ${i}`)
  const log = mergeLog(emptyLog(), { job_id: 'j', start: 0, lines, next: lines.length, total: lines.length })
  assert.equal(log.lines.length, LOG_LIMIT)
  assert.equal(log.lines.at(-1), `line ${LOG_LIMIT + 49}`)
  assert.equal(log.next, lines.length)
})

test('日誌行的語氣：失敗與重試是警告或錯誤，一般行無標記', () => {
  assert.equal(logTone('[合成] 第 3 句失敗（HTTP 429），等待 8 秒後重試'), 'warn')
  assert.equal(logTone('Traceback (most recent call last):'), 'error')
  assert.equal(logTone('[訓練] 步數 100/6000 loss 1.2'), '')
})

test('階段切換與終止狀態才朗讀，進度刻度不朗讀', () => {
  const running = { status: 'running', stage: 'synthesis' }
  assert.deepEqual(announcementFor(null, running), { code: 'stage', stage: 'synthesis' })
  assert.equal(announcementFor(running, { ...running }), null)
  assert.deepEqual(announcementFor(running, { status: 'running', stage: 'training' }), { code: 'stage', stage: 'training' })
  assert.deepEqual(announcementFor(running, { status: 'done', stage: 'export' }), { code: 'done' })
  assert.deepEqual(announcementFor(running, { status: 'failed', stage: 'training', error: '顯存不足' }), { code: 'failed', error: '顯存不足' })
  assert.deepEqual(announcementFor(running, { status: 'cancelled', stage: 'training' }), { code: 'cancelled' })
  assert.deepEqual(announcementFor({ status: 'running', stage: 'training' }, { status: 'cancelling', stage: 'training' }), { code: 'cancelling' })
})

test('自動逐字稿：顯示實際裝置與退回原因，CPU 退回時帶預估說明', () => {
  const running = transcriptionView({ state: 'running', model: 'medium', total: 40, done: 10, skipped: 1, failed: [], device: 'cpu', fallback_reason: '有舞台連線', cancel_requested: false })
  assert.equal(running.running, true)
  assert.equal(running.percent, 25)
  assert.equal(running.device, 'cpu')
  assert.equal(running.fallbackReason, '有舞台連線')
  assert.equal(running.slowNote, true)
  const gpu = transcriptionView({ state: 'running', total: 4, done: 1, failed: [], device: 'cuda', fallback_reason: null })
  assert.equal(gpu.slowNote, false)
  assert.equal(gpu.fallbackReason, '')
})

test('自動逐字稿缺少 device 欄位時不顯示裝置，也不丟例外', () => {
  const view = transcriptionView({ state: 'running', total: 0, done: 0, failed: [] })
  assert.equal(view.device, null)
  assert.equal(view.percent, 0)
  assert.equal(view.slowNote, false)
  assert.deepEqual(transcriptionView(null), { state: 'idle', running: false, finished: false, percent: 0, total: 0, done: 0, skipped: 0, failed: [], message: '', device: null, fallbackReason: '', slowNote: false, cancelling: false })
})

test('自動逐字稿結束狀態：完成、失敗、取消', () => {
  assert.equal(transcriptionView({ state: 'done', total: 3, done: 3, failed: [] }).finished, true)
  assert.equal(transcriptionView({ state: 'failed', message: '剩餘顯存不足', failed: [] }).message, '剩餘顯存不足')
  assert.equal(transcriptionView({ state: 'running', cancel_requested: true, total: 3, done: 1, failed: [] }).cancelling, true)
})
