// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test'
import assert from 'node:assert/strict'
import { h } from 'vue'
import { loadComponent, mount, all, button, textContent, settle } from './helpers/componentHarness.js'
import { useRuntimeSettings } from '../src/composables/useRuntimeSettings.js'

const saves = []
const Profiles = { default: { setup: () => () => h('div', '數位人設定檔') } }
const Panel = await loadComponent(new URL('../src/components/SettingsPanel.vue', import.meta.url), {
  './ConversationComposer.vue': { default: { setup: () => () => h('div', '舞台文字輸入預覽') } },
  './ConversationPanel.vue': { default: { props: ['sessionId'], emits: ['session-summary'], setup: (props, { emit }) => {
    emit('session-summary', { sessionId: props.sessionId, locale: 'en-US' })
    return () => h('div', `對話記憶設定 #${props.sessionId}`)
  } } },
  './AvatarProfiles.vue': Profiles,
  './IdleGreetingSettings.vue': { default: { setup: () => () => h('div', '閒置招呼獨立設定頁') } },
  '../composables/useI18n': { useI18n: () => ({ t: key => key, setLocale() {} }) },
  '../composables/useRuntimeSettings': { useRuntimeSettings: () => ({ ...useRuntimeSettings(),
    loadRuntimeSettings: async () => {}, loadOllamaModels: async () => {},
    loadBackgrounds: async () => {}, loadArchivedCharacters: async () => {},
    applyStageSettings: async () => { saves.push('stage') },
    applyVisitorSettings: async () => { saves.push('interaction') },
    applyVadSettings: async () => { saves.push('vad'); return {} },
    applySttSettings: async () => { saves.push('stt'); return {} }
  }) }
})

test('設定導覽直接提供閒置招呼與訪客互動，排版頁只含視覺設定', async t => {
  const oldWindow = globalThis.window, oldStorage = globalThis.localStorage, oldFetch = globalThis.fetch
  globalThis.window = { ResizeObserver: null }
  globalThis.localStorage = { getItem: () => null, setItem() {} }
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ code: 0, data: {} }) })
  const view = mount(Panel, { initialTab: 'stage' })
  t.after(() => { view.unmount(); globalThis.window = oldWindow; globalThis.localStorage = oldStorage; globalThis.fetch = oldFetch })
  await settle()
  assert.ok(button(view.root, '閒置招呼'), '側欄應有可直接找到的閒置招呼入口')
  assert.ok(button(view.root, '訪客互動'), '收音與清場應有獨立的互動設定入口')
  const layout = all(view.root, node => node.props.id === 'settings-panel-stage')[0]
  assert.doesNotMatch(textContent(layout), /閒置招呼|招呼間隔|訪客對話重置/)
  assert.match(textContent(layout), /字幕|背景|看板/)
  const interaction = all(view.root, node => node.props.id === 'catPanel-interaction')[0]
  assert.match(textContent(interaction), /訪客對話重置/)
  assert.match(textContent(interaction), /收音/)
  await button(view.root, '閒置招呼').props.onClick()
  await settle()
  assert.equal(button(view.root, '閒置招呼').props['aria-selected'], true)
  assert.match(textContent(all(view.root, node => node.props.id === 'catPanel-greeting')[0]), /閒置招呼獨立設定頁/)
  assert.equal(layout.style.display, 'none')
})


test('儲存排版頁只套用本頁，不提交訪客設定且不離開目前頁面', async t => {
  const previousWindow = globalThis.window, previousFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  globalThis.window = { ResizeObserver: null }
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null, setItem() {} } })
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ code: 0, data: {} }) })
  const settings = useRuntimeSettings()
  const old = { captionX: settings.selectedCaptionX.value, reset: settings.selectedVisitorResetSeconds.value, threshold: settings.vadDraft.threshold }
  settings.selectedCaptionX.value = 55
  settings.selectedVisitorResetSeconds.value = 120
  settings.vadDraft.threshold = .8
  let closed = 0
  const view = mount(Panel, { initialTab: 'stage', onCloseSettings: () => { closed++ } })
  t.after(() => {
    view.unmount(); globalThis.window = previousWindow; globalThis.fetch = previousFetch
    Object.defineProperty(globalThis, 'localStorage', storageDescriptor)
    settings.selectedCaptionX.value = old.captionX; settings.selectedVisitorResetSeconds.value = old.reset; settings.vadDraft.threshold = old.threshold
  })
  await settle()
  saves.length = 0
  await button(view.root, '儲存並套用本頁設定').props.onClick()
  await settle()
  assert.deepEqual(saves, ['stage'])
  assert.equal(closed, 0)
  assert.equal(button(view.root, '舞台與看板排版').props['aria-selected'], true)
  assert.equal(settings.selectedVisitorResetSeconds.value, 120)
})

test('對話設定分類沿用目前場次、轉送摘要並可返回控制台', async t => {
  const previousWindow = globalThis.window, previousFetch = globalThis.fetch, previousStorage = globalThis.localStorage
  globalThis.window = { ResizeObserver: null }
  globalThis.localStorage = { getItem: () => null, setItem() {} }
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ code: 0, data: {} }) })
  const summaries = []
  let returned = 0
  const view = mount(Panel, { initialTab: 'conversation', sessionId: 7,
    onConversationSummary: value => summaries.push(value), onCloseSettings: () => returned++ })
  t.after(() => { view.unmount(); globalThis.window = previousWindow; globalThis.fetch = previousFetch; globalThis.localStorage = previousStorage })
  await settle()
  assert.equal(button(view.root, '對話記憶與語系').props['aria-selected'], true)
  assert.match(textContent(all(view.root, node => node.props.id === 'catPanel-conversation')[0]), /對話記憶設定 #7/)
  assert.deepEqual(summaries, [{ sessionId: 7, locale: 'en-US' }])
  assert.equal(all(view.root, node => node.props.class === 'settings-fixed-footer')[0].style.display, 'none',
    '記憶與語系沿用自己的套用操作，不顯示其他分類的儲存鈕')
  button(view.root, '返回控制台').props.onClick()
  assert.equal(returned, 1)
})

