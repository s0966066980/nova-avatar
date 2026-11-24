// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { all, button, loadComponent, mount, settle, textContent } from './helpers/componentHarness.js'
import { TrainingApiError } from '../src/voiceTraining/api.js'
import { createVoiceTrainingStore } from '../src/voiceTraining/store.js'

const url = name => new URL(`../src/components/voice-training/${name}.vue`, import.meta.url)
const ActionButton = await loadComponent(url('VtActionButton'))
const UsageBadge = await loadComponent(url('VtUsageBadge'))
const stubs = { './VtActionButton.vue': { default: ActionButton }, './VtUsageBadge.vue': { default: UsageBadge } }
const Preflight = await loadComponent(url('VtPreflight'), stubs)
const Review = await loadComponent(url('VtReview'), stubs)
const EdgeTextReview = await loadComponent(url('VtEdgeTextReview'), stubs)
const Job = await loadComponent(url('VtJob'), stubs)
const Done = await loadComponent(url('VtDone'), stubs)
const Text = await loadComponent(url('VtText'), stubs)
const EdgeConfirm = await loadComponent(url('VtEdgeConfirm'), stubs)

const byId = (root, id) => all(root, node => node.props.id === id)[0]

function storeWith(answers = {}) {
  const api = new Proxy({}, {
    get: (_t, name) => {
      if (name === 'lineAudioUrl') return (slug, id) => `/a/${slug}/${id}`
      return async (...args) => {
        const answer = answers[name]
        if (answer instanceof Error) throw answer
        return typeof answer === 'function' ? answer(...args) : answer
      }
    }
  })
  return createVoiceTrainingStore({ api })
}
const pass = id => ({ id, label: id, status: 'pass', reason: '通過', detail: {} })
const line = (id, extra = {}) => ({ id, original_name: `clip_${id}.wav`, text: '你好', normalized_text: '你好', unresolved: [], review: 'pending', ...extra })

test('VtActionButton：停用時仍可聚焦，aria-disabled 與 aria-describedby 指向原因，點擊不觸發', async t => {
  let activated = 0
  const view = mount(ActionButton, { label: '開始訓練', enabled: false, reasons: ['有 1 個舞台正在連線', '剩餘 6.1 GB'], reasonId: 'why-1', onActivate: () => { activated++ } })
  t.after(() => view.unmount())
  await settle()
  const btn = button(view.root, '開始訓練')
  assert.equal(btn.props['aria-disabled'], 'true')
  assert.equal(btn.props['aria-describedby'], 'why-1')
  assert.equal(btn.props.disabled, undefined, '不用 disabled，才能聚焦並被朗讀')
  assert.match(textContent(byId(view.root, 'why-1')), /舞台正在連線[\s\S]*剩餘 6\.1 GB/)
  btn.props.onClick()
  assert.equal(activated, 0)
  view.props.enabled = true
  await settle()
  assert.equal(button(view.root, '開始訓練').props['aria-disabled'], undefined)
  assert.equal(byId(view.root, 'why-1'), undefined)
  button(view.root, '開始訓練').props.onClick()
  assert.equal(activated, 1)
})

test('使用限制標示一律是英文原文加圖示，不隨語言翻譯', async t => {
  for (const label of ['Development only', 'Research / Non-commercial']) {
    const view = mount(UsageBadge, { label })
    t.after(() => view.unmount())
    await settle()
    assert.equal(textContent(view.root).trim(), label)
    assert.equal(all(view.root, n => n.type === 'i').length, 1, '有圖示')
  }
})

test('訓練前檢查：每個拒絕原因都列出，開始按鈕停用並以 aria-describedby 連到原因', async t => {
  const store = storeWith({
    getTraining: {
      job: null, settings: { min_free_vram_gb: 8 },
      preflight: {
        can_start: false,
        checks: [pass('admin'),
          { id: 'stage_connections', label: '舞台連線', status: 'fail', reason: '有 1 個舞台正在連線，請先關閉再重新檢查', detail: { count: 1 } },
          { id: 'free_vram', label: '剩餘顯存', status: 'fail', reason: '剩餘 6.1 GB，低於門檻 8 GB', detail: { free_gb: 6.1, threshold_gb: 8 } },
          { id: 'corpus_size', label: '語料份量', status: 'warn', reason: '少於 15 分鐘，可以開始但品質較差', detail: {} }]
      }
    }
  })
  store.chooseSource('upload')
  store.state.slug = 'c'
  store.state.name = '展廳導覽員'
  store.state.corpus = { slug: 'c', source: 'self-recorded', counts: { confirmed: 5 }, lines: [] }
  const view = mount(Preflight, { store })
  t.after(() => view.unmount())
  await settle()
  const start = button(view.root, '開始訓練')
  assert.equal(start.props['aria-disabled'], 'true')
  assert.equal(start.props['aria-describedby'], 'vt-why-start')
  const why = textContent(byId(view.root, 'vt-why-start'))
  assert.match(why, /有 1 個舞台正在連線/)
  assert.match(why, /剩餘 6\.1 GB，低於門檻 8 GB/)
  const text = textContent(view.root)
  assert.match(text, /語料份量/, 'warn 項目也顯示')
  assert.match(text, /Research \/ Non-commercial/)
  assert.ok(all(view.root, n => n.props.role === 'img' && /6\.1 GB/.test(n.props['aria-label'])).length, '顯存量表有文字替代')
})

