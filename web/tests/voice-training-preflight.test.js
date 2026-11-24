// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { checkView, startGate, vramGauge } from '../src/voiceTraining/preflight.js'

const pass = (id, extra = {}) => ({ id, label: id, status: 'pass', reason: '通過', detail: {}, ...extra })
const fail = (id, reason, detail = {}) => ({ id, label: id, status: 'fail', reason, detail })

test('通過、未通過、注意各有圖示與文字，不只靠顏色', () => {
  assert.deepEqual(checkView(pass('admin')), { id: 'admin', status: 'pass', tone: 'ok', icon: 'check-circle', reason: '通過', detail: {} })
  assert.equal(checkView(fail('stage_connections', '有 1 個舞台正在連線')).tone, 'bad')
  assert.equal(checkView(fail('stage_connections', 'x')).icon, 'x-circle')
  assert.equal(checkView({ id: 'corpus_size', status: 'warn', reason: '少於 15 分鐘' }).icon, 'alert')
  assert.equal(checkView({ id: 'corpus_size', status: 'warn', reason: 'r' }).tone, 'warn')
})

test('所有未通過的原因都列出，開始按鈕因此停用', () => {
  const preflight = {
    can_start: false,
    checks: [pass('admin'), fail('stage_connections', '有 1 個舞台正在連線，請先關閉'), fail('free_vram', '剩餘 6.1 GB，低於門檻 8 GB'), pass('environment')]
  }
  const gate = startGate(preflight, null)
  assert.equal(gate.canStart, false)
  assert.deepEqual(gate.reasons.map(r => r.id), ['stage_connections', 'free_vram'])
  assert.equal(gate.reasons[1].text, '剩餘 6.1 GB，低於門檻 8 GB')
})

test('只有 warn 時仍可開始（語料少於約 15 分鐘只提醒）', () => {
  const preflight = { can_start: true, checks: [pass('admin'), { id: 'corpus_size', status: 'warn', reason: '少於 15 分鐘', detail: {} }] }
  const gate = startGate(preflight, null)
  assert.equal(gate.canStart, true)
  assert.deepEqual(gate.reasons, [])
  assert.deepEqual(gate.warnings.map(w => w.id), ['corpus_size'])
})

test('還沒有檢查結果時不能開始；名稱問題在伺服器尚未回報時由用戶端補上', () => {
  assert.deepEqual(startGate(null, null), { canStart: false, reasons: [{ id: 'unchecked', text: '' }], warnings: [] })
  const ok = { can_start: true, checks: [pass('admin')] }
  assert.deepEqual(startGate(ok, 'required').reasons, [{ id: 'model_name', text: '', code: 'required' }])
  assert.equal(startGate(ok, 'required').canStart, false)
  const serverSaysName = { can_start: false, checks: [fail('model_name', '名稱必填')] }
  assert.deepEqual(startGate(serverSaysName, 'required').reasons.map(r => r.id), ['model_name'], '不重複列同一項')
})

test('伺服器說不能開始時即使沒有 fail 項也不能開始', () => {
  assert.equal(startGate({ can_start: false, checks: [pass('admin')] }, null).canStart, false)
})

test('顯存量表：剩餘與門檻的位置，沒有數字時回傳 null', () => {
  const gauge = vramGauge(pass('free_vram', { detail: { free_gb: 9.6, threshold_gb: 8 } }))
  assert.equal(gauge.free, 9.6)
  assert.equal(gauge.threshold, 8)
  assert.ok(gauge.freePct > gauge.thresholdPct && gauge.freePct <= 100)
  assert.ok(vramGauge(fail('free_vram', 'x', { free_gb: 6.1, threshold_gb: 8 })).freePct < vramGauge(fail('free_vram', 'x', { free_gb: 6.1, threshold_gb: 8 })).thresholdPct)
  assert.equal(vramGauge(fail('free_vram', '讀不到顯存')), null)
  assert.equal(vramGauge(pass('admin')), null)
})
