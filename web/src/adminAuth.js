// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

/**
 * Client helpers for Nova Avatar single-admin cookie authentication.
 */

export async function fetchAdminAuthStatus(fetchImpl = globalThis.fetch) {
  try {
    const response = await fetchImpl('/api/admin/status', {
      cache: 'no-store',
      credentials: 'same-origin'
    })
    if (!response.ok) {
      return { ok: false, auth_enabled: true, authenticated: false }
    }
    const payload = await response.json().catch(() => ({}))
    const data = payload?.data || {}
    return {
      ok: true,
      auth_enabled: Boolean(data.auth_enabled),
      authenticated: Boolean(data.authenticated)
    }
  } catch {
    return { ok: false, auth_enabled: true, authenticated: false }
  }
}

export async function loginAdmin(password, fetchImpl = globalThis.fetch) {
  const response = await fetchImpl('/api/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ password })
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload?.code === -1) {
    return {
      ok: false,
      status: response.status,
      message: payload?.msg || `HTTP ${response.status}`,
      retryAfter: typeof payload?.retry_after === 'number' ? payload.retry_after : null
    }
  }
  const data = payload?.data || {}
  return {
    ok: true,
    auth_enabled: Boolean(data.auth_enabled),
    authenticated: Boolean(data.authenticated)
  }
}

export async function logoutAdmin(fetchImpl = globalThis.fetch) {
  const response = await fetchImpl('/api/admin/logout', {
    method: 'POST',
    credentials: 'same-origin'
  })
  const payload = await response.json().catch(() => ({}))
  const data = payload?.data || {}
  return {
    auth_enabled: Boolean(data.auth_enabled),
    authenticated: Boolean(data.authenticated)
  }
}
