// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import test from 'node:test'

import { LEGACY_STORAGE_KEYS, STORAGE_KEYS, readMigratedStorage } from '../src/storageKeys.js'

function memoryStorage(entries = {}) {
  const values = new Map(Object.entries(entries))
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, value),
    value: (key) => values.get(key)
  }
}

test('uses the Nova Avatar value when both storage generations exist', () => {
  const storage = memoryStorage({
    [STORAGE_KEYS.language]: 'en-US',
    [LEGACY_STORAGE_KEYS.language]: 'zh-TW'
  })

  assert.equal(
    readMigratedStorage(storage, STORAGE_KEYS.language, LEGACY_STORAGE_KEYS.language),
    'en-US'
  )
})

test('migrates a pre-rebrand value to the Nova Avatar key', () => {
  const storage = memoryStorage({ [LEGACY_STORAGE_KEYS.settings]: '{"theme":"dark"}' })

  assert.equal(
    readMigratedStorage(storage, STORAGE_KEYS.settings, LEGACY_STORAGE_KEYS.settings),
    '{"theme":"dark"}'
  )
  assert.equal(storage.value(STORAGE_KEYS.settings), '{"theme":"dark"}')
})
