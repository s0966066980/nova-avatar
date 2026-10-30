// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  THEME_PREFERENCES,
  applyThemePreference,
  normalizeThemePreference,
  readThemePreference,
  saveThemePreference
} from '../src/consoleTheme.js'
import { LEGACY_STORAGE_KEYS, STORAGE_KEYS } from '../src/storageKeys.js'

function memoryStorage(entries = {}) {
  const values = new Map(Object.entries(entries))
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    value: (key) => values.get(key)
  }
}

function fakeRoot() {
  const attributes = new Map()
  return {
    setAttribute: (name, value) => attributes.set(name, String(value)),
    removeAttribute: (name) => attributes.delete(name),
    getAttribute: (name) => attributes.has(name) ? attributes.get(name) : null
  }
}

test('主題選項為跟隨系統、淺色、深色', () => {
  assert.deepEqual(THEME_PREFERENCES, ['system', 'light', 'dark'])
})

test('舊版主題值對應到新的三個選項，未知值跟隨系統', () => {
  for (const legacy of ['obsidian', 'dark']) assert.equal(normalizeThemePreference(legacy), 'dark')
  for (const legacy of ['bento', 'white', 'light']) assert.equal(normalizeThemePreference(legacy), 'light')
  for (const value of ['system', 'auto', '', null, undefined, 'neon']) assert.equal(normalizeThemePreference(value), 'system')
})

test('跟隨系統時移除 data-theme，讓 prefers-color-scheme 決定配色', () => {
  const root = fakeRoot()
  applyThemePreference('dark', root)
  assert.equal(root.getAttribute('data-theme'), 'dark')
  applyThemePreference('light', root)
  assert.equal(root.getAttribute('data-theme'), 'light')
  applyThemePreference('system', root)
  assert.equal(root.getAttribute('data-theme'), null)
  assert.equal(root.getAttribute('data-theme-preference'), 'system')
})

test('讀取已儲存的主題，沒有時沿用舊版樣式樣本', () => {
  assert.equal(readThemePreference(memoryStorage({ [STORAGE_KEYS.theme]: 'light' })), 'light')
  assert.equal(readThemePreference(memoryStorage({ [STORAGE_KEYS.designSample]: 'bento' })), 'light')
  assert.equal(readThemePreference(memoryStorage({ [LEGACY_STORAGE_KEYS.designSample]: 'obsidian' })), 'dark')
  assert.equal(readThemePreference(memoryStorage()), 'system')
  // 舊版 toggle 曾把 white 寫進主題鍵
  assert.equal(readThemePreference(memoryStorage({ [STORAGE_KEYS.theme]: 'white' })), 'light')
})

test('儲存主題只寫入主題鍵，儲存空間不可用時不拋錯', () => {
  const storage = memoryStorage()
  saveThemePreference(storage, 'obsidian')
  assert.equal(storage.value(STORAGE_KEYS.theme), 'dark')
  const broken = { setItem() { throw new Error('quota') } }
  assert.doesNotThrow(() => saveThemePreference(broken, 'light'))
  assert.equal(readThemePreference({ getItem() { throw new Error('blocked') } }), 'system')
})
