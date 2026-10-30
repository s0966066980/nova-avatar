// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const pages = { 'index.html': read('../index.html'), 'stage.html': read('../stage.html') }
const main = read('../src/main.js')

for (const [name, html] of Object.entries(pages)) {
  test(`${name} 不從外部 CDN 載入樣式、字型或腳本`, () => {
    const external = [...html.matchAll(/<(?:link|script)\b[^>]*\b(?:href|src)\s*=\s*["']((?:https?:)?\/\/[^"']+)/gi)]
      .map((match) => match[1])
    assert.deepEqual(external, [])
  })
}

test('Bootstrap 與 bootstrap-icons 由 npm 套件打包', () => {
  assert.match(main, /import\s+['"]bootstrap\/dist\/css\/bootstrap\.min\.css['"]/)
  assert.match(main, /import\s+['"]bootstrap-icons\/font\/bootstrap-icons\.min\.css['"]/)
  // 專案樣式需在 Bootstrap 之後載入才能覆寫預設值
  assert.ok(main.indexOf('bootstrap.min.css') < main.indexOf('console-prototype.css'))
})

test('介面字型 Plus Jakarta Sans 與 JetBrains Mono 由 npm 套件打包', () => {
  assert.match(main, /import\s+['"]@fontsource\/plus-jakarta-sans\/latin-400\.css['"]/)
  assert.match(main, /import\s+['"]@fontsource\/jetbrains-mono\/latin-400\.css['"]/)
  assert.ok(main.indexOf('@fontsource') < main.indexOf('console-prototype.css'))
})
