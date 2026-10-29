// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0
import { ref, reactive } from 'vue'

const roleRuntime = reactive({ enabled: false, phase: 'disabled' })
const libraryRuntime = reactive({ enabled: false, phase: 'disabled' })
const roleLibrary = ref(null)
export function useRoles() {
  async function request(path = '', method = 'GET', body) {
    const response = await fetch('/api/profiles' + path, {
      method, ...(body instanceof FormData ? {body} : body ? {headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)} : {})
    })
    const data = await response.json()
    if (!response.ok || data.code !== 0) throw new Error(data.msg || '角色操作失敗')
    if (data.runtime) Object.assign(data.runtime.sessionid ? roleRuntime : libraryRuntime, data.runtime)
    if (data.library) roleLibrary.value = data.library
    return data
  }
  function event(message) {
    if (message.type === 'role_state') Object.assign(roleRuntime, message)
  }
  return { roleRuntime, libraryRuntime, roleLibrary, roleRequest: request, roleEvent: event }
}
