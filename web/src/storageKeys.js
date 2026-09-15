// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export const STORAGE_KEYS = Object.freeze({
  designSample: 'nova-avatar-design-sample',
  editorHeights: 'nova-avatar-editor-heights',
  language: 'nova-avatar-language',
  settings: 'nova-avatar-settings',
  theme: 'nova-avatar-theme'
})

const legacyPrefix = ['linly', 'talker', 'stream'].join('-')

export const LEGACY_STORAGE_KEYS = Object.freeze({
  designSample: ['linly', 'design', 'sample'].join('_'),
  editorHeights: `${legacyPrefix}-editor-heights`,
  language: `${legacyPrefix}-language`,
  settings: `${legacyPrefix}-settings`,
  theme: `${legacyPrefix}-theme`
})

export function readMigratedStorage(storage, key, legacyKey) {
  const current = storage.getItem(key)
  if (current !== null) return current

  const legacy = storage.getItem(legacyKey)
  if (legacy !== null) storage.setItem(key, legacy)
  return legacy
}
