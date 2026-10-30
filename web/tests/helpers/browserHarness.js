// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Serves the console with Vite and opens it in headless Chrome, answering
// every backend path with the stubs in fixtures/settingsApi.js. Needs a
// Chrome or Chromium binary: the installed Google Chrome by default, or
// CHROME_PATH. Without one the caller skips, except under CI.
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { chromium } from 'playwright-core'
import { isBackendPath, settingsApi } from '../fixtures/settingsApi.js'

const webRoot = fileURLToPath(new URL('../..', import.meta.url))

async function launchBrowser() {
  const executablePath = process.env.CHROME_PATH
  // Keep classic scrollbars: a 100vw box only overflows when they take space.
  const options = { ignoreDefaultArgs: ['--hide-scrollbars'] }
  try {
    return await chromium.launch(executablePath ? { ...options, executablePath } : { ...options, channel: 'chrome' })
  } catch (error) {
    return { error }
  }
}

// Returns { browser, origin } or null after skipping the test.
export async function openConsoleHarness(t) {
  const browser = await launchBrowser()
  if (browser.error) {
    if (process.env.CI) throw browser.error
    t.skip(`no Chrome available (${browser.error.message.split('\n')[0]}); set CHROME_PATH to run`)
    return null
  }
  // No proxy: every backend path is answered by the stubs below.
  const server = await createServer({
    configFile: false, root: webRoot, plugins: [vue()], logLevel: 'error',
    server: { host: '127.0.0.1', port: 0, hmr: false }
  })
  t.after(async () => { await browser.close(); await server.close() })
  await server.listen()
  return { browser, origin: server.resolvedUrls.local[0] }
}

export async function stubBackend(page) {
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (!isBackendPath(url.pathname)) return route.continue()
    return route.fulfill(settingsApi(url.pathname))
  })
}

// Each state opens one settings tab, optionally a sub-view, and names its blocks.
export const settingsStates = [
  { id: 'conversation', select: ['#catPanel-conversation select', '11'], blocks: '.conversation-panel' },
  { id: 'roles', blocks: '.role-list, .role-editor-card' },
  { id: 'roles', view: 'voice', open: ['聲音與工具'], blocks: '.role-list, .role-editor-card' },
  { id: 'roles', view: 'handoff', open: ['角色組合、交接與轉場'], blocks: '.role-handoff > .role-card' },
  { id: 'greeting', blocks: '.greeting-side, .greeting-main' },
  { id: 'interaction', blocks: '.setting-card' },
  { id: 'avatar', blocks: '.setting-card' },
  { id: 'stage', blocks: '.setting-card, .stage-live-preview-card' },
  { id: 'experience', blocks: '.setting-card' }
]

export async function openSettingsState(page, state) {
  await page.click(`#railTab-${state.id}`)
  for (const label of state.open || []) await page.getByRole('button', { name: label, exact: true }).click()
  if (state.select) await page.selectOption(...state.select)
  await page.waitForTimeout(300)
}