test('訓練前檢查全數通過且名稱有效時才可開始', async t => {
  const store = storeWith({ getTraining: { job: null, settings: {}, preflight: { can_start: true, checks: [pass('admin')] } } })
  store.chooseSource('edge')
  store.state.slug = 'e'
  store.state.name = '展廳導覽員'
  const view = mount(Preflight, { store })
  t.after(() => view.unmount())
  await settle()
  assert.equal(button(view.root, '開始訓練').props['aria-disabled'], undefined)
  assert.match(textContent(view.root), /Development only/)
  assert.match(textContent(view.root), /不提供匯出/)
})

test('校對表：無法處理的片段標出、數字展開預覽、狀態有文字、全部確認不含無法處理的句子', async t => {
  const corpus = {
    slug: 'c', source: 'self-recorded',
    lines: [
      line('1', { text: '我有3個蘋果', normalized_text: '我有三個蘋果' }),
      line('2', { text: '編號 A12', normalized_text: '編號 A12', unresolved: [{ text: 'A12', start: 3, end: 6, reason: 'mixed' }] }),
      line('3', { review: 'confirmed' }),
      line('4', { review: 'excluded' })
    ]
  }
  const store = storeWith({ getCorpus: corpus })
  store.state.slug = 'c'
  store.state.corpus = corpus
  const view = mount(Review, { store })
  t.after(() => view.unmount())
  await settle()
  const rows = all(view.root, n => n.props.role === 'row' && n.props['data-row'])
  assert.equal(rows.length, 4)
  assert.ok(all(view.root, n => n.props.role === 'table').length === 1)
  assert.match(textContent(rows[0]), /展開後：\s*我有三個蘋果/)
  assert.ok(all(rows[0], n => n.props.class?.includes('vt-ex') && textContent(n) === '三').length)
  assert.ok(all(rows[1], n => n.props.class?.includes('vt-bad') && textContent(n) === 'A12').length, '無法處理的片段有標記')
  assert.match(textContent(rows[1]), /無法處理/)
  assert.match(textContent(rows[2]), /已確認/)
  assert.match(textContent(rows[3]), /已排除/)
  assert.ok(button(view.root, '全部標為已確認（1）'), '只算第 1 句，第 2 句無法處理')
  // Per-row controls carry the file name in their label.
  assert.ok(all(rows[0], n => n.type === 'button' && /^編輯 clip_1\.wav$/.test(n.props['aria-label'])).length)
  const play = all(rows[0], n => n.type === 'button' && /試聽 clip_1\.wav/.test(n.props['aria-label']))[0]
  assert.equal(play.props['aria-pressed'], false)
  play.props.onClick()
  await settle()
  assert.equal(store.state.review.playingId, '1')
  assert.equal(all(view.root, n => n.type === 'button' && /停止試聽 clip_1/.test(n.props['aria-label']))[0].props['aria-pressed'], true)
  // Next is disabled with the counts as reasons.
  const next = button(view.root, '訓練前檢查')
  assert.equal(next.props['aria-disabled'], 'true')
  assert.match(textContent(byId(view.root, 'vt-why-review')), /1 句待確認[\s\S]*1 句無法處理/)
})

test('Edge 上傳文字檔的校對表：合成前就標出無法念出的句子，不能試聽，全部可用才可開始', async t => {
  const store = storeWith({})
  store.chooseSource('edge')
  store.state.edge.textSrc = 'file'
  store.state.edge.sentences = ['你好', '價錢是$50']
  store.state.edge.preview = {
    ok: false, total: 2, estimatedSeconds: 8,
    items: [
      { index: 1, text: '你好', spoken: '你好', unresolved: [] },
      { index: 2, text: '價錢是$50', spoken: '價錢是$50', unresolved: [{ text: '$50', start: 3, end: 6, reason: 'currency' }] }
    ]
  }
  const view = mount(EdgeTextReview, { store })
  t.after(() => view.unmount())
  await settle()
  const text = textContent(view.root)
  assert.match(text, /第 2 句的 「\$50」 無法確定怎麼念|第 2 句的 「\$50」/)
  assert.doesNotMatch(text, /第 2 行/, '用「第 N 句」，不用「行」')
  assert.ok(all(view.root, n => n.type === 'button' && n.props['aria-disabled'] === 'true' && /目前無法試聽/.test(n.props['aria-label'])).length === 2)
  assert.equal(button(view.root, '訓練前檢查').props['aria-disabled'], 'true')
  assert.match(textContent(byId(view.root, 'vt-why-edge-review')), /1 句無法處理/)
  assert.ok(button(view.root, '移除'))
})

