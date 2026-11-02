// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import { ref, reactive } from 'vue'

const roleRuntime = reactive({ enabled: false, phase: 'disabled' })
const libraryRuntime = reactive({ enabled: false, phase: 'disabled' })
const roleLibrary = ref(null)
// Profile id -> reasons it cannot join the saved main avatar's composition.
const roleCompatibility = ref({})

// A failed request keeps the server's JSON (field, conflict, reasons, …) on the error.
export class RoleRequestError extends Error {
  constructor(message, status, data) {
    super(message)
    this.status = status
    this.data = data || {}
  }
}

export function useRoles() {
  async function request(path = '', method = 'GET', body) {
    const response = await fetch('/api/profiles' + path, {
      method, ...(body instanceof FormData ? {body} : body ? {headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)} : {})
    })
    const data = await response.json()
    if (!response.ok || data.code !== 0) throw new RoleRequestError(data.msg || '角色操作失敗', response.status, data)
    if (data.runtime) Object.assign(data.runtime.sessionid ? roleRuntime : libraryRuntime, data.runtime)
    if (data.compatibility) roleCompatibility.value = data.compatibility
    if (data.library) roleLibrary.value = data.library
    return data
  }
  function event(message) {
    if (message.type === 'role_state') Object.assign(roleRuntime, message)
  }
  return { roleRuntime, libraryRuntime, roleLibrary, roleCompatibility, roleRequest: request, roleEvent: event }
}
