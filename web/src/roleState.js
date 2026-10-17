// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export function canRoleInput(role, presenter) {
  if (role?.applying) return false
  return !role?.enabled || (!role.applying && ['ready', 'announcement'].includes(role.phase)
    && (role.mode === 'visitor' ? presenter === 'stage' : presenter === 'console'))
}

export function canRoleReturn(role) {
  return Boolean(role?.enabled && role.can_return && role.phase === 'ready' && !role.applying)
}

export function rolePhaseLabel(phase) {
  return { ready: '就緒', announcement: '交接說明中', transition: '角色轉場中',
    disabled: '單角色模式' }[phase] || '準備中'
}

export function directedTransition(library, source, target) {
  const found = library.transitions.find(e => e.source === source && e.target === target)
  if (found) return found
  const edge = { source, target, kind: 'effect', effect: 'fade', duration: 0.6, asset_id: '' }
  library.transitions.push(edge)
  return edge
}