test('最小靜音判定時間滑桿編輯 min_silence_ms，可選 192 ms（6 個 32 ms 幀）並顯示目前值', async t => {
  const previousWindow = globalThis.window, previousFetch = globalThis.fetch, previousStorage = globalThis.localStorage
  globalThis.window = { ResizeObserver: null }
  globalThis.localStorage = { getItem: () => null, setItem() {} }
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ code: 0, data: {} }) })
  const settings = useRuntimeSettings()
  const old = settings.vadDraft.min_silence_ms
  settings.vadDraft.min_silence_ms = 192
  const view = mount(Panel, { initialTab: 'interaction' })
  t.after(() => {
    view.unmount(); globalThis.window = previousWindow; globalThis.fetch = previousFetch; globalThis.localStorage = previousStorage
    settings.vadDraft.min_silence_ms = old
  })
  await settle()
  const row = all(view.root, n => n.props.class === 'setting-form-row' && textContent(n).includes('最小靜音判定時間'))[0]
  const slider = all(row, n => n.type === 'input' && n.props.type === 'range')[0]
  const [min, max, step] = ['min', 'max', 'step'].map(key => Number(slider.props[key]))
  assert.ok(min >= 100 && max <= 3000, '刻度在伺服器接受的 100–3000 ms 內')
  assert.ok(min <= 192 && 192 <= max)
  assert.equal(step % 32, 0, '分段器以 32 ms 幀計算')
  assert.equal((192 - min) % step, 0, '192 ms 必須是可選刻度')
  assert.equal((max - min) % step, 0, '最大值也落在刻度上')
  assert.equal(slider.value, 192, '滑桿顯示目前的 min_silence_ms')
  assert.match(textContent(row), /192\s*ms/)
  slider.props['onUpdate:modelValue'](224)
  await settle()
  assert.equal(settings.vadDraft.min_silence_ms, 224)
  assert.equal('min_silence_duration_ms' in settings.vadDraft, false, '不可寫入伺服器不認得的欄位')
  assert.match(textContent(row), /224\s*ms/)
})

test('語音辨識併入訪客互動頁，依後端引擎資料呈現，且不再有全域語音合成設定', async t => {
  const previousWindow = globalThis.window, previousFetch = globalThis.fetch, previousStorage = globalThis.localStorage
  globalThis.window = { ResizeObserver: null }
  globalThis.localStorage = { getItem: () => null, setItem() {} }
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ code: 0, data: {} }) })
  const settings = useRuntimeSettings()
  const old = { stt: { ...settings.speech.stt }, draft: { ...settings.sttDraft } }
  Object.assign(settings.speech.stt, { type: 'whisper', model_size: 'small', engines: [
    { id: 'whisper', label: 'faster-whisper', available: true, models: ['small', 'turbo'], output_scripts: [], local_model_ready: false },
    { id: 'nano', label: '新的中英辨識', available: true, models: ['nano-v1'],
      output_scripts: [{ id: 'traditional-tw', label: '臺灣正體輸出' }], local_model_ready: true }
  ] })
  Object.assign(settings.sttDraft, { type: 'whisper', model_size: 'small' })
  const view = mount(Panel, { initialTab: 'interaction' })
  t.after(() => {
    view.unmount(); globalThis.window = previousWindow; globalThis.fetch = previousFetch; globalThis.localStorage = previousStorage
    Object.assign(settings.speech.stt, old.stt); Object.assign(settings.sttDraft, old.draft)
  })
  await settle()
  assert.ok(!button(view.root, '語音辨識與合成'), '全域語音頁已移除')
  assert.equal(all(view.root, node => node.props.id === 'catPanel-voice').length, 0)
  assert.equal(button(view.root, '訪客互動與語音辨識').props['aria-selected'], true)
  const panel = () => all(view.root, node => node.props.id === 'catPanel-interaction')[0]
  assert.match(textContent(panel()), /語音辨識/)
  assert.doesNotMatch(textContent(panel()), /TTS|語音合成|參考音訊/)
  const engines = all(panel(), node => node.props.id === 'stt-engine')[0]
  assert.deepEqual(engines.options.map(textContent).map(s => s.trim()), ['faster-whisper', '新的中英辨識'])
  const models = () => all(panel(), node => node.props.id === 'stt-model-size')[0].options.map(textContent)
  assert.deepEqual(models(), ['small', 'turbo'])
  assert.equal(all(panel(), node => node.props.id === 'stt-output-script').length, 0, '引擎沒有輸出字元集選項時不顯示')

  settings.sttDraft.type = 'nano'
  await settle()
  assert.deepEqual(models(), ['nano-v1'])
  const scripts = all(panel(), node => node.props.id === 'stt-output-script')[0]
  assert.deepEqual(scripts.options.map(textContent), ['臺灣正體輸出'])

  saves.length = 0
  await button(view.root, '儲存並套用本頁設定').props.onClick()
  await settle()
  assert.ok(saves.includes('stt'), '本頁儲存會套用語音辨識草稿')
  assert.ok(!saves.includes('stage'))
})
