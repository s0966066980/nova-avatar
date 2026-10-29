// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'
import * as vue from 'vue'
import { all, button, loadComponent, mount, settle, textContent } from './helpers/componentHarness.js'

const lifecycle = { ...vue, onMounted() {},
  TransitionGroup: { inheritAttrs: false, setup: (_props, { slots }) => () => slots.default?.() } }
const Composer = await loadComponent(new URL('../src/components/ConversationComposer.vue', import.meta.url), { vue: lifecycle }, { inlineTemplate: false })
const VoiceTestPanel = await loadComponent(new URL('../src/components/VoiceTestPanel.vue', import.meta.url), { vue: lifecycle }, { inlineTemplate: false })
const empty = { default: { render: () => null } }
const Settings = { props: ['sessionId'], emits: ['close-settings', 'conversation-summary'], setup: (props, { emit, expose }) => {
  const selected = vue.ref('roles')
  expose({ selectSettingsTab: value => { selected.value = value } })
  return () => vue.h('section', [vue.h('span', selected.value),
    vue.h('button', { onClick: () => emit('close-settings') }, '返回控制台'),
    vue.h('button', { onClick: () => emit('conversation-summary', { sessionId: props.sessionId, locale: 'en-US' }) }, '更新語系摘要')])
} }

async function consoleView(t, { connected = true, rolePhase = 'disabled', humanResponse, voiceResponse } = {}) {
  let transport
  const calls = []
  const previousFetch = globalThis.fetch
  const previousWindow = globalThis.window
  globalThis.window = { visualViewport: null, setTimeout, clearTimeout, setInterval, clearInterval }
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body ? JSON.parse(options.body) : undefined })
    if (url === '/human' && humanResponse) return typeof humanResponse === 'function' ? humanResponse() : humanResponse
    if (url.startsWith('/api/voice-tests') && voiceResponse) return {
      ok: true, headers: { get: () => 'application/json' }, json: async () => voiceResponse(url)
    }
    return { ok: true, json: async () => ({ code: 0, data: url === '/human'
      ? { turn_id: 'shortcut-turn' }
      : { files: [], selection: [], bytes: 0, vision_ready: false } }) }
  }
  const App = await loadComponent(new URL('../src/App.vue', import.meta.url), {
    vue: lifecycle,
    './components/ConversationComposer.vue': { default: Composer },
    './components/ConversationPanel.vue': { default: { render: () => vue.h('section', '對話記憶與語系') } },
    './components/DebugPanel.vue': empty,
    './components/SettingsPanel.vue': { default: Settings },
    './components/VoiceTestPanel.vue': { default: VoiceTestPanel },
    './composables/useI18n': { useI18n: () => ({ t: key => key, setLocale() {}, loadLocale() {} }) },
    './composables/useRoles.js': { useRoles: () => ({ roleRuntime: vue.reactive({ enabled: false, phase: rolePhase }),
      roleLibrary: vue.ref({ profiles: [] }), roleRequest: async () => {}, roleEvent() {} }) },
    './composables/useRuntimeSettings': { useRuntimeSettings: () => ({ vad: { enabled: true }, vadDraft: {},
      runtime: { characters: [], avatar: {}, stage: {} }, isStageConfiguring: vue.ref(false), selectedBoardPreview: vue.ref(false) }) },
    './composables/useWebRTC': { useWebRTC: callbacks => {
      transport = callbacks
      return { stopPlay() {}, getCaptureRequested: () => false, setCaptureEnabled() {} }
    } }
  }, { inlineTemplate: false })
  const view = mount(App, {})
  t.after(() => {
    view.unmount(); globalThis.fetch = previousFetch
    if (previousWindow === undefined) delete globalThis.window
    else globalThis.window = previousWindow
  })
  if (connected) { transport.onSessionId(7); transport.onConnectionState('connected') }
  await settle()
  return { ...view, calls, transport }
}

