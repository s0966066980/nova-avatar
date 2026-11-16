// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import vm from 'node:vm'
import test from 'node:test'
import { JSDOM } from 'jsdom'

import { renderSafeMarkdown } from '../src/sanitizeHtml.js'
import { stageText, stageItemCount } from '../src/stageLocale.js'
import { configureReplyPlayout } from '../src/replyPlayout.js'
import { mountPresentation, presentationPlayer, exportSceneRecording } from '../src/prerecordedPlayer.js'

function withDom(fn) {
  const dom = new JSDOM('<!doctype html><html><body></body></html>')
  return fn(dom.window)
}

test('renderSafeMarkdown removes script, event handlers, svg, style, iframe/object, and unsafe URIs while preserving safe markdown', () => {
  withDom((win) => {
    const doc = win.document
    const parseFragment = (html) => {
      const container = doc.createElement('div')
      container.innerHTML = html
      return container
    }

    const scriptOut = parseFragment(
      renderSafeMarkdown('Hello <script>alert(1)</script> **world**', { domWindow: win })
    )
    assert.equal(scriptOut.querySelector('script'), null)
    assert.match(scriptOut.innerHTML, /<strong>world<\/strong>/)
    assert.match(scriptOut.textContent, /Hello/)

    const imgOut = parseFragment(
      renderSafeMarkdown('<img src="https://example.com/ok.png" onerror="alert(1)" style="color:red" alt="pic">', { domWindow: win })
    )
    const img = imgOut.querySelector('img')
    assert.ok(img)
    assert.equal(img.getAttribute('src'), 'https://example.com/ok.png')
    assert.equal(img.getAttribute('onerror'), null)
    assert.equal(img.getAttribute('style'), null)

    const jsLinkOut = parseFragment(
      renderSafeMarkdown('[click](javascript:alert(1)) and [safe](https://example.com)', { domWindow: win })
    )
    const links = jsLinkOut.querySelectorAll('a')
    assert.equal(links.length, 2)
    assert.equal(links[0].getAttribute('href'), null)
    assert.equal(links[0].textContent, 'click')
    assert.equal(links[1].getAttribute('href'), 'https://example.com')

    const dataLinkOut = parseFragment(
      renderSafeMarkdown('[bad](data:text/html,<script>alert(1)</script>) <img src="data:image/svg+xml,<svg onload=alert(1)>">', { domWindow: win })
    )
    const badLink = dataLinkOut.querySelector('a')
    assert.equal(badLink?.getAttribute('href') ?? null, null)
    const dataImg = dataLinkOut.querySelector('img')
    assert.equal(dataImg?.getAttribute('src') ?? null, null)

    const svgOut = parseFragment(
      renderSafeMarkdown('<svg onload="alert(1)"><circle onload="alert(2)"></circle></svg><iframe src="https://evil.test"></iframe><object data="x"></object>', { domWindow: win })
    )
    assert.equal(svgOut.querySelector('svg'), null)
    assert.equal(svgOut.querySelector('iframe'), null)
    assert.equal(svgOut.querySelector('object'), null)
    assert.equal(svgOut.innerHTML.includes('onload'), false)
  })
})

test('renderSafeMarkdown preserves safe code blocks, lists, and tables, and fails closed without a DOM', () => {
  withDom((win) => {
    const md = [
      '## 標題',
      '',
      '- 項目一',
      '- 項目二',
      '',
      '```js',
      'const x = "<script>alert(1)</script>";',
      '```',
      '',
      '| A | B |',
      '| - | - |',
      '| 1 | 2 |',
    ].join('\n')
    const html = renderSafeMarkdown(md, { domWindow: win })
    const doc = win.document
    const container = doc.createElement('div')
    container.innerHTML = html
    assert.equal(container.querySelector('h2')?.textContent, '標題')
    assert.equal(container.querySelectorAll('li').length, 2)
    assert.ok(container.querySelector('pre code.hljs'))
    assert.equal(container.querySelector('script'), null)
    assert.equal(container.querySelectorAll('td').length, 2)
  })

  // Fail-closed when no DOM window is present
  const prevWindow = globalThis.window
  delete globalThis.window
  try {
    const escaped = renderSafeMarkdown('<img src=x onerror=alert(1)>')
    assert.equal(escaped.includes('<img'), false)
    assert.equal(escaped.includes('&lt;img'), true)
  } finally {
    if (prevWindow !== undefined) globalThis.window = prevWindow
  }
})

