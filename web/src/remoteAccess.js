// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '0:0:0:0:0:0:0:1'])

export function isLoopbackHost(hostname) {
  if (typeof hostname !== 'string') return false
  let normalized = hostname.trim().toLowerCase()
  if (normalized.startsWith('[') && normalized.endsWith(']')) {
    normalized = normalized.slice(1, -1)
  }
  return LOOPBACK_HOSTS.has(normalized)
}

export function browserHostname() {
  return typeof globalThis.window !== 'undefined'
    ? String(globalThis.window.location?.hostname || '')
    : ''
}

export function ragflowAccessGuide({
  hostname = browserHostname(),
  isLocalClient = true,
  managementUrl = ''
} = {}) {
  const local = isLoopbackHost(hostname) && isLocalClient !== false
  const cleanUrl = typeof managementUrl === 'string' ? managementUrl.trim() : ''
  if (local && cleanUrl) {
    return {
      canOpenDirect: true,
      managementUrl: cleanUrl,
      hint: '',
      tunnelCommand: ''
    }
  }
  const targetHost = (typeof hostname === 'string' && hostname.trim()) || '<jetson-host>'
  return {
    canOpenDirect: false,
    managementUrl: '',
    hint: 'RAGFlow 管理頁僅綁定於主機本機 loopback（127.0.0.1:8088）。從遠端裝置管理知識庫時，請在本機電腦執行 SSH port-forward 後再開啟 http://127.0.0.1:8088：',
    tunnelCommand: `ssh -L 8088:127.0.0.1:8088 <user>@${targetHost}`
  }
}

export function speechPathPickerState({
  hostname = browserHostname(),
  serverAvailable = true
} = {}) {
  const local = isLoopbackHost(hostname) && serverAvailable !== false
  if (local) {
    return { available: true, hint: '' }
  }
  return {
    available: false,
    hint: '遠端連線或無螢幕伺服器不支援本機視窗選檔，請直接輸入伺服器上的檔案或資料夾路徑。'
  }
}