for (const readAloud of [false, true]) {
  test(`點擊快捷指令立即送出指定問題${readAloud ? '，並切回對話模式' : ''}`, async t => {
    const view = await consoleView(t)
    if (readAloud) { button(view.root, '朗讀模式').props.onClick(); await settle() }
    button(view.root, '核心技術優勢').props.onClick()
    await settle()
    const requests = view.calls.filter(call => call.url === '/human')
    assert.equal(requests.length, 1)
    assert.equal(requests[0].body.text, '請整理 Nova Avatar 三大核心技術優勢並輸出看板')
    assert.equal(requests[0].body.sessionid, 7)
    assert.ok(all(view.root, node => node.props.innerHTML?.includes('請整理 Nova Avatar 三大核心技術優勢並輸出看板')).length)
    assert.equal(all(view.root, node => node.props.class === 'std-textarea').length, 0)
  })
}

function visible(node) {
  return Boolean(node) && node.style.display !== 'none' && (!node.parent || visible(node.parent))
}

test('記憶與語系不占控制台工作區，並提供對話設定入口', async t => {
  const view = await consoleView(t)
  const workspace = all(view.root, node => node.props.class === 'studio-chat-panel')[0]
  assert.doesNotMatch(textContent(workspace), /對話記憶與語系/)
  assert.ok(button(workspace, '對話設定'))
})

test('語音驗證獨占工作區，不與聊天列表及輸入塢堆疊', async t => {
  const view = await consoleView(t)
  button(view.root, '語音驗證').props.onClick()
  await settle()
  assert.equal(visible(all(view.root, node => node.props.id === 'chatFlowBox')[0]), false)
  assert.equal(visible(all(view.root, node => node.props.class === 'studio-input-dock')[0]), false)
  assert.equal(visible(all(view.root, node => node.props.id === 'voiceTestPrompt')[0]), true)
})

test('語音驗證的草稿在切到對話或朗讀後仍保留', async t => {
  const view = await consoleView(t)
  button(view.root, '語音驗證').props.onClick()
  await settle()
  const prompt = all(view.root, node => node.props.id === 'voiceTestPrompt')[0]
  prompt.props['onUpdate:modelValue']('這段語音驗證草稿需要保留')
  await settle()
  button(view.root, '朗讀模式').props.onClick()
  await settle()
  button(view.root, '語音驗證').props.onClick()
  await settle()
  assert.equal(all(view.root, node => node.props.id === 'voiceTestPrompt')[0].value, '這段語音驗證草稿需要保留')
})

test('切換模式後仍接收進行中語音驗證的完成結果', async t => {
  const record = { id: 'validation-record', turn_id: 'validation-turn', status: 'running',
    prompt: '請回答語音測試正常', label: '保留進行中驗證', metrics: {} }
  const view = await consoleView(t, { voiceResponse: url => url.endsWith('/run')
    ? { code: 0, turn_id: record.turn_id, record: { ...record } }
    : { code: 0, results: [{ ...record }] } })
  button(view.root, '語音驗證').props.onClick()
  await settle()
  await all(view.root, node => node.type === 'form' && node.props.class === 'test-form')[0].props.onSubmit({ preventDefault() {} })
  await settle()
  assert.ok(button(view.root, '測試執行中'))
  button(view.root, '對話模式').props.onClick()
  await settle()
  record.status = 'passed'
  record.passed = true
  view.transport.onVoiceEvent({ type: 'turn_metrics', turn_id: record.turn_id })
  await settle()
  button(view.root, '語音驗證').props.onClick()
  await settle()
  assert.match(textContent(view.root), /保留進行中驗證/)
  assert.equal(button(view.root, '測試執行中'), undefined)
  assert.match(textContent(view.root), /語音測試已通過並保存紀錄/)
  assert.equal(view.calls.filter(call => call.url === '/api/voice-tests/run').length, 1)
})

