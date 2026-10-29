// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { defineComponent, h } from 'vue'
import { adminSession, installSessionExpiry, login, logout, refreshSession } from '../src/adminSession.js'
import { button, loadComponent, mount, settle, textContent } from './helpers/componentHarness.js'

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body })

function withFetch(t, handler) {
  const previous = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, init = {}) => { calls.push({ url, init }); return handler(url, init) }
  t.after(() => { globalThis.fetch = previous; adminSession.status = 'checking'; adminSession.error = '' })
  return calls
}

test('登入狀態依 /api/session 決定登入、未設定或已登入', async t => {
  let data = { authenticated: false, configured: true }
  withFetch(t, () => json(200, { code: 0, data }))
  assert.equal(await refreshSession(), 'anonymous')
  data = { authenticated: true, configured: true }
  assert.equal(await refreshSession(), 'authenticated')
  data = { authenticated: false, configured: false }
  assert.equal(await refreshSession(), 'unconfigured')
})

test('登入成功切換狀態，失敗顯示後端訊息', async t => {
  let status = 401
  const calls = withFetch(t, () => json(status, status === 200 ? { code: 0 } : { code: -1, reason: 'invalid_password', msg: '密碼錯誤' }))
  adminSession.status = 'anonymous'
  assert.equal(await login('wrong'), false)
  assert.equal(adminSession.status, 'anonymous')
  assert.equal(adminSession.error, '密碼錯誤')
  assert.deepEqual(JSON.parse(calls[0].init.body), { password: 'wrong' })
  assert.equal(calls[0].init.method, 'POST')
  status = 200
  assert.equal(await login('right'), true)
  assert.equal(adminSession.status, 'authenticated')
  assert.equal(adminSession.error, '')
  await logout()
  assert.equal(calls.at(-1).url, '/api/logout')
  assert.equal(adminSession.status, 'anonymous')
})

test('任何控制台 API 回 401 時回到登入畫面', async t => {
  const target = { fetch: async url => json(url === '/api/settings' ? 401 : 200, {}) }
  t.after(() => { adminSession.status = 'checking'; adminSession.error = '' })
  installSessionExpiry(target)
  const wrapped = target.fetch
  installSessionExpiry(target)
  assert.equal(target.fetch, wrapped, 'installing twice keeps one wrapper')
  adminSession.status = 'authenticated'
  await target.fetch('/api/stage')
  assert.equal(adminSession.status, 'authenticated')
  const response = await target.fetch('/api/settings')
  assert.equal(response.status, 401, 'callers still see the response')
  assert.equal(adminSession.status, 'anonymous')
  assert.match(adminSession.error, /重新登入/)
})

test('控制台根元件：未登入顯示登入表單，登入後才掛載主控制台', async t => {
  let authenticated = false
  withFetch(t, url => url === '/api/session'
    ? json(200, { code: 0, data: { authenticated, configured: true } })
    : json(200, { code: 0 }))
  const AppStub = defineComponent({ render: () => h('div', 'MAIN CONSOLE') })
  const AdminLogin = await loadComponent(new URL('../src/components/AdminLogin.vue', import.meta.url))
  const Root = await loadComponent(new URL('../src/ConsoleRoot.vue', import.meta.url), {
    './App.vue': { default: AppStub }, './components/AdminLogin.vue': { default: AdminLogin }
  })
  const view = mount(Root, {})
  t.after(() => view.unmount())
  await settle()
  assert.match(textContent(view.root), /管理者密碼/)
  assert.doesNotMatch(textContent(view.root), /MAIN CONSOLE/)
  adminSession.status = 'authenticated'
  await settle()
  assert.match(textContent(view.root), /MAIN CONSOLE/)
  adminSession.status = 'anonymous'
  await settle()
  assert.doesNotMatch(textContent(view.root), /MAIN CONSOLE/)
})

test('未設定密碼時登入畫面提示設定腳本', async t => {
  withFetch(t, () => json(200, { code: 0, data: { authenticated: false, configured: false } }))
  const Login = await loadComponent(new URL('../src/components/AdminLogin.vue', import.meta.url))
  await refreshSession()
  const view = mount(Login, {})
  t.after(() => view.unmount())
  await settle()
  assert.match(textContent(view.root), /scripts\/configure-admin\.py/)
  assert.ok(button(view.root, '重新檢查'))
})

test('數位人舞台不載入控制台登入', () => {
  const stage = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')
  assert.doesNotMatch(stage, /adminSession|AdminLogin|ConsoleRoot/)
  const main = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8')
  assert.match(main, /installSessionExpiry\(\)/)
  assert.match(main, /createApp\(ConsoleRoot\)/)
})
