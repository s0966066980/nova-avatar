// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

import {
  isLoopbackHost,
  ragflowAccessGuide,
  speechPathPickerState
} from '../src/remoteAccess.js'

const rag = readFileSync(new URL('../src/components/RagFlowSettings.vue', import.meta.url), 'utf8')
const panel = readFileSync(new URL('../src/components/SettingsPanel.vue', import.meta.url), 'utf8')
const speechFieldUrl = new URL('../src/components/SpeechPathField.vue', import.meta.url)

test('isLoopbackHost accurately distinguishes loopback vs LAN and Tailscale hosts', () => {
  assert.equal(isLoopbackHost('localhost'), true)
  assert.equal(isLoopbackHost('LOCALHOST'), true)
  assert.equal(isLoopbackHost('127.0.0.1'), true)
  assert.equal(isLoopbackHost('::1'), true)
  assert.equal(isLoopbackHost('[::1]'), true)
  assert.equal(isLoopbackHost('192.168.1.50'), false)
  assert.equal(isLoopbackHost('100.88.1.2'), false)
  assert.equal(isLoopbackHost('orin.local'), false)
  assert.equal(isLoopbackHost('orin.tailnet.ts.net'), false)
  assert.equal(isLoopbackHost(''), false)
})

test('ragflowAccessGuide suppresses dead 127.0.0.1 link on remote hosts and shows SSH port-forward', () => {
  const local = ragflowAccessGuide({
    hostname: '127.0.0.1',
    isLocalClient: true,
    managementUrl: 'http://127.0.0.1:8088'
  })
  assert.equal(local.canOpenDirect, true)
  assert.equal(local.managementUrl, 'http://127.0.0.1:8088')

  const remote = ragflowAccessGuide({
    hostname: '192.168.1.50',
    isLocalClient: false,
    managementUrl: null
  })
  assert.equal(remote.canOpenDirect, false)
  assert.equal(remote.managementUrl, '')
  assert.match(remote.tunnelCommand, /ssh -L 8088:127\.0\.0\.1:8088 .*192\.168\.1\.50/)
  assert.match(remote.hint, /SSH|本機/)

  const proxiedRemote = ragflowAccessGuide({
    hostname: 'orin.local',
    isLocalClient: true,
    managementUrl: 'http://127.0.0.1:8088'
  })
  assert.equal(proxiedRemote.canOpenDirect, false)
  assert.match(proxiedRemote.tunnelCommand, /orin\.local/)
})

test('speechPathPickerState disables native picker on remote or headless hosts', () => {
  assert.deepEqual(
    speechPathPickerState({ hostname: 'localhost', serverAvailable: true }),
    { available: true, hint: '' }
  )
  const remote = speechPathPickerState({ hostname: '192.168.1.50', serverAvailable: true })
  assert.equal(remote.available, false)
  assert.match(remote.hint, /伺服器.*路徑/)

  const headless = speechPathPickerState({ hostname: '127.0.0.1', serverAvailable: false })
  assert.equal(headless.available, false)
  assert.match(headless.hint, /伺服器.*路徑/)
})

test('RagFlowSettings and SettingsPanel wire remote access guards cleanly', () => {
  assert.match(rag, /ragflowAccessGuide/)
  assert.match(rag, /v-if="ragflowAccess\.canOpenDirect"/)
  assert.match(rag, /ragflowAccess\.tunnelCommand/)
  assert.doesNotMatch(rag, /ref\('http:\/\/127\.0\.0\.1:8088'\)/)

  assert.equal(existsSync(speechFieldUrl), true, 'SpeechPathField.vue should deduplicate picker + hint markup')
  const speechField = readFileSync(speechFieldUrl, 'utf8')
  assert.match(speechField, /v-if="pickerState\.available"/)
  assert.match(speechField, /pickerState\.hint/)

  assert.match(panel, /speechPathPickerState/)
  assert.equal((panel.match(/<SpeechPathField\b/g) || []).length, 1)
  assert.doesNotMatch(panel, /pathPickerState\.hint/)
  assert.match(panel, /id="stt-custom-path-toggle"/)
  assert.match(panel, /useCustomSttPath/)
  assert.match(panel, /v-model\.trim="sttDraft\.model_size"/)
})
