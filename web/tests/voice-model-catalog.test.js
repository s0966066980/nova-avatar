// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import test from 'node:test'
import { loadComponent, mount, all, textContent, settle } from './helpers/componentHarness.js'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'
import zhTW from '../src/locales/zh-TW.js'
import zhCN from '../src/locales/zh-CN.js'
import enUS from '../src/locales/en-US.js'

const hsiaochen = { id: 'zh-tw-hsiaochen-edge', name: '曉臻（Edge 蒸餾）', usage: 'Development only', languages: ['zh-TW', 'en-US'], source: 'distilled' }
const researchModel = { id: 'my-voice', name: '自訓聲線', usage: 'Research / Non-commercial', languages: ['zh-TW', 'en-US'], source: 'fine-tuned' }

test('三份 locales 都有聲線模型說明，實測數字由同一份資料填入', () => {
  const keys = Object.keys(zhTW.settings.voiceModels).sort()
  for (const locale of [zhCN, enUS]) assert.deepEqual(Object.keys(locale.settings.voiceModels).sort(), keys)
  for (const locale of [zhTW, zhCN, enUS]) {
    for (const key of keys) assert.ok(locale.settings.voiceModels[key].trim(), key)
    assert.match(locale.settings.voiceModels.measured, /\{cer\}[\s\S]*\{wer\}/)
    assert.match(locale.settings.voiceModels.cpu, /CPU/)
  }
})

async function mountCatalog(t, models) {
  const { speech } = useRuntimeSettings()
  const previous = speech.tts.voice_models
  speech.tts.voice_models = models
  const Catalog = await loadComponent(new URL('../src/components/VoiceModelCatalog.vue', import.meta.url))
  const view = mount(Catalog, {})
  t.after(() => { view.unmount(); speech.tts.voice_models = previous })
  await settle()
  return view
}

test('設定頁列出已安裝的聲線模型，名稱後面是使用限制標示，hsiaochen-edge 附實測品質', async t => {
  const view = await mountCatalog(t, [hsiaochen, researchModel])
  const items = all(view.root, n => n.type === 'li').map(textContent)
  assert.equal(items.length, 2)
  assert.match(items[0], /曉臻（Edge 蒸餾） · Development only/)
  assert.match(items[0], /CER 13\.2%/)
  assert.match(items[0], /WER 5\.6%/)
  assert.match(items[1], /自訓聲線 · Research \/ Non-commercial/)
  assert.doesNotMatch(items[1], /CER/)
  assert.match(textContent(view.root), /CPU/)
  assert.match(textContent(view.root), /matcha\.num_threads/)
})

test('沒有已安裝的聲線模型時說明怎麼安裝', async t => {
  const view = await mountCatalog(t, [])
  assert.equal(all(view.root, n => n.type === 'li').length, 0)
  assert.match(textContent(view.root), /models\/tts/)
})
