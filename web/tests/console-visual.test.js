// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Renders the live console and every settings tab in headless Chrome, in the
// light and the dark theme, and checks what the visual refresh promises:
// every visible text reaches WCAG AA contrast against what is really behind
// it, the theme option works (system, light, dark), keyboard focus is
// visible, and reduced motion stops animations.
//
// Needs Chrome (see helpers/browserHarness.js); skipped without it except under CI.
// CONSOLE_VISUAL_SCREENSHOTS=<dir> also saves a screenshot per view, size and theme.
import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { openConsoleHarness, openSettingsState, settingsStates, stubBackend } from './helpers/browserHarness.js'

const screenshotDir = process.env.CONSOLE_VISUAL_SCREENSHOTS
const viewports = [{ width: 1920, height: 1080 }, { width: 1280, height: 720 }]
const themeStorageKey = 'nova-avatar-theme'

// Runs in the page: every element with its own visible text must reach 4.5:1
// (3:1 for large text) against the composited background behind it.
// Stage pictures keep the stage's own palette and are left out, as are
// disabled controls, which WCAG exempts.
/* global document, getComputedStyle */
function inspectContrast(scopeSelector) {
  const stageSelector = '.stage-viewport-center, .interactive-large-stage, .theme-swatches'
  const parse = (value) => {
    let m = value.match(/^rgba?\(([^)]+)\)$/)
    if (m) {
      const [r, g, b, a = 1] = m[1].split(/[\s,/]+/).filter(Boolean).map(Number)
      return [r, g, b, a]
    }
    m = value.match(/^color\(srgb ([^)]+)\)$/)
    if (m) {
      const [r, g, b, a = 1] = m[1].replace('/', ' ').split(/\s+/).filter(Boolean).map(Number)
      return [r * 255, g * 255, b * 255, a]
    }
    return null
  }
  const over = (top, bottom) => {
    const a = top[3]
    return [0, 1, 2].map(i => top[i] * a + bottom[i] * (1 - a)).concat(1)
  }
  const lum = ([r, g, b]) => {
    const c = [r, g, b].map(v => v / 255).map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
  }
  const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05) }
  const name = node => node.id ? `#${node.id}` : `${node.tagName.toLowerCase()}${[...node.classList].map(c => `.${c}`).join('')}`

  const problems = []
  let checked = 0
  const scope = document.querySelector(scopeSelector)
  if (!scope) return { checked, problems: [`no ${scopeSelector}`] }
  for (const element of [scope, ...scope.querySelectorAll('*')]) {
    const text = [...element.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()
    if (!text) continue
    const rect = element.getBoundingClientRect()
    if (!rect.width || !rect.height) continue
    const style = getComputedStyle(element)
    if (style.visibility !== 'visible' || element.closest(stageSelector)) continue
    if (element.closest(':disabled, [aria-disabled="true"], [aria-hidden="true"], option')) continue
    // Background: composite every ancestor's colour from the page upwards.
    const chain = []
    let unknown = false
    let opacity = 1
    for (let node = element; node; node = node.parentElement) {
      const cs = getComputedStyle(node)
      opacity *= Number(cs.opacity)
      if (cs.backgroundImage !== 'none' && !cs.backgroundImage.startsWith('url(')) unknown = true
      chain.push(parse(cs.backgroundColor) || [0, 0, 0, 0])
    }
    if (unknown || opacity === 0) continue
    const background = chain.reverse().reduce((under, layer) => over(layer, under), [255, 255, 255, 1])
    const color = parse(style.color)
    if (!color) { problems.push(`${name(element)}: unparsed colour ${style.color}`); continue }
    const foreground = over([color[0], color[1], color[2], color[3] * opacity], background)
    const size = parseFloat(style.fontSize)
    const large = size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700)
    const value = ratio(foreground, background)
    checked += 1
    if (value < (large ? 3 : 4.5)) {
      problems.push(`${name(element)} "${text.slice(0, 24)}" ${value.toFixed(2)}:1 (${style.color} on rgb(${background.slice(0, 3).map(Math.round)}))`)
    }
  }
  return { checked, problems }
}

async function snap(page, file) {
  if (screenshotDir) await page.screenshot({ path: path.join(screenshotDir, file) })
}

test('控制台與設定中心在淺色與深色主題下文字對比至少 4.5:1', { timeout: 240_000 }, async t => {
  const harness = await openConsoleHarness(t)
  if (!harness) return
  const { browser, origin } = harness
  if (screenshotDir) mkdirSync(screenshotDir, { recursive: true })

  const failures = []
  for (const theme of ['light', 'dark']) {
    for (const viewport of viewports) {
      const page = await browser.newPage({ viewport })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.addInitScript(([key, value]) => localStorage.setItem(key, value), [themeStorageKey, theme])
      await stubBackend(page)
      await page.goto(origin)
      await page.waitForSelector('.app-root-shell')
      await page.waitForTimeout(300)
      const size = `${viewport.width}x${viewport.height}`
      const record = (label, result) => {
        if (!result.checked) failures.push(`${label}: no text checked`)
        if (result.problems.length) failures.push(`${label}:\n  ${result.problems.slice(0, 10).join('\n  ')}`)
      }
      record(`console @ ${size} ${theme}`, await page.evaluate(inspectContrast, '.app-root-shell'))
      await snap(page, `console-${size}-${theme}.png`)
      await page.click('#btnViewSettings')
      for (const state of settingsStates) {
        await openSettingsState(page, state)
        const label = `${state.id}${state.view ? `-${state.view}` : ''}`
        record(`${label} @ ${size} ${theme}`, await page.evaluate(inspectContrast, '#viewSettings'))
        await snap(page, `settings-${label}-${size}-${theme}.png`)
      }
      assert.deepEqual(errors, [], `page errors at ${size} ${theme}`)
      await page.close()
    }
  }
  assert.equal(failures.length, 0, `contrast problems:\n${failures.join('\n')}`)
})

