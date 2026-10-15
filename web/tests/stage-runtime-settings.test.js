// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

async function withSettings(run) {
  const originalFetch = globalThis.fetch
  const requests = []
  let stage = { idle_reset_seconds: 10 }
  let fail = false
  globalThis.fetch = async (url, options = {}) => {
    let data
    if (url === '/api/settings') data = { llm: {}, avatar: {}, stage }
    else if (url === '/api/llm/rules') data = {}
    else if (url === '/api/stage') {
      const body = JSON.parse(options.body)
      requests.push(body)
      if (fail) return { ok: false, status: 500, json: async () => ({ code: -1, msg: '儲存失敗' }) }
      data = stage = body
    } else throw new Error(`Unexpected request ${url}`)
    return { ok: true, status: 200, json: async () => ({ code: 0, data }) }
  }
  try {
    const settings = useRuntimeSettings()
    await settings.loadRuntimeSettings()
    await run({ settings, requests, failNextSave: () => { fail = true } })
  } finally {
    globalThis.fetch = originalFetch
  }
}

test('訪客重置秒數可修改、套用並從伺服器重新載入', async () => {
  await withSettings(async ({ settings, requests }) => {
    assert.equal(settings.selectedStageIdleResetSeconds.value, 10)
    assert.equal(settings.stageDirty.value, false)
    settings.selectedStageIdleResetSeconds.value = 45
    assert.equal(settings.stageDirty.value, true)
    await settings.applyStageSettings()
    assert.equal(requests[0].idle_reset_seconds, 45)
    assert.equal(settings.stageDirty.value, false)
    await settings.loadRuntimeSettings()
    assert.equal(settings.selectedStageIdleResetSeconds.value, 45)
  })
})

test('訪客重置秒數超出範圍或非整數時禁止套用舞台設定', async () => {
  await withSettings(async ({ settings }) => {
    for (const value of [2, 301, 10.5, '', 'invalid']) {
      settings.selectedStageIdleResetSeconds.value = value
      assert.equal(settings.stageIdleResetError.value, true)
      assert.equal(settings.stageDirty.value, false)
    }
    for (const value of [3, 300]) {
      settings.selectedStageIdleResetSeconds.value = value
      assert.equal(settings.stageIdleResetError.value, false)
      assert.equal(settings.stageDirty.value, true)
    }
  })
})

test('訪客重置設定儲存失敗時保留草稿並顯示錯誤', async () => {
  await withSettings(async ({ settings, failNextSave }) => {
    settings.selectedStageIdleResetSeconds.value = 60
    failNextSave()
    await assert.rejects(settings.applyStageSettings(), /儲存失敗/)
    assert.equal(settings.runtime.stage.idle_reset_seconds, 10)
    assert.equal(settings.selectedStageIdleResetSeconds.value, 60)
    assert.equal(settings.stageDirty.value, true)
    assert.equal(settings.stageError.value, '儲存失敗')
    assert.equal(settings.applyingStage.value, false)
  })
})
