// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { TrainingApiError, createTrainingApi } from '../src/voiceTraining/api.js'
import { previewEdgeText } from '../src/voiceTraining/textPreviewClient.js'

// A fake fetch that records requests and answers from a route table.
function fakeFetch(routes) {
  const calls = []
  const fetchImpl = async (url, init = {}) => {
    const key = `${init.method || 'GET'} ${url}`
    calls.push({ url, init, key })
    const answer = routes[key]
    if (!answer) throw new Error(`unexpected request ${key}`)
    const { status = 200, body } = typeof answer === 'function' ? answer(init) : answer
    return { ok: status >= 200 && status < 300, status, json: async () => body }
  }
  return { fetchImpl, calls }
}
const ok = data => ({ body: { code: 0, msg: 'ok', data } })

test('GET 回傳 data，音檔網址對 slug 做編碼', async () => {
  const { fetchImpl, calls } = fakeFetch({ 'GET /api/tts/corpora/my-voice': ok({ slug: 'my-voice', lines: [] }) })
  const api = createTrainingApi(fetchImpl)
  assert.deepEqual(await api.getCorpus('my-voice'), { slug: 'my-voice', lines: [] })
  assert.equal(calls.length, 1)
  assert.equal(api.lineAudioUrl('a b', '000001'), '/api/tts/corpora/a%20b/lines/000001/audio')
})

test('建立語料與記錄 Edge 條文確認都走伺服器，條文原文隨請求送出', async () => {
  const { fetchImpl, calls } = fakeFetch({
    'POST /api/tts/corpora': ok({ slug: 'edge-1' }),
    'POST /api/tts/corpora/edge-1/acknowledgement': ok({ acknowledged_at: '2026-11-24T00:00:00+00:00' })
  })
  const api = createTrainingApi(fetchImpl)
  await api.createCorpus({ slug: 'edge-1', source: 'edge-test-teacher' })
  const ack = await api.recordAcknowledgement('edge-1', 'clause text')
  assert.equal(ack.acknowledged_at, '2026-11-24T00:00:00+00:00')
  assert.deepEqual(JSON.parse(calls[0].init.body), { slug: 'edge-1', source: 'edge-test-teacher' })
  assert.deepEqual(JSON.parse(calls[1].init.body), { shown_text: 'clause text' })
  assert.equal(calls[1].init.headers['Content-Type'], 'application/json')
})

test('錯誤回應變成 TrainingApiError，保留狀態碼、problems 與訓練前檢查', async () => {
  const { fetchImpl } = fakeFetch({
    'POST /api/tts/corpora/c/transcripts': { status: 422, body: { code: -1, msg: '逐字稿有問題', problems: ['第 2 行缺少分隔符'] } },
    'POST /api/tts/training/start': { status: 409, body: { code: -1, msg: '不能開始', preflight: { can_start: false, checks: [{ id: 'stage_connections' }] } } }
  })
  const api = createTrainingApi(fetchImpl)
  await assert.rejects(api.importTranscripts('c', []), err => {
    assert.ok(err instanceof TrainingApiError)
    assert.equal(err.status, 422)
    assert.equal(err.message, '逐字稿有問題')
    assert.deepEqual(err.problems, ['第 2 行缺少分隔符'])
    return true
  })
  await assert.rejects(api.startTraining({ corpus: 'c', name: 'n' }), err => {
    assert.equal(err.status, 409)
    assert.equal(err.preflight.checks[0].id, 'stage_connections')
    return true
  })
})

test('回應不是 JSON 時仍給出可讀的錯誤', async () => {
  const api = createTrainingApi(async () => ({ ok: false, status: 502, json: async () => { throw new Error('bad json') } }))
  await assert.rejects(api.listCorpora(), err => err instanceof TrainingApiError && /502/.test(err.message))
})

