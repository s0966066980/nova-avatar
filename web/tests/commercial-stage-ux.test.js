// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import { stageText, stageItemCount, stageErrorGuidance } from '../src/stageLocale.js'
import { configureReplyPlayout } from '../src/replyPlayout.js'
import { mountPresentation, presentationPlayer, exportSceneRecording } from '../src/prerecordedPlayer.js'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const settingsPanel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)
const stageHtml = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const stageScript = stageHtml.match(/<script type="module">([\s\S]*?)<\/script>/)?.[1]
const composerVue = readFileSync(
  new URL('../src/components/ConversationComposer.vue', import.meta.url),
  'utf8'
)

function stageUxHarness({
  stageConfig = {},
  mediaDevices = undefined,
  humanResponse = async () => ({ ok: true, json: async () => ({ code: 0, turn_id: 'welcome-1' }) })
} = {}) {
  const elements = new Map()
  const makeNode = (id = '', tagName = 'div') => {
    const handlers = new Map()
    const node = {
      id,
      tagName,
      hidden: id === 'audioUnlock' || id === 'recommendedPrompts' || id === 'stageNotice' || id === 'stageNoticeAction',
      disabled: id === 'mic',
      muted: false,
      volume: 1,
      paused: true,
      srcObject: null,
      dataset: {},
      style: { setProperty() {} },
      className: '',
      classList: { add() {}, remove() {}, toggle() {} },
      children: [],
      _text: '',
      _innerHTMLWrites: 0,
      get textContent() { return this._text },
      set textContent(value) {
        this._text = String(value ?? '')
        if (this._text === '') this.children = []
      },
      get innerHTML() {
        return this.children.map((child) => `<${child.tagName}>${child.textContent}</${child.tagName}>`).join('')
      },
      set innerHTML(val) {
        this._innerHTMLWrites += 1
        throw new Error(`Unsafe innerHTML write attempted on #${this.id}: ${val}`)
      },
      appendChild(child) { this.children.push(child); return child },
      append(...items) { this.children.push(...items) },
      clientWidth: 360,
      clientHeight: 640,
      addEventListener(type, handler) { handlers.set(type, handler) },
      dispatch(type) { handlers.get(type)?.({ preventDefault() {} }) },
      setAttribute() {},
      async play() { this.paused = false }
    }
    return node
  }
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, makeNode(id))
    return elements.get(id)
  }

  let peer
  let channel
  const humanRequests = []
  const track = { enabled: false, stop() {} }
  const defaultMediaDevices = {
    getUserMedia: async () => ({ getAudioTracks: () => [track], getTracks: () => [track] })
  }

  class Peer {
    constructor() { this.connectionState = 'new'; peer = this }
    createDataChannel() {
      channel = { readyState: 'open', send() {}, close() {} }
      return channel
    }
    addTrack() {}
    addTransceiver() {}
    getTransceivers() { return [{ receiver: { track: { kind: 'audio' } }, sender: { replaceTrack: async () => {} } }] }
    async createOffer() { return { sdp: 'offer', type: 'offer' } }
    async setLocalDescription(value) { this.localDescription = value }
    async setRemoteDescription() {}
    close() {}
  }

  const context = {
    stageText, stageItemCount, stageErrorGuidance,
    newClientId: () => 'stage-test',
    releaseSession: async () => {},
    avatarIsReady: async () => true,
    downloadMedia: async () => {},
    configureReplyPlayout,
    mountPresentation, presentationPlayer, exportSceneRecording,
    document: {
      getElementById: (id) => id === 'scene-record-controls' ? elements.get(id) || null : element(id),
      createElement: (tag) => makeNode('', tag),
      documentElement: { setAttribute() {} },
      title: ''
    },
    window: { ResizeObserver: null, isSecureContext: true },
    isSecureContext: true,
    navigator: { mediaDevices: mediaDevices === undefined ? defaultMediaDevices : mediaDevices },
    RTCPeerConnection: Peer,
    RTCSessionDescription: class { constructor(value) { Object.assign(this, value) } },
    MediaStream: class { getTracks() { return [] } addTrack() {} },
    StageCaptionWindow: class {},
    StageCaptionView: class {
      constructor({ container }) { this.container = container }
      append(text) { this.container.textContent += text }
      clear() { this.container.textContent = '' }
      destroy() {}
    },
    DEFAULT_STAGE_CAPTION_MAX_CHARS: 200,
    reactive: value => value,
    createApp: () => ({ mount() {} }),
    h: () => null,
    composerSettings: values => ({ composer_enabled: false, ...values }),
    shouldFadeStageReply: () => true,
    boardReopenPresentation: () => ({ style: {}, edge: 'top', icon: '▣' }),
    placeStageCaption: () => ({}),
    previewScale: () => 1,
    STAGE_CAPTION_RATIO: 0.9,
    STAGE_BOARD_PREVIEW_ITEMS: [],
    STAGE_BOARD_PREVIEW_TITLE: '',
    placeStageBoard: () => ({ width: 200, height: 200, left: 0, top: 0 }),
    fetch: async (url, options = {}) => {
      if (url === '/api/vad') return { ok: true, json: async () => ({ data: { enabled: true } }) }
      if (url === '/api/stage') return { ok: true, json: async () => ({ data: { composer_enabled: false, ...stageConfig } }) }
      if (url === '/human') {
        const body = JSON.parse(options.body)
        humanRequests.push(body)
        return humanResponse(body)
      }
      if (url === '/clear_history') {
        humanRequests.push({ _endpoint: '/clear_history' })
        return { ok: true, json: async () => ({ code: 0 }) }
      }
      return { ok: true, json: async () => ({ sessionid: 7, sdp: 'answer', type: 'answer' }) }
    },
    setTimeout: () => 1,
    clearTimeout() {},
    setInterval() {},
    addEventListener() {},
  }
  const body = stageScript.replace(/^import[\s\S]*?from '[^']+';\s*/gm, '')
  vm.runInNewContext(body, context)

  return {
    element,
    humanRequests,
    async enter(locale = 'zh-TW') {
      const btn = { dataset: { locale } }
      element('stageLocale').value = locale
      const promise = element('entryLanguages').querySelectorAll?.('[data-locale]')
      void promise
      element('veilBtn').onclick()
      await new Promise((r) => setImmediate(r))
      peer.connectionState = 'connected'
      peer.onconnectionstatechange()
      channel.onopen()
      await new Promise((r) => setImmediate(r))
      return btn
    },
    event(data) { channel.onmessage({ data: JSON.stringify(data) }) }
  }
}