test('對話與朗讀草稿在模式切換後各自保留', async t => {
  const view = await consoleView(t)
  const chat = all(view.root, node => node.type === 'textarea')[0]
  chat.props['onUpdate:modelValue']('尚未送出的對話')
  button(view.root, '朗讀模式').props.onClick()
  await settle()
  const reading = all(view.root, node => node.props.class === 'std-textarea')[0]
  reading.props['onUpdate:modelValue']('尚未播放的朗讀內容')
  button(view.root, '對話模式').props.onClick()
  await settle()
  assert.equal(all(view.root, node => node.type === 'textarea')[0].value, '尚未送出的對話')
  button(view.root, '朗讀模式').props.onClick()
  await settle()
  assert.equal(all(view.root, node => node.props.class === 'std-textarea')[0].value, '尚未播放的朗讀內容')
  assert.equal(view.calls.some(call => call.url === '/human'), false)
})

test('對話設定入口進入正確分類，返回時保留目前模式與草稿', async t => {
  const view = await consoleView(t)
  button(view.root, '語音驗證').props.onClick()
  await settle()
  all(view.root, node => node.props.id === 'voiceTestPrompt')[0].props['onUpdate:modelValue']('往返設定仍保留')
  button(view.root, '對話設定').props.onClick()
  await settle()
  const settings = all(view.root, node => node.props.id === 'viewSettings')[0]
  assert.match(settings.props.class, /active/)
  assert.match(textContent(settings), /conversation/)
  button(view.root, '更新語系摘要').props.onClick()
  await settle()
  assert.match(textContent(all(view.root, node => node.props.class === 'console-locale-summary')[0]), /English/)
  button(view.root, '返回控制台').props.onClick()
  await settle()
  assert.match(all(view.root, node => node.props.id === 'viewConsole')[0].props.class, /active/)
  assert.equal(button(view.root, '語音驗證').props['aria-pressed'], true)
  assert.equal(all(view.root, node => node.props.id === 'voiceTestPrompt')[0].value, '往返設定仍保留')
  assert.equal(view.calls.some(call => call.url === '/human'), false)
})

test('尚未連線的快捷指令會明確提示先連線', async t => {
  const view = await consoleView(t, { connected: false })
  button(view.root, '自我介紹 (SIMPLE)').props.onClick()
  await settle()
  assert.equal(view.calls.some(call => call.url === '/human'), false)
  assert.match(textContent(view.root), /notifications.connectFirst/)
})

test('角色轉場中的快捷指令保留問題並顯示提示', async t => {
  const view = await consoleView(t, { rolePhase: 'transition' })
  button(view.root, '自我介紹 (SIMPLE)').props.onClick()
  await settle()
  assert.equal(view.calls.some(call => call.url === '/human'), false)
  assert.match(textContent(view.root), /角色準備或轉場中/)
  const input = all(view.root, node => node.type === 'textarea')[0]
  assert.equal(input.value, '你好！請簡短自我介紹')
})

test('快捷指令送出後立即顯示問題與傳送狀態，不等待後端回應', async t => {
  let finish
  const humanResponse = new Promise(resolve => { finish = resolve })
  const view = await consoleView(t, { humanResponse })
  const sending = button(view.root, '核心技術優勢').props.onClick()
  await settle()
  try {
    assert.equal(view.calls.filter(call => call.url === '/human').length, 1)
    assert.ok(all(view.root, node => node.props.innerHTML?.includes('請整理 Nova Avatar 三大核心技術優勢並輸出看板')).length,
      '點擊後即顯示使用者問題')
    assert.match(textContent(view.root), /傳送中/)
  } finally {
    finish({ ok: true, json: async () => ({ code: 0, turn_id: 'accepted-shortcut' }) })
    await sending; await settle()
  }
  assert.equal(all(view.root, node => node.props.innerHTML?.includes('請整理 Nova Avatar 三大核心技術優勢並輸出看板')).length, 1)
  assert.doesNotMatch(textContent(view.root), /傳送中/)
})