test('上傳錄音用 multipart：audio 與選填的 text', async () => {
  const { fetchImpl, calls } = fakeFetch({ 'POST /api/tts/corpora/c/lines': ok({ line: { id: '000001' }, duration: 3.2 }) })
  const api = createTrainingApi(fetchImpl)
  const file = new Blob(['x'], { type: 'audio/wav' })
  const result = await api.uploadLine('c', file, 'clip_001.wav')
  assert.equal(result.duration, 3.2)
  const form = calls[0].init.body
  assert.ok(form instanceof FormData)
  assert.equal(form.get('audio').name, 'clip_001.wav')
  assert.equal(form.has('text'), false)
})

test('逐字稿匯入把每個檔案放進同名欄位 files', async () => {
  const { fetchImpl, calls } = fakeFetch({ 'POST /api/tts/corpora/c/transcripts': ok({ applied: 2, without_transcript: [] }) })
  const api = createTrainingApi(fetchImpl)
  await api.importTranscripts('c', [new File(['a'], 'a.txt'), new File(['b'], 'b.txt')])
  assert.equal(calls[0].init.body.getAll('files').length, 2)
})

test('訓練日誌用絕對行號 offset；訓練前檢查帶 corpus 與 name', async () => {
  const { fetchImpl, calls } = fakeFetch({
    'GET /api/tts/training/log?offset=12': ok({ job_id: 'j', start: 0, lines: ['x'], next: 13, total: 13 }),
    'GET /api/tts/training?corpus=my+voice&name=%E8%81%B2%E7%B7%9A': ok({ job: null, preflight: { can_start: false, checks: [] }, settings: {} })
  })
  const api = createTrainingApi(fetchImpl)
  assert.equal((await api.getTrainingLog(12)).next, 13)
  await api.getTraining({ corpus: 'my voice', name: '聲線' })
  assert.equal(calls.length, 2)
})

test('沒有任何下載或匯出的呼叫', () => {
  const api = createTrainingApi(async () => { throw new Error('no network') })
  assert.deepEqual(Object.keys(api).filter(name => /download|export/i.test(name)), [])
})

test('Edge 文字清單在合成前預覽：句子以換行相連送出，結果正規化成固定形狀', async () => {
  const { fetchImpl, calls } = fakeFetch({
    'POST /api/tts/training/text-preview': ok({
      ok: false, total: 2, estimated_seconds: 7.5,
      sentences: [
        { index: 1, text: '價格 3 元', spoken: '價格三元', unresolved: [] },
        { index: 2, text: '編號 A12', spoken: '編號 A12', unresolved: [{ text: 'A12', start: 3, end: 6, reason: 'mixed' }] }
      ]
    })
  })
  const api = createTrainingApi(fetchImpl)
  const preview = await previewEdgeText(api, ['價格 3 元', '編號 A12'])
  assert.deepEqual(JSON.parse(calls[0].init.body), { sentences: '價格 3 元\n編號 A12' })
  assert.equal(preview.ok, false)
  assert.equal(preview.total, 2)
  assert.equal(preview.estimatedSeconds, 7.5)
  assert.equal(preview.items[1].unresolved[0].text, 'A12')
  assert.equal(preview.items[0].spoken, '價格三元')
})

test('預覽回應缺欄位時不丟例外：ok 由未解決項推得', async () => {
  const api = { post: async () => ({ sentences: [{ index: 1, text: 'a', unresolved: [{ text: '1/2', start: 0, end: 3 }] }] }) }
  const preview = await previewEdgeText(api, ['a'])
  assert.equal(preview.ok, false)
  assert.equal(preview.total, 1)
  assert.equal(preview.items[0].spoken, 'a')
})

test('start 因數字無法念出而 409 時，unresolved 保留 index（第 N 句）與片段', async () => {
  const { fetchImpl } = fakeFetch({
    'POST /api/tts/training/start': { status: 409, body: { code: -1, msg: '有數字無法確定怎麼念：第 2 句「$50」', unresolved: [{ index: 2, text: '$50', reason: 'currency' }] } }
  })
  const api = createTrainingApi(fetchImpl)
  await assert.rejects(api.startTraining({ corpus: 'c', name: 'n', sentences: 'a\nb' }), err => {
    assert.equal(err.status, 409)
    assert.equal(err.preflight, null)
    assert.deepEqual(err.unresolved, [{ index: 2, text: '$50', reason: 'currency' }])
    return true
  })
})