test('App.vue 移除測試快捷指令列與原型佔位字串', () => {
  assert.doesNotMatch(app, /quick-chips-row/)
  assert.doesNotMatch(app, /quickCommands/)
  assert.doesNotMatch(app, /核心優勢看板/)
  assert.doesNotMatch(app, /好的！這三大核心優勢已同步呈現於右側 9:16 舞台看板中。/)
})

test('App.vue 將 VoiceTestPanel 與 DebugPanel 保留於原本位置，不放在頂部導航抽屜', () => {
  const toolbarMatch = app.match(/<div class="mode-pills-wrap">([\s\S]*?)<\/div>/)
  assert.ok(toolbarMatch, 'mode-pills-wrap toolbar must exist')
  assert.match(toolbarMatch[1], /語音驗證/)

  assert.doesNotMatch(app, /id="maintenanceDrawer"/)
  assert.doesNotMatch(app, /id="btnMaintenanceDrawer"/)
  assert.match(app, /<VoiceTestPanel\s+v-if="showTestPanel"/)
  assert.match(app, /<DebugPanel\s+v-if="canRenderConsole && appSettings\.showDebugPanel"/)
  assert.doesNotMatch(settingsPanel, /開啟維護診斷抽屜/)
})

test('stage.html 進場手勢後安全顯示舞台歡迎詞，且 welcome_speak 開啟時僅觸發一次語音歡迎', async () => {
  const silentStage = stageUxHarness({
    stageConfig: {
      welcome_text: '<img src=x onerror=alert(1)> 歡迎蒞臨現場',
      welcome_speak: false
    }
  })
  await silentStage.enter('zh-TW')
  assert.equal(
    silentStage.element('reply').textContent,
    '<img src=x onerror=alert(1)> 歡迎蒞臨現場'
  )
  assert.equal(silentStage.humanRequests.length, 0)

  const speakingStage = stageUxHarness({
    stageConfig: {
      welcome_text: '歡迎來到 Nova Avatar 展區',
      welcome_speak: true
    }
  })
  await speakingStage.enter('zh-TW')
  assert.equal(speakingStage.element('reply').textContent, '歡迎來到 Nova Avatar 展區')
  assert.deepEqual(speakingStage.humanRequests, [
    {
      type: 'echo',
      sessionid: 7,
      client_id: 'stage-test',
      text: '歡迎來到 Nova Avatar 展區',
      interrupt: false
    }
  ])
})

