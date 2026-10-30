// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Renders every settings tab in headless Chrome at the supported 16:9 sizes
// and checks the layout: nothing scrolls sideways, blocks stay inside their
// own grid cells without overlapping, and long blocks scroll inside
// themselves instead of stretching the page.
//
// Needs Chrome (see helpers/browserHarness.js); skipped without it except under CI.
// SETTINGS_LAYOUT_SCREENSHOTS=<dir> also saves a screenshot per tab and size.
import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { openConsoleHarness, openSettingsState, settingsStates as states, stubBackend } from './helpers/browserHarness.js'

const screenshotDir = process.env.SETTINGS_LAYOUT_SCREENSHOTS
const viewports = [{ width: 1920, height: 1080 }, { width: 1280, height: 720 }]

// Runs in the page: measures the visible tab panel and returns every problem found.
/* global document, getComputedStyle, innerWidth */
function inspectPanel(blockSelector) {
  const problems = []
  const scroller = document.querySelector('.settings-content-scroll')
  const panel = [...document.querySelectorAll('.settings-category-panel')].find(node => node.offsetParent !== null)
  const name = node => node.id ? `#${node.id}` : `${node.tagName.toLowerCase()}.${[...node.classList].join('.')}`
  const root = document.documentElement
  if (root.scrollWidth > innerWidth + 1) problems.push(`page is ${root.scrollWidth}px wide in a ${innerWidth}px window`)
  // Ancestors clip overflow, so also compare the page frame with the window.
  for (const node of document.querySelectorAll('.settings-page-layout, .settings-main-container, .settings-fixed-footer')) {
    if (node.getBoundingClientRect().right > root.clientWidth + 1) problems.push(`${name(node)} extends past the window`)
  }
  if (!panel) return ['no visible settings panel']
  if (scroller.scrollHeight > scroller.clientHeight + 1) {
    problems.push(`settings page scrolls (${scroller.scrollHeight}px content in ${scroller.clientHeight}px)`)
  }
  for (const node of document.querySelectorAll('.settings-page-layout, .settings-page-layout *')) {
    const style = getComputedStyle(node)
    if (['auto', 'scroll'].includes(style.overflowX) && node.scrollWidth > node.clientWidth + 1) {
      problems.push(`${name(node)} scrolls sideways (${node.scrollWidth}px in ${node.clientWidth}px)`)
    }
  }
  const area = scroller.getBoundingClientRect()
  const blocks = [...panel.querySelectorAll(blockSelector)].filter(node => node.offsetParent !== null)
  if (!blocks.length) problems.push(`no blocks match ${blockSelector}`)
  const rects = blocks.map(node => node.getBoundingClientRect())
  blocks.forEach((block, index) => {
    const rect = rects[index]
    if (rect.left < area.left - 1 || rect.right > area.right + 1) problems.push(`${name(block)} leaves the settings area`)
    // A block in an inner scrolling column may continue below; others must fit.
    let scrollParent = block.parentElement
    while (scrollParent !== scroller && !['auto', 'scroll'].includes(getComputedStyle(scrollParent).overflowY)) scrollParent = scrollParent.parentElement
    if (scrollParent === scroller && rect.bottom > area.bottom + 1) problems.push(`${name(block)} ends below the visible area`)
    const style = getComputedStyle(block)
    if (block.scrollHeight > block.clientHeight + 1 && !['auto', 'scroll'].includes(style.overflowY)) {
      problems.push(`${name(block)} clips its content instead of scrolling`)
    }
    rects.slice(index + 1).forEach((other, offset) => {
      const width = Math.min(rect.right, other.right) - Math.max(rect.left, other.left)
      const height = Math.min(rect.bottom, other.bottom) - Math.max(rect.top, other.top)
      if (width > 1 && height > 1) problems.push(`${name(block)} overlaps ${name(blocks[index + offset + 1])}`)
    })
    // Content must stay inside its block unless a nearer box clips or scrolls it.
    for (const child of block.querySelectorAll('*')) {
      const box = child.getBoundingClientRect()
      if (!box.width || !box.height) continue
      let clipped = false
      for (let node = child.parentElement; node && node !== block; node = node.parentElement) {
        if (getComputedStyle(node).overflowX !== 'visible') { clipped = true; break }
      }
      if (!clipped && (box.right > rect.right + 1 || box.left < rect.left - 1)) {
        problems.push(`${name(child)} sticks out of ${name(block)}`)
      }
    }
  })
  return problems
}

test('系統設定中心各分頁在 1920×1080 與 1280×720 不橫向捲動、區塊不重疊且在格內捲動', { timeout: 120_000 }, async t => {
  const harness = await openConsoleHarness(t)
  if (!harness) return
  const { browser, origin } = harness
  if (screenshotDir) mkdirSync(screenshotDir, { recursive: true })

  const failures = []
  for (const viewport of viewports) {
    const page = await browser.newPage({ viewport })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await stubBackend(page)
    await page.goto(origin)
    await page.click('#btnViewSettings')
    for (const state of states) {
      await openSettingsState(page, state)
      const label = `${state.id}${state.view ? `-${state.view}` : ''} @ ${viewport.width}×${viewport.height}`
      const problems = await page.evaluate(inspectPanel, state.blocks)
      if (problems.length) failures.push(`${label}:\n  ${problems.slice(0, 8).join('\n  ')}`)
      if (screenshotDir) {
        await page.screenshot({ path: path.join(screenshotDir, `${state.id}${state.view ? `-${state.view}` : ''}-${viewport.width}x${viewport.height}.png`) })
      }
    }
    assert.deepEqual(errors, [], `page errors at ${viewport.width}×${viewport.height}`)
    await page.close()
  }
  assert.equal(failures.length, 0, `layout problems:\n${failures.join('\n')}`)
})
