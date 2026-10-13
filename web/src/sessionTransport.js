// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export function newClientId(role = 'console') {
  const key = `nova-avatar.session-client.${role}`
  try {
    const existing = globalThis.sessionStorage?.getItem(key)
    if (existing) return existing
  } catch (_) { /* Storage can be disabled by browser policy. */ }
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
  try { globalThis.sessionStorage?.setItem(key, id) } catch (_) {}
  return id
}

export async function releaseSession(sessionid, client_id) {
  if (!sessionid) return
  try {
    await fetch('/api/sessions/release', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionid, client_id }), keepalive: true,
      signal: AbortSignal.timeout(5000)
    })
  } catch (_) { /* A reconnect with the same client ID also releases its old slot. */ }
}

export async function avatarIsReady() {
  try {
    const health = await (await fetch('/health')).json()
    return Boolean(health.ready && health.model_ready && !health.switching)
  } catch (_) { return false }
}