test('內建句庫免校對：直接說明已預先確認，下一步可用', async t => {
  const store = storeWith({})
  store.chooseSource('edge')
  const view = mount(EdgeTextReview, { store })
  t.after(() => view.unmount())
  await settle()
  assert.match(textContent(view.root), /內建句庫已預先確認/)
  assert.equal(button(view.root, '訓練前檢查').props['aria-disabled'], undefined)
})

test('訓練進度：日誌是 role=log 可鍵盤聚焦；取消要先確認，確認區預設聚焦「繼續訓練」', async t => {
  const store = storeWith({ cancelTraining: { id: 'j', status: 'cancelling', stages: [] } })
  store.state.job = { id: 'j', status: 'running', stage: 'training', progress: 42, name: 'n', stages: [{ id: 'training', label: '訓練', status: 'running', detail: '步數 10 / 100', progress: 0.1 }] }
  store.state.log = { jobId: 'j', lines: ['[訓練] step 10', '[合成] 第 3 句失敗（HTTP 429），等待 8 秒後重試'], next: 2, gap: false }
  const view = mount(Job, { store })
  t.after(() => view.unmount())
  await settle()
  const log = all(view.root, n => n.props.role === 'log')[0]
  assert.equal(log.props.tabindex, '0')
  assert.match(textContent(log), /step 10/)
  assert.ok(all(log, n => n.props.class === 'warn').length === 1, '重試那行標為警告')
  const bar = all(view.root, n => n.props.role === 'progressbar')[0]
  assert.equal(bar.props['aria-valuenow'], 42)
  assert.match(textContent(view.root), /步數 10 \/ 100/)
  assert.equal(all(view.root, n => n.props.role === 'group').length, 0)
  button(view.root, '取消訓練').props.onClick()
  await settle()
  const confirm = all(view.root, n => n.props.role === 'group' && n.props['aria-labelledby'] === 'vt-cc-t')[0]
  assert.ok(confirm)
  assert.match(textContent(confirm), /訓練進度不會保留[\s\S]*語料會保留/)
  confirm.props.onKeydown?.({ key: 'Escape' })
  button(view.root, '繼續訓練').props.onClick()
  await settle()
  assert.equal(store.state.confirmCancel, false)
  assert.equal(store.state.job.status, 'running')
})

test('完成畫面：標示、三句預設試聽（無自訂句子）、不含任何下載', async t => {
  const store = storeWith({})
  store.state.job = { id: 'j', status: 'done', name: '展廳導覽員', voice_id: 'trained-1', usage: 'Development only', source: 'edge-test-teacher', metrics: { step: 3000, total_steps: 3000, training_seconds: 2400 }, stages: [] }
  let opened = 0
  const view = mount(Done, { store, onOpenProfiles: () => { opened++ } })
  t.after(() => view.unmount())
  await settle()
  const text = textContent(view.root)
  assert.match(text, /Development only/)
  assert.match(text, /不提供匯出/)
  assert.match(text, /trained-1/)
  assert.match(text, /3000 \/ 3000 步，訓練約 40 分鐘/)
  assert.ok(text.includes('今天是2026年11月24日') && text.includes('Welcome to the exhibition hall'))
  assert.equal(all(view.root, n => n.type === 'input' || n.type === 'textarea').length, 0, '第一版沒有自訂句子')
  assert.equal(all(view.root, n => n.type === 'a' || n.props.download !== undefined).length, 0)
  assert.equal(all(view.root, n => n.type === 'button' && /下載|匯出|download|export/i.test(textContent(n))).length, 0, '沒有任何下載或匯出的按鈕')
  const players = all(view.root, n => n.type === 'button' && n.props['aria-pressed'] !== undefined)
  assert.equal(players.length, 3)
  assert.deepEqual(players.map(n => n.props['aria-disabled']), [undefined, undefined, undefined], '三句都能試聽')
  button(view.root, '到數位人設定檔選用').props.onClick()
  assert.equal(opened, 1)
})

