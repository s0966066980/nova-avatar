// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import test from 'node:test'
import zhTW from '../src/locales/zh-TW.js'
import zhCN from '../src/locales/zh-CN.js'
import enUS from '../src/locales/en-US.js'
import { DECLARATIONS, EDGE_PRESETS, PREVIEW_SENTENCES, WHISPER_MODELS } from '../src/voiceTraining/constants.js'
import { stepList } from '../src/voiceTraining/flow.js'

const locales = { 'zh-TW': zhTW, 'zh-CN': zhCN, 'en-US': enUS }

function flatten(node, prefix = '') {
  return Object.entries(node).flatMap(([key, value]) => (
    value && typeof value === 'object' ? flatten(value, `${prefix}${key}.`) : [[`${prefix}${key}`, value]]
  ))
}
const entries = locale => new Map(flatten(locale.settings.voiceTraining))
const placeholders = text => [...String(text).matchAll(/\{(\w+)\}/g)].map(match => match[1]).sort().join(',')

test('聲線訓練的字串在三份 locales 完整：同樣的鍵、都不是空字串、佔位符一致', () => {
  const base = entries(zhTW)
  assert.ok(base.size > 300)
  for (const [name, locale] of Object.entries(locales)) {
    const own = entries(locale)
    assert.deepEqual([...own.keys()].sort(), [...base.keys()].sort(), name)
    for (const [key, text] of own) {
      assert.equal(typeof text, 'string', `${name} ${key}`)
      assert.ok(text.trim(), `${name} ${key} 是空的`)
      assert.equal(placeholders(text), placeholders(base.get(key)), `${name} ${key} 的佔位符與 zh-TW 不同`)
    }
  }
})

// Every key the screens ask for must exist: literal keys are read from the sources,
// computed keys are listed here from the same constants the screens loop over.
const dir = new URL('../src/components/voice-training/', import.meta.url)
const sources = readdirSync(dir).filter(name => name.endsWith('.vue')).map(name => readFileSync(new URL(name, dir), 'utf8'))

test('畫面用到的每一個靜態鍵都有字串', () => {
  const base = entries(zhTW)
  const used = new Set()
  for (const source of sources) {
    for (const match of source.matchAll(/\bt[xf]\('([A-Za-z0-9_.-]+)'[,)]/g)) used.add(match[1])
  }
  assert.ok(used.size > 100, `只找到 ${used.size} 個鍵`)
  const missing = [...used].filter(key => !base.has(key))
  assert.deepEqual(missing, [])
})

test('畫面以變數組出的鍵，每個可能的值都有字串', () => {
  const base = entries(zhTW)
  const expected = [
    ...['edge-test-teacher', 'self-recorded', 'written-authorization', 'development-unlicensed'].map(k => `source.kind.${k}`),
    ...EDGE_PRESETS.map(p => `source.presets.${p.key}`),
    ...stepList('edge').concat(stepList('upload')).map(s => `steps.${s.labelKey}`),
    ...['source', 'edge-confirm', 'upload', 'textEdge', 'textUpload', 'review', 'reviewEdge', 'preflight', 'job', 'done']
      .flatMap(k => [`screens.${k}.title`, `screens.${k}.desc`]),
    ...['admin', 'stage_connections', 'free_vram', 'environment', 'other_job', 'edge_acknowledgement', 'corpus', 'corpus_size', 'model_name'].map(k => `checks.${k}`),
    ...['pending', 'confirmed', 'excluded', 'unresolved'].map(k => `review.state.${k}`),
    ...['all', 'pending', 'attention', 'excluded'].map(k => `review.filter.${k}`),
    ...['pending', 'unresolved', 'none_confirmed'].map(k => `review.reason.${k}`),
    ...['unresolved', 'empty', 'checking'].map(k => `edgeReview.reason.${k}`),
    ...['pick_source'].map(k => `source.reason.${k}`),
    ...['check', 'session'].map(k => `edgeConfirm.reason.${k}`),
    ...['declare', 'consent', 'files', 'uploading'].map(k => `upload.reason.${k}`),
    ...['pick_txt', 'running', 'none'].map(k => `text.reason.${k}`),
    ...DECLARATIONS.flatMap(d => ['title', 'desc', 'consent'].map(k => `upload.decl.${d.key}.${k}`)),
    ...WHISPER_MODELS.map(m => `text.models.${m}`),
    ...['required', 'too_long'].map(k => `preflight.nameReason.${k}`),
    ...['pass', 'fail', 'warn'].map(k => `preflight.status.${k}`),
    ...['environment', 'synthesis', 'preparation', 'quality', 'training', 'export'].map(k => `job.stages.${k}`),
    ...['pending', 'running', 'done', 'failed', 'cancelled'].map(k => `job.stageStatus.${k}`),
    ...['running', 'cancelling', 'done', 'failed', 'cancelled'].map(k => `job.status.${k}`),
    ...PREVIEW_SENTENCES.map(s => `done.sentences.${s.key}`),
    ...['stage', 'confirmed', 'done', 'failed', 'cancelled', 'cancelling'].map(k => `announce.${k}`)
  ]
  assert.deepEqual(expected.filter(key => !base.has(key)), [])
})

test('使用限制標示的英文原文不出現在任何翻譯鍵的名稱，也沒有被改寫成其他語言', () => {
  for (const [name, locale] of Object.entries(locales)) {
    const text = [...entries(locale).values()].join('\n')
    assert.doesNotMatch(text, /僅限研究|仅限研究|開發用（Development|Research only|Dev only/, name)
  }
})

test('en-US 的長句沒有被硬塞進固定寬度：標籤與按鈕文字都能換行（CSS 不設固定 width）', () => {
  const root = readFileSync(new URL('../src/components/voice-training/VoiceTrainingWorkbench.vue', import.meta.url), 'utf8')
  const style = root.slice(root.indexOf('<style>'))
  assert.doesNotMatch(style, /\.vt-btn[^{]*\{[^}]*(?<![-\w])width:\s*\d/)
  assert.match(style, /overflow-wrap:\s*anywhere/)
  assert.match(style, /minmax\(0,\s*1fr\)/)
  assert.match(style, /prefers-reduced-motion/)
  assert.match(style, /min-height:\s*44px/)
})
