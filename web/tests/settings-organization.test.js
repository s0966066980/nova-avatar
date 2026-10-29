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
    applyVadSettings: async () => { saves.push('vad'); return {} }
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
