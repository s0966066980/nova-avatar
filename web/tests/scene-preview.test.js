// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { avatarScenePreviewUrl } from '../src/scenePreview.js'

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const panel = readFileSync(new URL('../src/components/SettingsPanel.vue', import.meta.url), 'utf8')
const settings = readFileSync(new URL('../src/composables/useRuntimeSettings.js', import.meta.url), 'utf8')

test('控制台離線畫面與舞台設定預覽都使用合成後的數字人背景', () => {
  assert.match(app, /:src="consoleScenePreviewUrl"/)
  assert.match(panel, /:src="stageScenePreviewUrl"/)
})

test('選定背景時才以合成場景取代綠幕縮圖', () => {
  const avatar = { id: 'musetalk_avatar', green_screen: true, preview_url: '/api/avatars/musetalk_avatar/preview' }
  assert.equal(avatarScenePreviewUrl(avatar, ''), avatar.preview_url)
  assert.equal(avatarScenePreviewUrl(avatar, 'abc123'), '/api/avatars/musetalk_avatar/scene-preview?background_id=abc123')
  assert.equal(avatarScenePreviewUrl({ ...avatar, green_screen: false }, 'abc123'), avatar.preview_url)
})

test('背景卡片可刪除，且本機回收區可復原', () => {
  assert.ok(panel.includes('requestDeleteBackground(item)'))
  assert.ok(panel.includes('handleRestoreBackground(item.archive_name)'))
  assert.ok(settings.includes('method: \'DELETE\''))
  assert.ok(settings.includes('/api/backgrounds/deleted'))
})

test('數字人回收區的復原旁可永久刪除，且需確認', () => {
  assert.match(panel, /handleRestoreAvatar\(item\.archive_name\)[\s\S]*requestPermanentlyDeleteAvatar\(item\)/)
  assert.match(panel, /purge-avatar[\s\S]*無法復原/)
  assert.match(settings, /\/api\/avatars\/deleted\/\$\{encodeURIComponent\(archiveName\)\}[\s\S]*method: 'DELETE'/)
})
