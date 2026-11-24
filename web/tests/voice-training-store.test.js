// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { TrainingApiError } from '../src/voiceTraining/api.js'
import { MSA_CLAUSE } from '../src/voiceTraining/constants.js'
import { createVoiceTrainingStore } from '../src/voiceTraining/store.js'

// A recording fake of createTrainingApi(): ``answers`` overrides any method.
function fakeApi(answers = {}) {
  const calls = []
  const record = name => async (...args) => {
    calls.push([name, ...args])
    const answer = answers[name]
    if (answer instanceof Error) throw answer
    return typeof answer === 'function' ? answer(...args) : answer
  }
  const api = new Proxy({}, {
    get: (_target, name) => {
      if (name === 'lineAudioUrl') return (slug, id) => `/audio/${slug}/${id}`
      return record(String(name))
    }
  })
  return { api, calls, names: () => calls.map(call => call[0]) }
}
const line = (id, extra = {}) => ({ id, original_name: `${id}.wav`, text: '你好', normalized_text: '你好', unresolved: [], review: 'pending', ...extra })
const summary = (slug, source) => ({ slug, source, counts: { pending: 0, confirmed: 0, excluded: 0, total: 0 } })
const stage = id => ({ id, label: id, status: 'running', detail: '', progress: 0 })
const job = (status, extra = {}) => ({ id: 'j1', status, stage: 'training', stages: [stage('training')], progress: 10, name: '展廳', usage: 'Development only', ...extra })

test('Edge 確認：沒勾選不能繼續；勾選後先建立語料再把條文原文記錄到伺服器', async () => {
  const { api, calls, names } = fakeApi({ createCorpus: slug => summary(slug.slug, 'edge-test-teacher'), recordAcknowledgement: { acknowledged_at: 't' } })
  const store = createVoiceTrainingStore({ api })
  store.chooseSource('edge')
  store.go('edge-confirm')
  await store.confirmEdge()
  assert.deepEqual(names(), [], '沒勾選時不呼叫伺服器')
  assert.equal(store.state.screen, 'edge-confirm')
  store.state.edge.checked = true
  await store.confirmEdge()
  assert.deepEqual(names(), ['createCorpus', 'recordAcknowledgement'])
  assert.equal(calls[0][1].source, 'edge-test-teacher')
  assert.equal(calls[1][2], MSA_CLAUSE.text)
  assert.equal(calls[1][1], calls[0][1].slug)
  assert.equal(store.state.screen, 'text')
  await store.confirmEdge()
  assert.equal(names().length, 2, '同一份語料不重複記錄')
})

test('Edge 確認被伺服器拒絕時留在原畫面並顯示原因', async () => {
  const { api } = fakeApi({ createCorpus: c => summary(c.slug, 'edge-test-teacher'), recordAcknowledgement: new TrainingApiError('顯示的條文與目前不一致', { status: 400 }) })
  const store = createVoiceTrainingStore({ api })
  store.chooseSource('edge')
  store.go('edge-confirm')
  store.state.edge.checked = true
  await store.confirmEdge()
  assert.equal(store.state.screen, 'edge-confirm')
  assert.equal(store.state.error, '顯示的條文與目前不一致')
})

test('上傳：未宣告或未勾選聲明不能送出；換宣告會清除聲明；送出後語料已建立就鎖定宣告', async () => {
  const { api, calls, names } = fakeApi({
    createCorpus: c => summary(c.slug, c.source),
    uploadLine: (_slug, file) => ({ line: line('000001'), duration: 4.2 })
  })
  const store = createVoiceTrainingStore({ api })
  store.chooseSource('upload')
  await store.addUploadFiles([{ name: 'clip_001.wav', size: 10 }])
  assert.deepEqual(names(), [], '沒有宣告，什麼都不送')
  store.selectDeclaration('own')
  store.state.up.consent = true
  store.selectDeclaration('written')
  assert.equal(store.state.up.consent, false, '換選項清除聲明')
  await store.addUploadFiles([{ name: 'clip_001.wav', size: 10 }])
  assert.deepEqual(names(), [], '沒勾聲明不送')
  store.state.up.consent = true
  await store.addUploadFiles([{ name: 'clip_001.wav', size: 10 }, { name: 'intro.wmv', size: 10 }, { name: 'clip_001.wav', size: 10 }])
  assert.deepEqual(names(), ['createCorpus', 'uploadLine'])
  assert.deepEqual(calls[0][1].source, 'written-authorization')
  assert.equal(calls[0][1].consent, true)
  assert.deepEqual(store.state.up.files.map(f => [f.name, f.status, f.code]), [
    ['clip_001.wav', 'accepted', undefined], ['intro.wmv', 'rejected', 'format'], ['clip_001.wav', 'rejected', 'duplicate']
  ])
  assert.equal(store.state.up.locked, true)
  store.selectDeclaration('own')
  assert.equal(store.state.up.declared, 'written', '語料建立後宣告不再改變')
})