function stageJsdomHarness() {
  const html = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
  const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)?.[1]
  const dom = new JSDOM(html)
  const doc = dom.window.document
  const video = doc.getElementById('video')
  video.play = async () => {}

  const track = { enabled: false, stop() {} }
  let channel
  let peer
  class Peer {
    constructor() { this.connectionState = 'new'; peer = this }
    createDataChannel() {
      channel = { readyState: 'open', send() {}, close() {} }
      return channel
    }
    addTrack() {}
    addTransceiver() {}
    async createOffer() { return { sdp: 'offer', type: 'offer' } }
    async setLocalDescription(value) { this.localDescription = value }
    async setRemoteDescription() {}
    close() {}
  }

  const context = {
    stageText,
    stageItemCount,
    newClientId: () => 'stage-xss-test',
    releaseSession: async () => {},
    avatarIsReady: async () => true,
    downloadMedia: async () => {},
    configureReplyPlayout,
    mountPresentation,
    presentationPlayer,
    exportSceneRecording,
    document: doc,
    window: Object.assign(dom.window, { ResizeObserver: null }),
    navigator: {
      mediaDevices: {
        getUserMedia: async () => ({ getAudioTracks: () => [track], getTracks: () => [track] }),
      },
    },
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
    shouldFadeStageReply: () => false,
    boardReopenPresentation: () => ({ style: {}, edge: 'top', icon: '▣' }),
    captionStyle: () => ({}),
    placeStageCaption: () => ({}),
    previewScale: () => 1,
    STAGE_CAPTION_RATIO: 0.9,
    STAGE_BOARD_PREVIEW_ITEMS: [],
    STAGE_BOARD_PREVIEW_TITLE: '',
    placeStageBoard: () => ({ width: 200, height: 200, left: 0, top: 0 }),
    fetch: async (url) => ({
      ok: true,
      json: async () => {
        if (url === '/api/vad') return { data: { enabled: true } }
        if (url === '/api/stage') return { data: { composer_enabled: false } }
        return { sessionid: 1, sdp: 'answer', type: 'answer' }
      },
    }),
    requestAnimationFrame: (cb) => cb(),
    setTimeout: () => 1,
    clearTimeout() {},
    setInterval() {},
    addEventListener() {},
  }

  const body = script.replace(/^import[\s\S]*?from '[^']+';\s*/gm, '')
  vm.runInNewContext(body, context)

  return {
    doc,
    async connect() {
      await doc.getElementById('veilBtn').onclick()
      peer.connectionState = 'connected'
      peer.onconnectionstatechange()
      channel.onopen()
    },
    event(payload) {
      channel.onmessage({ data: JSON.stringify(payload) })
    },
  }
}

test('stage.html renderBoardItems builds board DOM safely without HTML injection on malicious title/body', async () => {
  const stage = stageJsdomHarness()
  await stage.connect()

  const maliciousTitle = '<img src=x onerror=alert(1)>'
  const maliciousBody = '<script>alert(1)</script><svg onload=alert(2)>'

  stage.event({
    seq: 1,
    type: 'assistant_board',
    turn_id: 'turn-1',
    board: {
      title: '<script>evilTitle()</script>',
      items: [{ title: maliciousTitle, body: maliciousBody }],
    },
  })

  const boardList = stage.doc.getElementById('boardList')
  assert.equal(boardList.querySelector('script'), null)
  assert.equal(boardList.querySelector('img'), null)
  assert.equal(boardList.querySelector('svg'), null)
  assert.equal(boardList.querySelectorAll('li.board-item').length, 1)
  assert.equal(boardList.querySelector('.item-number')?.textContent, '01')
  assert.equal(boardList.querySelector('.item-title')?.textContent, maliciousTitle)
  assert.equal(boardList.querySelector('.item-body')?.textContent, maliciousBody)
  assert.equal(stage.doc.getElementById('boardTitle')?.textContent, '<script>evilTitle()</script>')

  // Also verify incremental board_begin + board_item
  stage.event({ seq: 2, type: 'board_begin', turn_id: 'turn-2', title: '安全標題' })
  stage.event({
    seq: 3,
    type: 'board_item',
    turn_id: 'turn-2',
    index: 0,
    title: '<b>not bold</b>',
    body: '<iframe src="javascript:alert(1)"></iframe>',
  })
  assert.equal(boardList.querySelector('b'), null)
  assert.equal(boardList.querySelector('iframe'), null)
  assert.equal(boardList.querySelector('.item-title')?.textContent, '<b>not bold</b>')
  assert.equal(boardList.querySelector('.item-body')?.textContent, '<iframe src="javascript:alert(1)"></iframe>')
})

function collectSourceFiles(dir) {
  const results = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      results.push(...collectSourceFiles(full))
    } else if (/\.(js|vue|html)$/.test(entry)) {
      results.push(full)
    }
  }
  return results
}

test('App.vue uses renderSafeMarkdown and web/src + stage.html contain no unguarded HTML sinks', () => {
  const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.match(appSource, /from\s+['"]\.\/sanitizeHtml\.js['"]/)
  assert.match(appSource, /renderSafeMarkdown\(/)
  assert.doesNotMatch(appSource, /marked\.parse\(/)

  const srcDir = new URL('../src', import.meta.url).pathname
  const targets = [...collectSourceFiles(srcDir), new URL('../stage.html', import.meta.url).pathname]
  for (const filePath of targets) {
    const content = readFileSync(filePath, 'utf8')
    assert.doesNotMatch(
      content,
      /\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b/,
      `Unexpected HTML sink in ${filePath}`
    )
    const vHtmlMatches = content.match(/v-html="[^"]*"/g) || []
    for (const binding of vHtmlMatches) {
      assert.equal(
        binding,
        'v-html="renderMarkdown(msg.text)"',
        `Unexpected v-html binding ${binding} in ${filePath}`
      )
    }
  }
})



