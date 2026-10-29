// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  fetchJsonWithTimeout,
  STAGE_CONNECT_TIMEOUT_MS,
  STAGE_OFFER_TIMEOUT_MS,
  STAGE_POLL_TIMEOUT_MS,
  StageTimeoutError
} from '../src/stageConnection.js'

function manualTimers() {
  const timers = []
  return {
    timers,
    setTimer: (fn, ms) => { timers.push({ fn, ms, cleared: false }); return timers.length },
    clearTimer: (id) => { if (timers[id - 1]) timers[id - 1].cleared = true },
    fire() { for (const timer of timers.filter(item => !item.cleared)) { timer.cleared = true; timer.fn() } },
  }
}

const never = () => new Promise(() => {})

test('逾時常數：輪詢短於 5 秒輪詢週期，整體連線看門狗長於 offer 請求', () => {
  assert.ok(STAGE_POLL_TIMEOUT_MS < 5000)
  assert.ok(STAGE_OFFER_TIMEOUT_MS > STAGE_POLL_TIMEOUT_MS)
  assert.ok(STAGE_CONNECT_TIMEOUT_MS > STAGE_OFFER_TIMEOUT_MS)
})

test('正常回應回傳狀態與 JSON，並帶上 AbortSignal、清除計時器', async () => {
  const clock = manualTimers()
  let seen
  const result = await fetchJsonWithTimeout('/api/vad', { cache: 'no-store' }, 1000, {
    ...clock,
    fetchImpl: async (url, options) => { seen = options; return { ok: true, status: 200, json: async () => ({ data: 1 }) } },
  })
  assert.deepEqual(result, { ok: true, status: 200, data: { data: 1 } })
  assert.equal(seen.cache, 'no-store')
  assert.ok(seen.signal instanceof AbortSignal)
  assert.equal(clock.timers[0].ms, 1000)
  assert.equal(clock.timers[0].cleared, true)
})

test('後端接受連線後不回應時，逾時一到就中止請求並拋出逾時錯誤', async () => {
  const clock = manualTimers()
  let signal
  const pending = fetchJsonWithTimeout('/offer', {}, 15000, {
    ...clock,
    fetchImpl: (url, options) => { signal = options.signal; return never() },
  })
  clock.fire()
  await assert.rejects(pending, error => error instanceof StageTimeoutError && error.name === 'TimeoutError')
  assert.equal(signal.aborted, true)
})

test('回應標頭到了但內容卡住時同樣會逾時', async () => {
  const clock = manualTimers()
  const pending = fetchJsonWithTimeout('/api/stage', {}, 4000, {
    ...clock,
    fetchImpl: async () => ({ ok: true, status: 200, json: never }),
  })
  await new Promise(resolve => setImmediate(resolve))
  clock.fire()
  await assert.rejects(pending, StageTimeoutError)
})

test('非 JSON 回應不視為錯誤，data 為 null', async () => {
  const clock = manualTimers()
  const result = await fetchJsonWithTimeout('/offer', {}, 1000, {
    ...clock,
    fetchImpl: async () => ({ ok: false, status: 502, json: async () => { throw new SyntaxError('bad') } }),
  })
  assert.deepEqual(result, { ok: false, status: 502, data: null })
})

test('網路錯誤照原樣拋出並清除計時器', async () => {
  const clock = manualTimers()
  await assert.rejects(fetchJsonWithTimeout('/offer', {}, 1000, {
    ...clock,
    fetchImpl: async () => { throw new TypeError('Failed to fetch') },
  }), TypeError)
  assert.equal(clock.timers[0].cleared, true)
})