test('上傳被伺服器拒絕的檔案列出原因，其餘檔案不受影響', async () => {
  const { api } = fakeApi({
    createCorpus: c => summary(c.slug, c.source),
    uploadLine: (_slug, file) => {
      if (file.name === 'bad.wav') throw new TrainingApiError('無法解碼', { status: 422 })
      return { line: line('000001'), duration: 3 }
    }
  })
  const store = createVoiceTrainingStore({ api })
  store.chooseSource('upload')
  store.selectDeclaration('dev')
  await store.addUploadFiles([{ name: 'bad.wav', size: 1 }, { name: 'ok.wav', size: 1 }])
  assert.deepEqual(store.state.up.files.map(f => [f.name, f.status, f.reason || '']), [['bad.wav', 'rejected', '無法解碼'], ['ok.wav', 'accepted', '']])
  assert.equal(store.acceptedCount.value, 1)
})

test('逐字稿匯入錯誤保留每一條問題；成功後重新載入校對表', async () => {
  const { api } = fakeApi({
    importTranscripts: new TrainingApiError('逐字稿有問題', { status: 422, problems: ['第 2 行缺少分隔符'] }),
    getCorpus: { ...summary('c', 'self-recorded'), lines: [line('1')] }
  })
  const store = createVoiceTrainingStore({ api })
  store.state.slug = 'c'
  await store.importTranscripts([{ name: 'metadata.csv' }])
  assert.deepEqual(store.state.tr.problems, ['第 2 行缺少分隔符'])
  assert.equal(store.state.tr.imported, null)
  const ok = fakeApi({ importTranscripts: { applied: 2, without_transcript: ['000003'] }, getCorpus: { ...summary('c', 'self-recorded'), lines: [line('1')] } })
  const store2 = createVoiceTrainingStore({ api: ok.api })
  store2.state.slug = 'c'
  await store2.importTranscripts([{ name: 'a.txt' }])
  assert.deepEqual(store2.state.tr.imported, { applied: 2, without: ['000003'] })
  assert.equal(store2.state.tr.problems.length, 0)
  assert.deepEqual(ok.names(), ['importTranscripts', 'getCorpus'])
})

test('批次確認只送出可確認句子的 ID（待確認、有文字、沒有未解項）', async () => {
  const lines = [line('1'), line('2', { review: 'confirmed' }), line('3', { unresolved: [{ text: '1/2', start: 0, end: 3 }] }), line('4', { text: '' }), line('5')]
  const { api, calls } = fakeApi({ getCorpus: { ...summary('c', 'self-recorded'), lines }, confirmLines: { confirmed: 2 } })
  const store = createVoiceTrainingStore({ api })
  store.state.slug = 'c'
  await store.loadCorpus()
  await store.confirmAllPending()
  const confirm = calls.find(call => call[0] === 'confirmLines')
  assert.deepEqual(confirm.slice(1), ['c', ['1', '5']])
})

test('編輯後若已沒有無法處理的片段，自動確認；仍有就留在無法處理', async () => {
  let resolved = true
  const { api, calls } = fakeApi({
    getCorpus: { ...summary('c', 'self-recorded'), lines: [line('1', { unresolved: [{ text: 'A1', start: 0, end: 2 }] })] },
    editLine: (_slug, id, changes) => (changes.review
      ? { line: line(id, { text: 'x', review: changes.review }), summary: {} }
      : { line: line(id, { text: changes.text, unresolved: resolved ? [] : [{ text: '3.5.1', start: 0, end: 5 }] }), summary: {} })
  })
  const store = createVoiceTrainingStore({ api })
  store.state.slug = 'c'
  await store.loadCorpus()
  store.startEdit('1')
  await store.saveEdit('1', '甲一')
  assert.deepEqual(calls.filter(c => c[0] === 'editLine').map(c => c[3]), [{ text: '甲一' }, { review: 'confirmed' }])
  assert.equal(store.state.review.editingId, null)
  resolved = false
  calls.length = 0
  await store.saveEdit('1', '3.5.1 版')
  assert.deepEqual(calls.filter(c => c[0] === 'editLine').map(c => c[3]), [{ text: '3.5.1 版' }])
  assert.equal(store.state.corpus.lines[0].review, 'pending')
})

