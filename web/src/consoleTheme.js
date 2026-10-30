// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// The console's colour theme. Colours live in console-prototype.css as tokens:
// light is the base set, dark applies when <html data-theme="dark"> or, with
// no data-theme, when the system prefers dark. "system" therefore removes the
// attribute instead of resolving it once, so the console follows later
// operating-system changes without a reload.
import { LEGACY_STORAGE_KEYS, STORAGE_KEYS } from './storageKeys.js'

export const THEME_PREFERENCES = Object.freeze(['system', 'light', 'dark'])

const LEGACY_VALUES = Object.freeze({
  obsidian: 'dark', dark: 'dark',
  bento: 'light', white: 'light', light: 'light',
  system: 'system', auto: 'system'
})

export function normalizeThemePreference(value) {
  return LEGACY_VALUES[value] || 'system'
}

export function applyThemePreference(preference, root = globalThis.document?.documentElement) {
  const value = normalizeThemePreference(preference)
  if (!root) return value
  if (value === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', value)
  root.setAttribute('data-theme-preference', value)
  return value
}

// Before this setting existed the console stored a "design sample"
// (obsidian or bento); keep honouring it until the theme key is written.
export function readThemePreference(storage) {
  try {
    const stored = storage.getItem(STORAGE_KEYS.theme)
      ?? storage.getItem(STORAGE_KEYS.designSample)
      ?? storage.getItem(LEGACY_STORAGE_KEYS.designSample)
    return normalizeThemePreference(stored)
  } catch {
    return 'system'
  }
}

export function saveThemePreference(storage, preference) {
  const value = normalizeThemePreference(preference)
  try {
    storage.setItem(STORAGE_KEYS.theme, value)
  } catch {
    // Private windows or blocked storage: the theme still applies this session.
  }
  return value
}
