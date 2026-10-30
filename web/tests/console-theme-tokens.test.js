// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// The console defines every colour once, as light-dark(light, dark). These
// checks keep normal text at WCAG AA (4.5:1) on every surface it is used on,
// in both themes, without needing a browser.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const css = readFileSync(new URL('../src/console-prototype.css', import.meta.url), 'utf8')
const tokens = Object.fromEntries(
  [...css.matchAll(/--([\w-]+):\s*light-dark\(\s*(#[0-9a-f]{6})\s*,\s*(#[0-9a-f]{6})\s*\)/gi)]
    .map(([, name, light, dark]) => [name, { light, dark }])
)

function luminance(hex) {
  const channels = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}
export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const surfaces = ['bg-page', 'bg-surface', 'bg-raised', 'bg-sunken', 'bg-input', 'bg-hover']
const pairs = [
  ...['text', 'text-2', 'text-3', 'brand', 'brand-ink', 'ok', 'warn', 'danger'].flatMap(fg => surfaces.map(bg => [fg, bg])),
  ['brand-ink', 'brand-surface'], ['text', 'brand-surface'], ['on-brand', 'brand'], ['on-brand', 'brand-hover'],
  ['ok', 'ok-surface'], ['warn', 'warn-surface'], ['danger', 'danger-surface'], ['text', 'warn-surface'],
  ['text', 'danger-surface'], ['text-2', 'warn-surface'], ['text-2', 'danger-surface'], ['on-danger', 'danger']
]

test('色彩 token 以 light-dark() 一次定義淺色與深色', () => {
  for (const name of new Set(pairs.flat())) assert.ok(tokens[name], `--${name} 需以 light-dark(#淺, #深) 定義`)
  assert.match(css, /:root\[data-theme="light"\]\s*\{\s*color-scheme:\s*light;/)
  assert.match(css, /:root\[data-theme="dark"\]\s*\{\s*color-scheme:\s*dark;/)
  assert.match(css, /:root\s*\{\s*color-scheme:\s*light dark;/)
})

for (const theme of ['light', 'dark']) {
  test(`${theme === 'light' ? '淺色' : '深色'}主題的文字對比至少 4.5:1`, () => {
    const failures = pairs
      .map(([fg, bg]) => [fg, bg, contrast(tokens[fg][theme], tokens[bg][theme])])
      .filter(([, , ratio]) => ratio < 4.5)
      .map(([fg, bg, ratio]) => `--${fg} on --${bg}: ${ratio.toFixed(2)}`)
    assert.deepEqual(failures, [])
  })
}

test('深色主題沿用舞台背景黑與說話中藍', () => {
  assert.equal(tokens['bg-page'].dark, '#08090c')
  assert.equal(tokens.brand.dark, '#7c9cff')
})

test('鍵盤焦點框與減少動態偏好', () => {
  assert.match(css, /:focus-visible\s*\{\s*outline:\s*2px solid var\(--focus-ring\)/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/)
  // 不可再把焦點框整個拿掉
  assert.doesNotMatch(css, /:focus(?:-visible)?\s*\{[^}]*outline:\s*(?:none|0)\b/)
})