test('Edge 上傳文字檔：讀入後在合成前預覽，改寫或移除句子會重新預覽，沒有未解項才能繼續', async () => {
  let call = 0
  const previewFor = sentences => ({
    ok: !sentences.some(text => /A12/.test(text)), total: sentences.length, estimated_seconds: 3,
    items: sentences.map((text, i) => ({ index: i + 1, text, spoken: text, unresolved: /A12/.test(text) ? [{ text: 'A12', start: 0, end: 3, reason: 'x' }] : [] }))
  })
  const { api, calls } = fakeApi({ post: (_path, body) => { call++; return previewFor(body.sentences.split('\n')) } })
  const store = createVoiceTrainingStore({ api })
  store.chooseSource('edge')
  store.state.edge.textSrc = 'file'
  await store.loadEdgeTextFile({ text: async () => '你好\nA12 號\n你好\n' })
  assert.deepEqual(store.state.edge.sentences, ['你好', 'A12 號'])
  assert.equal(store.edgeReview.value.canContinue, false)
  await store.editEdgeSentence(1, '甲一二號')
  assert.deepEqual(store.state.edge.sentences, ['你好', '甲一二號'])
  assert.equal(store.edgeReview.value.canContinue, true)
  await store.removeEdgeSentence(0)
  assert.deepEqual(store.state.edge.sentences, ['甲一二號'])
  assert.equal(call, 3)
  assert.equal(calls.every(c => c[1] === '/api/tts/training/text-preview'), true)
})

test('開始訓練：內建句庫送 preset，上傳文字檔送 sentences；伺服器拒絕時顯示它回報的檢查', async () => {
  const started = job('running')
  const { api, calls } = fakeApi({ startTraining: started, getTraining: { job: started, preflight: { can_start: true, checks: [] }, settings: {} }, getTrainingLog: { job_id: 'j1', start: 0, lines: ['啟動'], next: 1, total: 1 } })
  const store = createVoiceTrainingStore({ api })
  store.chooseSource('edge')
  store.state.slug = 'edge-1'
  store.state.name = '展廳'
  store.state.edge.preset = 'quick-test'
  store.state.edge.voice = 'zh-TW-YunJheNeural'
  await store.startTraining()
  assert.deepEqual(calls.find(c => c[0] === 'startTraining')[1], { corpus: 'edge-1', name: '展廳', voice: 'zh-TW-YunJheNeural', preset: 'quick-test' })
  assert.equal(store.state.screen, 'job')
  store.state.edge.textSrc = 'file'
  store.state.edge.sentences = ['你好', '再見']
  await store.startTraining()
  assert.deepEqual(calls.filter(c => c[0] === 'startTraining')[1][1], { corpus: 'edge-1', name: '展廳', voice: 'zh-TW-YunJheNeural', sentences: '你好\n再見' })

  const refused = { can_start: false, checks: [{ id: 'stage_connections', status: 'fail', reason: '有 1 個舞台正在連線' }] }
  const second = fakeApi({ startTraining: new TrainingApiError('不能開始', { status: 409, preflight: refused }) })
  const store2 = createVoiceTrainingStore({ api: second.api })
  store2.chooseSource('upload')
  store2.state.slug = 'c'
  store2.state.name = 'n'
  store2.go('preflight')
  await store2.startTraining()
  assert.equal(store2.state.screen, 'preflight')
  assert.equal(store2.gate.value.canStart, false)
  assert.deepEqual(store2.gate.value.reasons.map(r => r.id), ['stage_connections'])
})

test('名稱格式不合時前端不送出開始請求', async () => {
  const { api, names } = fakeApi({})
  const store = createVoiceTrainingStore({ api })
  store.chooseSource('upload')
  store.state.slug = 'c'
  store.state.name = '   '
  await store.startTraining()
  assert.deepEqual(names(), [])
})