test('stage.html 推薦提問為空時隱藏；有設定時安全渲染 0-4 題並透過 /human 送出', async () => {
  const emptyStage = stageUxHarness({ stageConfig: { recommended_prompts: [] } })
  await emptyStage.enter('zh-TW')
  assert.equal(emptyStage.element('recommendedPrompts').hidden, true)
  assert.equal(emptyStage.element('recommendedPrompts').children.length, 0)

  const promptStage = stageUxHarness({
    stageConfig: {
      recommended_prompts: [
        '<script>alert(1)</script> 產品介紹',
        '現場導覽路線？'
      ]
    }
  })
  await promptStage.enter('zh-TW')
  const container = promptStage.element('recommendedPrompts')
  assert.equal(container.hidden, false)
  assert.equal(container.children.length, 2)
  assert.equal(container.children[0].tagName, 'button')
  assert.equal(container.children[0].textContent, '<script>alert(1)</script> 產品介紹')

  await container.children[1].onclick()
  assert.equal(promptStage.element('said').textContent, '現場導覽路線？')
  assert.deepEqual(promptStage.humanRequests.at(-1), {
    type: 'chat',
    sessionid: 7,
    client_id: 'stage-test',
    text: '現場導覽路線？',
    attachments: [],
    interrupt: true
  })
})

test('stage.html 與 stageLocale 提供麥克風拒權、ASR 拒收、LLM/TTS 失敗與不支援檔案/頁數之友善提示與一鍵恢復', async () => {
  const deniedErr = new Error('Permission denied')
  deniedErr.name = 'NotAllowedError'
  let allowMicNow = false
  const stage = stageUxHarness({
    mediaDevices: {
      getUserMedia: async () => {
        if (!allowMicNow) throw deniedErr
        const track = { enabled: false, stop() {} }
        return { getAudioTracks: () => [track], getTracks: () => [track] }
      }
    }
  })
  await stage.enter('zh-TW')
  assert.equal(stage.element('stageNotice').hidden, false)
  assert.match(stage.element('stageNoticeText').textContent, /麥克風權限/)
  assert.equal(stage.element('stageNoticeAction').hidden, false)
  assert.match(stage.element('stageNoticeAction').textContent, /重試麥克風/)

  allowMicNow = true
  await stage.element('stageNoticeAction').onclick()
  assert.equal(stage.element('stageNotice').hidden, true)

  stage.event({ seq: 1, type: 'speech_rejected', reason: 'speech_too_short' })
  assert.equal(stage.element('stageNotice').hidden, false)
  assert.match(stage.element('stageNoticeText').textContent, /太短/)
  assert.equal(stage.element('stageNoticeAction').hidden, false)

  stage.event({ seq: 2, type: 'state', state: 'error', error: 'tts_error_before_commit' })
  assert.equal(stage.element('stageNotice').hidden, false)
  assert.match(stage.element('stageNoticeText').textContent, /語音/)

  const pdfGuide = stageErrorGuidance('page_limit', 'zh-TW')
  assert.match(pdfGuide.message, /40 頁/)
  const fmtGuide = stageErrorGuidance('unsupported_file', 'en-US')
  assert.match(fmtGuide.message, /PDF, JPG, PNG, WebP/)
  assert.match(composerVue, /composer-error-recovery/)
})
