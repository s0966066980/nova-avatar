// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

const video = {
  max_height: 1280,
  height_options: [450, 540, 720, 960, 1280, 1920, 0],
  source_width: 1080,
  source_height: 1920,
  output_width: 720,
  output_height: 1280
}

async function withSettings(run, height = 1280) {
  const originalFetch = globalThis.fetch
  const requests = []
  let savedHeight = height
  let fail = false
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, ...options })
    let data
    if (url === '/api/settings') data = { llm: {}, avatar: {}, video: { ...video, max_height: savedHeight } }
    else if (url === '/api/llm/rules') data = {}
    else if (url === '/api/avatar/output') {
      if (fail) return { ok: false, status: 500, json: async () => ({ code: -1, msg: 'Disk full' }) }
      savedHeight = JSON.parse(options.body).max_height
      data = { ...video, max_height: savedHeight, requires_reconnect: true }
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

test('resolution drafts show actual portrait dimensions and save a numeric height', async () => {
  await withSettings(async ({ settings, requests }) => {
    assert.equal(settings.videoDirty.value, false)
    assert.equal(settings.outputDimensions.value, '720 × 1280')
    settings.selectedOutputHeight.value = 540
    assert.equal(settings.outputDimensions.value, '304 × 540')
    assert.equal(settings.videoDirty.value, true)
    const result = await settings.applyVideoSettings()
    const saved = requests.find((request) => request.url === '/api/avatar/output')
    assert.equal(saved.method, 'POST')
    assert.deepEqual(JSON.parse(saved.body), { max_height: 540 })
    assert.equal(result.requires_reconnect, true)
    assert.equal(settings.videoDirty.value, false)
    await settings.loadRuntimeSettings()
    assert.equal(settings.selectedOutputHeight.value, 540)
  })
})

test('native output and a custom saved height remain selectable without upscaling', async () => {
  await withSettings(async ({ settings }) => {
    assert.ok(settings.outputHeightOptions.value.includes(800))
    assert.equal(settings.selectedOutputHeight.value, 800)
    settings.selectedOutputHeight.value = 0
    assert.equal(settings.outputDimensions.value, '1080 × 1920')
    assert.ok(settings.outputHeightOptions.value.includes(800))
    settings.selectedOutputHeight.value = 2160
    assert.equal(settings.outputDimensions.value, '1080 × 1920')
  }, 800)
})

test('save failure keeps the resolution draft available for retry and exposes the error', async () => {
  await withSettings(async ({ settings, failNextSave }) => {
    settings.selectedOutputHeight.value = 720
    failNextSave()
    await assert.rejects(settings.applyVideoSettings(), /Disk full/)
    assert.equal(settings.runtime.video.max_height, 1280)
    assert.equal(settings.selectedOutputHeight.value, 720)
    assert.equal(settings.videoDirty.value, true)
    assert.equal(settings.videoError.value, 'Disk full')
    assert.equal(settings.applyingVideo.value, false)
  })
})