test('快捷指令被後端拒絕時顯示錯誤、移除暫存訊息並保留問題', async t => {
  let finish
  const view = await consoleView(t, { humanResponse: new Promise(resolve => { finish = resolve }) })
  const sending = button(view.root, '自我介紹 (SIMPLE)').props.onClick()
  await settle()
  assert.match(textContent(view.root), /傳送中/)
  finish({ ok: false, json: async () => ({ code: -1, msg: '回覆事件通道尚未就緒，請稍後再試' }) })
  await sending; await settle()
  assert.match(textContent(view.root), /回覆事件通道尚未就緒/)
  assert.doesNotMatch(textContent(view.root), /傳送中/)
  assert.equal(all(view.root, node => node.props.innerHTML?.includes('你好！請簡短自我介紹')).length, 0)
  assert.equal(all(view.root, node => node.type === 'textarea')[0].value, '你好！請簡短自我介紹')
})

test('上一題仍在傳送時可立即點快捷指令插話', async t => {
  let finish
  const view = await consoleView(t, { humanResponse: new Promise(resolve => { finish = resolve }) })
  const sending = button(view.root, '核心技術優勢').props.onClick()
  await settle()
  const interrupting = button(view.root, '自我介紹 (SIMPLE)').props.onClick()
  await settle()
  try {
    const requests = view.calls.filter(call => call.url === '/human')
    assert.equal(requests.length, 2, '新問題應立即送出，不等待上一題 HTTP 回應')
    assert.equal(requests[1].body.text, '你好！請簡短自我介紹')
    assert.equal(requests[1].body.interrupt, true)
    assert.doesNotMatch(textContent(view.root), /上一個問題正在傳送/)
    assert.equal(all(view.root, node => node.props.innerHTML?.includes('你好！請簡短自我介紹')).length, 1)
  } finally {
    finish({ ok: true, json: async () => ({ code: 0, turn_id: 'shortcut' }) })
    await Promise.all([sending, interrupting]); await settle()
  }
})

test('傳送期間可繼續輸入並按送出插話', async t => {
  let finish, attempts = 0
  const view = await consoleView(t, { humanResponse: () => ++attempts === 1
    ? new Promise(resolve => { finish = resolve })
    : { ok: true, json: async () => ({ code: 0, turn_id: 'typed-turn' }) } })
  const sending = button(view.root, '核心技術優勢').props.onClick()
  await settle()
  try {
    const input = all(view.root, node => node.type === 'textarea')[0]
    assert.equal(Boolean(input.props.disabled), false)
    input.props['onUpdate:modelValue']('請改為簡短回答')
    await settle()
    const send = button(view.root, '送出')
    assert.equal(Boolean(send.props.disabled), false)
    await send.props.onClick(); await settle()
    assert.equal(view.calls.filter(call => call.url === '/human').at(-1).body.text, '請改為簡短回答')
    assert.doesNotMatch(textContent(view.root), /傳送中/)
  } finally {
    finish({ ok: true, json: async () => ({ code: 0, turn_id: 'stale-shortcut' }) })
    await sending; await settle()
  }
})

test('取消後晚到的舊回應不會移除新快捷指令訊息', async t => {
  let finish, attempts = 0
  const firstResponse = new Promise(resolve => { finish = resolve })
  const view = await consoleView(t, { humanResponse: () => ++attempts === 1 ? firstResponse
    : { ok: true, json: async () => ({ code: 0, turn_id: 'new-shortcut' }) } })
  const first = button(view.root, '核心技術優勢').props.onClick()
  await settle()
  await button(view.root, '取消').props.onClick()
  await button(view.root, '自我介紹 (SIMPLE)').props.onClick()
  await settle()
  finish({ ok: true, json: async () => ({ code: 0, turn_id: 'old-shortcut' }) })
  await first; await settle()
  assert.equal(all(view.root, node => node.props.innerHTML?.includes('請整理 Nova Avatar 三大核心技術優勢並輸出看板')).length, 0)
  assert.equal(all(view.root, node => node.props.innerHTML?.includes('你好！請簡短自我介紹')).length, 1)
  assert.doesNotMatch(textContent(view.root), /傳送中/)
})