test('登入頁在淺色與深色主題下文字對比至少 4.5:1', { timeout: 120_000 }, async t => {
  const harness = await openConsoleHarness(t)
  if (!harness) return
  const failures = []
  for (const theme of ['light', 'dark']) {
    const page = await harness.browser.newPage({ viewport: { width: 1280, height: 720 } })
    await page.addInitScript(([key, value]) => localStorage.setItem(key, value), [themeStorageKey, theme])
    await stubBackend(page)
    // Backend unreachable: the login form shows with its error message.
    await page.route('**/api/session', route => route.abort())
    await page.goto(harness.origin)
    await page.waitForSelector('.admin-login-error')
    const result = await page.evaluate(inspectContrast, '.admin-login')
    if (!result.checked || result.problems.length) failures.push(`login ${theme}: ${result.problems.join('; ') || 'no text'}`)
    await snap(page, `login-1280x720-${theme}.png`)
    await page.close()
  }
  assert.deepEqual(failures, [])
})

test('主題選項跟隨系統、淺色、深色實際生效並記住', { timeout: 120_000 }, async t => {
  const harness = await openConsoleHarness(t)
  if (!harness) return
  const page = await harness.browser.newPage({ viewport: { width: 1920, height: 1080 } })
  await stubBackend(page)
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto(harness.origin)
  await page.waitForSelector('.app-root-shell')
  const pageBackground = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor)
  const themeAttribute = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'))

  // Nothing stored: follow the system, which the page can change live.
  assert.equal(await themeAttribute(), null)
  assert.equal(await pageBackground(), 'rgb(8, 9, 12)')
  await page.emulateMedia({ colorScheme: 'light' })
  assert.equal(await pageBackground(), 'rgb(243, 245, 249)')

  await page.click('#btnViewSettings')
  await page.click('#railTab-experience')
  const options = page.locator('.theme-choice-card')
  assert.equal(await options.count(), 3)
  assert.equal(await page.locator('.theme-choice-card[aria-checked="true"]').innerText().then(text => text.includes('跟隨系統')), true)

  await options.filter({ hasText: '深色模式' }).click()
  assert.equal(await themeAttribute(), 'dark')
  assert.equal(await pageBackground(), 'rgb(8, 9, 12)')
  assert.equal(await page.evaluate(key => localStorage.getItem(key), themeStorageKey), 'dark')

  await page.reload()
  await page.waitForSelector('.app-root-shell')
  assert.equal(await themeAttribute(), 'dark', 'the choice survives a reload')

  await page.click('#btnViewSettings')
  await page.click('#railTab-experience')
  await options.filter({ hasText: '淺色模式' }).click()
  assert.equal(await themeAttribute(), 'light')
  await page.emulateMedia({ colorScheme: 'dark' })
  assert.equal(await pageBackground(), 'rgb(243, 245, 249)', 'a pinned theme ignores the system')

  await options.filter({ hasText: '跟隨系統' }).click()
  assert.equal(await themeAttribute(), null)
  assert.equal(await pageBackground(), 'rgb(8, 9, 12)')
  await page.close()
})

test('鍵盤焦點有品牌色焦點框，減少動態時停止動畫與轉場', { timeout: 120_000 }, async t => {
  const harness = await openConsoleHarness(t)
  if (!harness) return
  const page = await harness.browser.newPage({ viewport: { width: 1920, height: 1080 } })
  await stubBackend(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto(harness.origin)
  await page.waitForSelector('.app-root-shell')
  await page.click('#btnViewSettings')
  await page.click('#railTab-roles')
  await page.keyboard.press('ArrowDown')
  const focus = await page.evaluate(() => {
    const style = getComputedStyle(document.activeElement)
    return { id: document.activeElement.id, outline: style.outlineStyle, width: parseFloat(style.outlineWidth) }
  })
  assert.equal(focus.id, 'railTab-greeting')
  assert.equal(focus.outline, 'solid')
  assert.ok(focus.width >= 2, `outline ${focus.width}px`)

  const motion = await page.evaluate(() => {
    const seconds = value => Math.max(...value.split(',').map(part => parseFloat(part)))
    return [...document.querySelectorAll('.rail-nav-item, .btn-apply-primary, .live-dot, .std-input')]
      .map(node => getComputedStyle(node))
      .map(style => Math.max(seconds(style.transitionDuration), seconds(style.animationDuration)))
  })
  assert.ok(motion.length > 0)
  assert.ok(motion.every(value => value <= 0.001), `durations ${motion}`)
  await page.close()
})
