// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(new URL('../src/components/SettingsPanel.vue', import.meta.url), 'utf8')
const weather = readFileSync(new URL('../src/components/WeatherSettings.vue', import.meta.url), 'utf8')

test('氣象查詢設定卡片整合於知識庫檢索頁籤，支援場域預設地點與測試查詢', () => {
  assert.match(panel, /WeatherSettings/)
  assert.match(weather, /\/api\/weather\/settings/)
  assert.match(weather, /\/api\/weather\/test/)
  assert.match(weather, /weather-default-county/)
  assert.match(weather, /weather-default-town/)
  assert.match(weather, /enabled: draft\.enabled/)
  assert.match(weather, /county: draft\.county/)
  assert.doesNotMatch(weather, /Authorization.*Bearer/)
})
