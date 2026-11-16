// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const stageHtml = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
const stageLocale = readFileSync(new URL('../src/stageLocale.js', import.meta.url), 'utf8')
const appVue = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('web/stage.html and stageLocale.js contain no veilAlt or console navigation links', () => {
  assert.doesNotMatch(stageHtml, /veilAlt/)
  assert.doesNotMatch(stageHtml, /開啟控制台/)
  assert.doesNotMatch(stageHtml, /window\.location\.href\s*=\s*['"]\/['"]/)
  assert.doesNotMatch(stageHtml, /<a\b[^>]*href=["']\/["']/i)
  assert.doesNotMatch(stageLocale, /開啟控制台|Open console/i)
})

test('adminAuth client helper queries status, logs in with credentials, handles 401/429, and logs out', async () => {
  const { fetchAdminAuthStatus, loginAdmin, logoutAdmin } = await import('../src/adminAuth.js')
  const calls = []
  const fakeFetch = async (url, options = {}) => {
    calls.push({ url, options })
    if (url === '/api/admin/status') {
      return {
        ok: true,
        status: 200,
        json: async () => ({ code: 0, data: { auth_enabled: true, authenticated: false } }),
      }
    }
    if (url === '/api/admin/login') {
      const body = JSON.parse(options.body)
      if (body.password === 'bad') {
        return { ok: false, status: 401, json: async () => ({ code: -1, msg: '密碼錯誤' }) }
      }
      if (body.password === 'locked') {
        return {
          ok: false,
          status: 429,
          json: async () => ({ code: -1, msg: '嘗試次數過多，請稍後再試', retry_after: 60 }),
        }
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ code: 0, data: { auth_enabled: true, authenticated: true } }),
      }
    }
    if (url === '/api/admin/logout') {
      return {
        ok: true,
        status: 200,
        json: async () => ({ code: 0, data: { auth_enabled: true, authenticated: false } }),
      }
    }
    throw new Error(`Unexpected URL: ${url}`)
  }

  const status = await fetchAdminAuthStatus(fakeFetch)
  assert.deepEqual(status, { ok: true, auth_enabled: true, authenticated: false })
  assert.equal(calls[0].options.credentials, 'same-origin')

  const badLogin = await loginAdmin('bad', fakeFetch)
  assert.deepEqual(badLogin, { ok: false, status: 401, message: '密碼錯誤', retryAfter: null })

  const rateLimited = await loginAdmin('locked', fakeFetch)
  assert.deepEqual(rateLimited, {
    ok: false,
    status: 429,
    message: '嘗試次數過多，請稍後再試',
    retryAfter: 60,
  })

  const okLogin = await loginAdmin('secret', fakeFetch)
  assert.deepEqual(okLogin, { ok: true, auth_enabled: true, authenticated: true })

  const out = await logoutAdmin(fakeFetch)
  assert.deepEqual(out, { auth_enabled: true, authenticated: false })
})

test('App.vue checks /api/admin/status before mounting console viewport/SettingsPanel and renders login & logout UI', () => {
  assert.match(appVue, /fetchAdminAuthStatus/)
  assert.match(appVue, /class="app-viewport"\s+v-if="canRenderConsole"/)
  assert.match(appVue, /id="adminLoginGate"/)
  assert.match(appVue, /id="adminPasswordInput"/)
  assert.match(appVue, /id="btnAdminLogin"/)
  assert.match(appVue, /id="btnAdminLogout"/)
  assert.match(appVue, /adminAuthEnabled\s*&&\s*adminAuthenticated/)
  assert.match(appVue, /id="adminAuthDisabledBadge"/)
  assert.match(appVue, /!adminAuthEnabled/)
  assert.match(appVue, /未啟用管理者認證/)
  // Ensure VAD/settings initialization runs after auth gate, not unconditionally before status check.
  const mountedBlock = appVue.match(/onMounted\(async \(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''
  assert.match(mountedBlock, /refreshAdminAuth/)
  assert.doesNotMatch(mountedBlock, /loadVadSettings\(\)\.then/)
})
