// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  classifyUploadFile, edgeConfirmGate, labelDerivation, nameProblem, newSlug, sourceGate, stepList, uploadGate, usageLabelFor
} from '../src/voiceTraining/flow.js'
import { USAGE_DEV, USAGE_RESEARCH } from '../src/voiceTraining/constants.js'

test('使用限制標示取最嚴格者：Edge 與開發用為 Development only，自錄與書面授權為 Research / Non-commercial', () => {
  assert.equal(usageLabelFor('edge-test-teacher'), USAGE_DEV)
  assert.equal(usageLabelFor('development-unlicensed'), USAGE_DEV)
  assert.equal(usageLabelFor('self-recorded'), USAGE_RESEARCH)
  assert.equal(usageLabelFor('written-authorization'), USAGE_RESEARCH)
  assert.equal(usageLabelFor(null), USAGE_DEV, '來源未宣告時取最嚴格')
})

test('標示的推導列出語料來源、底模與結果；Edge 另標不提供匯出', () => {
  const edge = labelDerivation('edge-test-teacher')
  assert.deepEqual([edge.corpus, edge.base, edge.result], [USAGE_DEV, USAGE_RESEARCH, USAGE_DEV])
  assert.equal(edge.noExport, true)
  const own = labelDerivation('self-recorded')
  assert.deepEqual([own.corpus, own.base, own.result], [USAGE_RESEARCH, USAGE_RESEARCH, USAGE_RESEARCH])
  assert.equal(own.noExport, false)
})

test('步驟列：第 2 步名稱依來源改變，Edge 內建句庫略過校對', () => {
  assert.deepEqual(stepList('upload').map(s => s.id), ['source', 'text', 'review', 'preflight', 'job', 'done'])
  assert.equal(stepList('upload')[1].labelKey, 'transcripts')
  assert.equal(stepList('edge')[1].labelKey, 'readingText')
  assert.equal(stepList(null)[1].labelKey, 'transcripts')
})

test('來源與上傳的下一步條件都給出原因代碼', () => {
  assert.deepEqual(sourceGate(null), ['pick_source'])
  assert.deepEqual(sourceGate('edge'), [])
  assert.deepEqual(uploadGate({ declared: '', consent: false, accepted: 0 }), ['declare', 'files'])
  assert.deepEqual(uploadGate({ declared: 'own', consent: false, accepted: 0 }), ['consent', 'files'])
  assert.deepEqual(uploadGate({ declared: 'own', consent: true, accepted: 3 }), [])
  assert.deepEqual(uploadGate({ declared: 'dev', consent: false, accepted: 1 }), [], '開發用不需要勾選聲明')
  assert.deepEqual(uploadGate({ declared: 'own', consent: true, accepted: 1, uploading: true }), ['uploading'])
})

test('Edge 確認：沒勾選、登入失效或伺服器沒給條文都不能繼續', () => {
  assert.deepEqual(edgeConfirmGate({ checked: false, sessionExpired: false, clauseReady: true }), ['check'])
  assert.deepEqual(edgeConfirmGate({ checked: true, sessionExpired: true, clauseReady: true }), ['session'])
  assert.deepEqual(edgeConfirmGate({ checked: true, sessionExpired: false, clauseReady: true }), [])
  assert.deepEqual(edgeConfirmGate({ checked: true, sessionExpired: false, clauseReady: false }), ['clause'], '沒有伺服器條文就不能確認')
  assert.deepEqual(edgeConfirmGate({ checked: true, sessionExpired: false }), ['clause'], '沒說明就視為沒有條文')
})

test('名稱：必填、最多 40 字（以字元計）', () => {
  assert.equal(nameProblem(''), 'required')
  assert.equal(nameProblem('   '), 'required')
  assert.equal(nameProblem('字'.repeat(41)), 'too_long')
  assert.equal(nameProblem('字'.repeat(40)), null)
  assert.equal(nameProblem(' 展廳導覽員 '), null)
})

test('slug 由用戶端產生並符合伺服器的 ID 規則，每次不同', () => {
  const ids = new Set()
  for (let i = 0; i < 20; i++) {
    const slug = newSlug('edge', new Date('2026-11-24T08:05:09Z'))
    assert.match(slug, /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/)
    assert.match(slug, /^edge-20261124-080509-[0-9a-f]{4}$/)
    ids.add(slug)
  }
  assert.ok(ids.size > 1)
})

test('錄音檔先在用戶端擋掉副檔名、大小與重複檔名，伺服器仍會再檢查', () => {
  const file = (name, size = 1000) => ({ name, size })
  assert.equal(classifyUploadFile(file('clip.wav'), []), null)
  assert.equal(classifyUploadFile(file('clip.WAV'), []), null)
  assert.deepEqual(classifyUploadFile(file('intro.wmv'), []), { code: 'format', detail: '.wmv' })
  assert.deepEqual(classifyUploadFile(file('big.wav', 21 * 1024 * 1024), []), { code: 'size', detail: '20' })
  assert.deepEqual(classifyUploadFile(file('clip.wav'), ['clip.wav']), { code: 'duplicate', detail: 'clip.wav' })
  assert.deepEqual(classifyUploadFile(file('noext'), []), { code: 'format', detail: '' })
})