test('訓練進度輪詢：日誌依 offset 接續，工作完成後通知清單更新並保留結果', async () => {
  const responses = [
    { job: job('running'), log: { job_id: 'j1', start: 0, lines: ['a', 'b'], next: 2, total: 2 } },
    { job: job('running', { stage: 'export' }), log: { job_id: 'j1', start: 2, lines: ['c'], next: 3, total: 3 } },
    { job: job('done', { stage: 'export', voice_id: 'trained-1', progress: 100 }), log: { job_id: 'j1', start: 3, lines: ['完成'], next: 4, total: 4 } }
  ]
  let index = -1
  const offsets = []
  let refreshed = 0
  const { api } = fakeApi({
    getTraining: () => ({ job: responses[Math.min(index + 1, 2)].job, preflight: null, settings: {} }),
    getTrainingLog: offset => { index++; offsets.push(offset); return responses[index].log }
  })
  const store = createVoiceTrainingStore({ api, onModelsChanged: () => { refreshed++ } })
  store.go('job')
  await store.pollJob()
  await store.pollJob()
  assert.equal(store.state.job.status, 'running')
  await store.pollJob()
  assert.deepEqual(offsets, [0, 2, 3])
  assert.deepEqual(store.state.log.lines, ['a', 'b', 'c', '完成'])
  assert.equal(store.state.job.status, 'done')
  assert.equal(refreshed, 1)
  assert.equal(store.state.announcement.code, 'done')
  assert.equal(store.shouldPoll.value, false)
})

test('取消訓練要先確認；繼續訓練不呼叫取消', async () => {
  const { api, names } = fakeApi({ cancelTraining: job('cancelling') })
  const store = createVoiceTrainingStore({ api })
  store.state.job = job('running')
  store.askCancel()
  assert.equal(store.state.confirmCancel, true)
  store.keepTraining()
  assert.equal(store.state.confirmCancel, false)
  assert.deepEqual(names(), [])
  store.askCancel()
  await store.confirmCancelJob()
  assert.deepEqual(names(), ['cancelTraining'])
  assert.equal(store.state.job.status, 'cancelling')
  assert.equal(store.state.confirmCancel, false)
})

test('自動逐字稿：啟動、輪詢顯示裝置與退回原因，完成後載入校對表', async () => {
  const statuses = [
    { state: 'running', model: 'medium', total: 4, done: 1, failed: [], device: 'cpu', fallback_reason: '有舞台連線' },
    { state: 'done', model: 'medium', total: 4, done: 4, failed: [], device: 'cpu', fallback_reason: '有舞台連線' }
  ]
  let n = 0
  const { api, names } = fakeApi({
    startTranscription: statuses[0], getTranscription: () => statuses[Math.min(n++, 1)],
    getCorpus: { ...summary('c', 'self-recorded'), lines: [line('1')] }
  })
  const store = createVoiceTrainingStore({ api })
  store.state.slug = 'c'
  await store.startAutoTranscription()
  assert.equal(store.transcription.value.device, 'cpu')
  assert.equal(store.transcription.value.fallbackReason, '有舞台連線')
  await store.pollTranscription()
  await store.pollTranscription()
  assert.equal(store.transcription.value.state, 'done')
  assert.ok(names().includes('getCorpus'))
  assert.equal(store.transcriptionShouldPoll.value, false)
})

test('首頁：列出語料與進行中的工作；繼續上傳語料回到校對，Edge 語料回到朗讀文字', async () => {
  const { api } = fakeApi({
    listCorpora: { corpora: [summary('a', 'self-recorded'), summary('b', 'edge-test-teacher')] },
    getTraining: { job: job('running'), preflight: null, settings: {} },
    getCorpus: slug => ({ ...summary(slug, slug === 'a' ? 'self-recorded' : 'edge-test-teacher'), lines: [] })
  })
  const store = createVoiceTrainingStore({ api })
  await store.refreshHome()
  assert.equal(store.state.corpora.length, 2)
  assert.equal(store.state.job.status, 'running')
  await store.openCorpus('a')
  assert.equal(store.state.screen, 'review')
  assert.equal(store.state.path, 'upload')
  await store.openCorpus('b')
  assert.equal(store.state.screen, 'text')
  assert.equal(store.state.path, 'edge')
})

test('完成畫面的預設試聽：伺服器目前只念固定句，其餘句子停用並說明', async () => {
  const { api, calls } = fakeApi({ post: { audio: 'data:audio/wav;base64,AAAA' } })
  const store = createVoiceTrainingStore({ api })
  store.state.job = job('done', { voice_id: 'trained-1' })
  assert.equal(store.previewAvailable('zh'), true)
  assert.equal(store.previewAvailable('en'), false)
  await store.previewVoice('en')
  assert.equal(calls.length, 0)
  await store.previewVoice('zh')
  assert.deepEqual(calls[0].slice(1), ['/api/speech/preview', { tts: { type: 'matcha', ref_file: 'trained-1', tts_server: '', model: '' } }])
  assert.equal(store.state.preview.audio, 'data:audio/wav;base64,AAAA')
})
