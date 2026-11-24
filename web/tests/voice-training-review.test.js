// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  cleanSentenceList, confirmableIds, countRows, edgeTextRows, expansionSegments, filterRows, paginate, removeSentence,
  replaceSentence, reviewGate, rowState, textSegments
} from '../src/voiceTraining/reviewTable.js'

const line = (id, extra = {}) => ({
  id, original_name: `clip_${id}.wav`, text: '你好', normalized_text: '你好', unresolved: [], review: 'pending', audio_url: `/a/${id}`, ...extra
})

test('每句的狀態只有四種：待確認、已確認、已排除、無法處理', () => {
  assert.equal(rowState(line('1')), 'pending')
  assert.equal(rowState(line('2', { review: 'confirmed' })), 'confirmed')
  assert.equal(rowState(line('3', { review: 'excluded' })), 'excluded')
  assert.equal(rowState(line('4', { unresolved: [{ text: '3.5.1', start: 0, end: 5, reason: 'x' }] })), 'unresolved')
  assert.equal(rowState(line('5', { review: 'excluded', unresolved: [{ text: 'A1', start: 0, end: 2 }] })), 'excluded', '排除優先，不再算無法處理')
  assert.equal(rowState(line('6', { review: 'confirmed', unresolved: [{ text: 'A1', start: 0, end: 2 }] })), 'unresolved', '已確認但有未解項仍須處理')
})

test('計數與批次確認只含有文字且沒有未解項的待確認句', () => {
  const lines = [
    line('1'), line('2'), line('3', { review: 'confirmed' }), line('4', { review: 'excluded' }),
    line('5', { unresolved: [{ text: '1/2', start: 0, end: 3 }] }), line('6', { text: '' })
  ]
  assert.deepEqual(countRows(lines), { pending: 3, confirmed: 1, excluded: 1, unresolved: 1, total: 6 })
  assert.deepEqual(confirmableIds(lines), ['1', '2'])
})

test('篩選：全部、待確認、需要處理（未解項或缺文字）、已排除', () => {
  const lines = [line('1'), line('2', { review: 'confirmed' }), line('3', { review: 'excluded' }),
    line('4', { unresolved: [{ text: 'R2D2', start: 0, end: 4 }] }), line('5', { text: '' })]
  const ids = filter => filterRows(lines, filter).map(l => l.id)
  assert.deepEqual(ids('all'), ['1', '2', '3', '4', '5'])
  assert.deepEqual(ids('pending'), ['1', '5'])
  assert.deepEqual(ids('attention'), ['4', '5'])
  assert.deepEqual(ids('excluded'), ['3'])
})

test('分頁：頁碼會被夾在範圍內', () => {
  const items = Array.from({ length: 23 }, (_, i) => i)
  assert.deepEqual(paginate(items, 0, 10), { items: items.slice(0, 10), page: 0, pages: 3, total: 23 })
  assert.deepEqual(paginate(items, 9, 10).items, [20, 21, 22])
  assert.equal(paginate(items, 9, 10).page, 2)
  assert.deepEqual(paginate([], 3, 10), { items: [], page: 0, pages: 1, total: 0 })
})

test('「下一步」的原因：待確認、無法處理、沒有任何已確認，全部列出', () => {
  assert.deepEqual(reviewGate([line('1', { review: 'confirmed' })]), [])
  assert.deepEqual(reviewGate([line('1'), line('2', { review: 'confirmed' })]), [{ code: 'pending', count: 1 }])
  assert.deepEqual(reviewGate([line('1', { unresolved: [{ text: 'A1', start: 0, end: 2 }] })]),
    [{ code: 'unresolved', count: 1 }])
  assert.deepEqual(reviewGate([line('1', { review: 'excluded' })]), [{ code: 'none_confirmed', count: 0 }])
  assert.deepEqual(reviewGate([]), [{ code: 'none_confirmed', count: 0 }])
})

test('無法處理的片段依位置標出，位置無效時整句不標', () => {
  assert.deepEqual(textSegments('編號 A12 的人', [{ text: 'A12', start: 3, end: 6 }]),
    [{ text: '編號 ', bad: false }, { text: 'A12', bad: true }, { text: ' 的人', bad: false }])
  assert.deepEqual(textSegments('abc', []), [{ text: 'abc', bad: false }])
  assert.deepEqual(textSegments('abc', [{ text: 'x', start: 5, end: 9 }]), [{ text: 'abc', bad: false }])
  assert.deepEqual(textSegments('abc', [{ text: 'a', start: 0, end: 1 }, { text: 'c', start: 2, end: 3 }]),
    [{ text: 'a', bad: true }, { text: 'b', bad: false }, { text: 'c', bad: true }])
})

test('數字展開預覽：展開的字用 expanded 標出，其餘照原樣', () => {
  assert.deepEqual(expansionSegments('我有3個蘋果', '我有三個蘋果'),
    [{ text: '我有', expanded: false }, { text: '三', expanded: true }, { text: '個蘋果', expanded: false }])
  assert.deepEqual(expansionSegments('2026年', '二零二六年'),
    [{ text: '二零二六', expanded: true }, { text: '年', expanded: false }])
  assert.deepEqual(expansionSegments('你好', '你好'), [{ text: '你好', expanded: false }])
  assert.deepEqual(expansionSegments('', ''), [])
})

test('Edge 文字清單：清理空行與重複、替換與移除句子', () => {
  assert.deepEqual(cleanSentenceList('  你好 \n\n你好\n再見\r\n'), ['你好', '再見'])
  assert.deepEqual(replaceSentence(['a', 'b', 'c'], 1, ' B '), ['a', 'B', 'c'])
  assert.deepEqual(replaceSentence(['a', 'b'], 0, 'b'), ['b'], '改成與別句相同就合併')
  assert.deepEqual(replaceSentence(['a', 'b'], 0, ''), ['b'], '改成空白等於移除')
  assert.deepEqual(removeSentence(['a', 'b', 'c'], 1), ['a', 'c'])
})

test('Edge 合成前校對表：由預覽結果逐句標出可用或無法處理，全部可用才算完成', () => {
  const preview = {
    ok: false, total: 2, estimatedSeconds: 10,
    items: [
      { index: 1, text: '價格 3 元', spoken: '價格三元', unresolved: [] },
      { index: 2, text: '編號 A12', spoken: '編號 A12', unresolved: [{ text: 'A12', start: 3, end: 6, reason: 'mixed' }] }
    ]
  }
  const view = edgeTextRows(preview)
  assert.deepEqual(view.rows.map(r => [r.position, r.state]), [[0, 'confirmed'], [1, 'unresolved']])
  assert.equal(view.counts.unresolved, 1)
  assert.equal(view.canContinue, false)
  assert.equal(edgeTextRows({ ...preview, ok: true, items: [preview.items[0]] }).canContinue, true)
  assert.equal(edgeTextRows(null).canContinue, false)
  assert.equal(edgeTextRows({ ok: true, total: 0, items: [] }).canContinue, false, '沒有句子不能開始')
})
