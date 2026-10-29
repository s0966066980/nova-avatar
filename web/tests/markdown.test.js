// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import createDOMPurify from 'dompurify'
import { JSDOM } from 'jsdom'
import { createMarkdownRenderer, renderMarkdown, stripProtocolMarkers } from '../src/markdown.js'

const { window } = new JSDOM('')
const render = createMarkdownRenderer(createDOMPurify(window))

function parse(html) {
  const doc = new JSDOM(`<body>${html}</body>`).window.document
  return doc.body
}

function assertHarmless(html) {
  const body = parse(html)
  assert.equal(body.querySelectorAll('script, iframe, object, embed, svg, style, form').length, 0, html)
  for (const el of body.querySelectorAll('*')) {
    for (const { name, value } of el.attributes) {
      assert.ok(!/^on/i.test(name), `${name} in ${html}`)
      assert.ok(!/^\s*(?:javascript|vbscript|data):/i.test(value), `${name}=${value} in ${html}`)
    }
  }
}

test('惡意 Markdown 與原始 HTML 渲染後皆無害', () => {
  for (const payload of [
    '<img src=x onerror=alert(1)>',
    '<script>alert(1)</script>',
    '[x](javascript:alert(1))',
    '<a href="javascript:alert(1)">x</a>',
    'hi <img src=x onerror=alert(1)> there',
    '[x](JaVaScRiPt:alert(1))',
    '![x](javascript:alert(1))',
    '<svg onload=alert(1)>',
    '<iframe src="javascript:alert(1)"></iframe>',
  ]) assertHarmless(render(payload))
})

test('一般 Markdown 仍正常渲染', () => {
  const body = parse(render('**粗體**\n\n- 一\n- 二\n\n[連結](https://example.com/a)'))
  assert.equal(body.querySelector('strong')?.textContent, '粗體')
  assert.deepEqual([...body.querySelectorAll('ul > li')].map(li => li.textContent), ['一', '二'])
  assert.equal(body.querySelector('a')?.getAttribute('href'), 'https://example.com/a')
  assert.equal(body.querySelector('a')?.textContent, '連結')
})

test('渲染前先剝除協定標記', () => {
  assert.equal(stripProtocolMarkers('[[MODE: SIMPLE]]你好[[END]]'), '你好')
  assert.equal(render(''), '')
  assert.ok(!render('[SPEECH: 你好]').includes('SPEECH'))
})

test('無 DOM 時預設渲染器失效關閉，只輸出跳脫後的純文字', () => {
  const html = renderMarkdown('<img src=x onerror=alert(1)> **b**')
  assert.ok(!html.includes('<img'), html)
  assert.ok(!html.includes('<'), html)
})

test('App.vue 不再直接使用 marked、highlight.js 或舊的 sanitizeChatText', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.ok(!/from 'marked'|highlight\.js|sanitizeChatText/.test(app))
  assert.equal(app.match(/v-html=/g)?.length, 1)
  assert.match(app, /eslint-disable-next-line vue\/no-v-html[^\n]*\n\s*<div v-html="renderMarkdown\(msg\.text\)">/)
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
  assert.equal(pkg.dependencies['highlight.js'], undefined)
})