test('自動逐字稿：顯示實際裝置、退回原因與 CPU 較慢的預估', async t => {
  const store = storeWith({})
  store.chooseSource('upload')
  store.state.slug = 'c'
  store.state.tr.src = 'whisper'
  store.state.transcriptionStatus = { state: 'running', model: 'medium', total: 40, done: 10, failed: [], device: 'cpu', fallback_reason: '有舞台連線' }
  const view = mount(Text, { store })
  t.after(() => view.unmount())
  await settle()
  const text = textContent(view.root)
  assert.match(text, /使用 CPU（int8）辨識/)
  assert.match(text, /改用 CPU 的原因：\s*有舞台連線/)
  assert.match(text, /預估剩餘約 \d+ 分鐘/)
  assert.equal(button(view.root, '下一步') ?? null, null)
  assert.ok(all(view.root, n => n.props.role === 'progressbar' && n.props['aria-valuenow'] === 10).length)
  assert.equal(button(view.root, '進入校對').props['aria-disabled'], 'true')
})

test('匯入逐字稿失敗：列出每一條問題', async t => {
  const store = storeWith({ importTranscripts: new TrainingApiError('x', { status: 422, problems: ['第 2 行缺少分隔符「|」', '找不到對應的錄音：clip_9'] }) })
  store.chooseSource('upload')
  store.state.slug = 'c'
  await store.importTranscripts([{ name: 'metadata.csv' }])
  const view = mount(Text, { store })
  t.after(() => view.unmount())
  await settle()
  const alert = all(view.root, n => n.props.role === 'alert' && /逐字稿無法使用/.test(textContent(n)))[0]
  assert.ok(alert)
  assert.match(textContent(alert), /第 2 行缺少分隔符[\s\S]*clip_9/)
})

test('完成畫面：三個試聽按鈕各自向伺服器要那一句，播放回傳的音檔', async t => {
  const requested = []
  const store = storeWith({ previewVoice: (voiceId, sentence) => { requested.push([voiceId, sentence]); return new Blob(['RIFF'], { type: 'audio/wav' }) } })
  store.state.job = { id: 'j', status: 'done', name: '展廳導覽員', voice_id: 'trained-1', usage: 'Development only', source: 'edge-test-teacher', metrics: {}, stages: [] }
  const view = mount(Done, { store })
  t.after(() => view.unmount())
  await settle()
  const players = all(view.root, n => n.type === 'button' && n.props['aria-pressed'] !== undefined)
  assert.equal(players.length, 3)
  for (const player of players) { player.props.onClick(); await settle() }
  assert.deepEqual(requested, [['trained-1', 'zh'], ['trained-1', 'digits'], ['trained-1', 'en']])
  const audio = all(view.root, n => n.type === 'audio')[0]
  assert.match(audio.props.src, /^blob:/)
  assert.equal(all(view.root, n => /目前只能念固定/.test(textContent(n))).length, 0, '不再說只有一句可聽')
  URL.revokeObjectURL(audio.props.src)
})

test('Edge 確認畫面：顯示並使用伺服器給的條文，沒有條文時不能勾選', async t => {
  const clause = { reference: '伺服器出處 §9', effective: '2031-02-03', text: 'Only the server knows this clause wording.' }
  const store = storeWith({ getTraining: { job: null, preflight: null, settings: { edge_clause: clause } } })
  store.chooseSource('edge')
  await store.loadEdgeClause()
  const view = mount(EdgeConfirm, { store })
  t.after(() => view.unmount())
  await settle()
  const text = textContent(view.root)
  assert.ok(text.includes(clause.reference) && text.includes(clause.text), '畫面顯示伺服器的條文')
  assert.ok(all(view.root, n => n.type === 'blockquote' && textContent(n).includes(clause.text)).length === 1)
  assert.equal(all(view.root, n => n.type === 'input' && n.props.type === 'checkbox' && n.props.disabled)[0], undefined)

  const bare = storeWith({ getTraining: { job: null, preflight: null, settings: {} } })
  bare.chooseSource('edge')
  await bare.loadEdgeClause()
  const missing = mount(EdgeConfirm, { store: bare })
  t.after(() => missing.unmount())
  await settle()
  assert.ok(!textContent(missing.root).includes('Microsoft Services Agreement'), '前端沒有自己的條文可顯示')
  assert.ok(all(missing.root, n => n.type === 'input' && n.props.type === 'checkbox' && n.props.disabled).length === 1, '沒有條文不能勾選')
  assert.equal(all(missing.root, n => n.type === 'blockquote').length, 0)
  assert.equal(button(missing.root, '確認並繼續').props['aria-disabled'], 'true')
  assert.match(textContent(byId(missing.root, 'vt-why-edge')), /伺服器還沒提供/)
})
