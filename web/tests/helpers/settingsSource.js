// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// The source of the settings store and the feature modules it composes, for tests that
// assert on what the store sends. Reading every module keeps them independent of which
// file a setting lives in.
import { readdirSync, readFileSync } from 'node:fs'

const src = new URL('../../src/', import.meta.url)

export const settingsSource = [
  'composables/useRuntimeSettings.js',
  ...readdirSync(new URL('settings/', src)).filter(name => name.endsWith('.js')).sort().map(name => `settings/${name}`)
].map(file => readFileSync(new URL(file, src), 'utf8')).join('\n')
