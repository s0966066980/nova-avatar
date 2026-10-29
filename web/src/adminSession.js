// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import { reactive } from 'vue'

// status: checking | anonymous | authenticated | unconfigured | offline
export const adminSession = reactive({ status: 'checking', error: '' })

const AUTH_PATHS = new Set(['/api/login', '/api/logout', '/api/session'])

function requestPath(input) {
  const raw = typeof input === 'string' ? input : input?.url ?? String(input)
  const base = globalThis.location?.href ?? 'http://console.invalid/'
  const url = new URL(raw, base)
  const sameOrigin = !globalThis.location || url.origin === globalThis.location.origin
  return sameOrigin ? url.pathname : null
}

async function readJson(response) {
  try { return await response.json() } catch { return {} }
}

export async function refreshSession() {
  try {
    const response = await fetch('/api/session', { cache: 'no-store' })
    const data = (await readJson(response)).data ?? {}
    adminSession.status = !data.configured ? 'unconfigured' : data.authenticated ? 'authenticated' : 'anonymous'
    adminSession.error = ''
  } catch {
    adminSession.status = 'offline'
    adminSession.error = '無法連線到後端，請確認服務已啟動'
  }
  return adminSession.status
}

export async function login(password) {
  adminSession.error = ''
  const response = await fetch('/api/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password })
  })
  const body = await readJson(response)
  if (response.ok) {
    adminSession.status = 'authenticated'
    return true
  }
  if (body.reason === 'admin_unconfigured') adminSession.status = 'unconfigured'
  adminSession.error = body.msg || `登入失敗（HTTP ${response.status}）`
  return false
}

export async function logout() {
  try { await fetch('/api/logout', { method: 'POST' }) } catch { /* The session is dropped locally regardless. */ }
  adminSession.status = 'anonymous'
  adminSession.error = ''
}

// Any console API answering 401 means the admin session ended: show the login screen.
const WRAPPED = Symbol.for('nova.sessionExpiry')

export function installSessionExpiry(target = globalThis) {
  if (target.fetch[WRAPPED]) return
  const original = target.fetch.bind(target)
  const wrapped = async (input, init) => {
    const response = await original(input, init)
    const path = response.status === 401 ? requestPath(input) : null
    if (path !== null && !AUTH_PATHS.has(path) && adminSession.status === 'authenticated') {
      adminSession.status = 'anonymous'
      adminSession.error = '登入已逾時，請重新登入'
    }
    return response
  }
  wrapped[WRAPPED] = true
  target.fetch = wrapped
}
