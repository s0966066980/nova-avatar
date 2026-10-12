// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  STAGE_TURN_ERROR_MESSAGE,
  STAGE_UNAVAILABLE_MESSAGE,
  stageErrorMessage
} from '../src/stageErrorMessage.js'

const stageHtml = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')

test('輪次錯誤只給訪客簡短提示，不論後端代碼或例外文字', () => {
  for (const error of [
    'tts_error_before_commit',
    'tts_error_after_commit',
    'playback_error_before_commit',
    'pipeline_error',
    "WSServerHandshakeError: 403, message='Invalid response status'"
  ]) {
    assert.equal(stageErrorMessage({ type: 'state', state: 'error', error }), STAGE_TURN_ERROR_MESSAGE)
  }
})

test('語音會話降級時顯示暫時無法使用，不洩漏準備失敗原因', () => {
  assert.equal(
    stageErrorMessage({ type: 'state', state: 'degraded', error: 'CUDA out of memory' }),
    STAGE_UNAVAILABLE_MESSAGE
  )
})

test('沒有錯誤或不是錯誤狀態時不顯示任何提示', () => {
  assert.equal(stageErrorMessage({ type: 'state', state: 'error' }), null)
  assert.equal(stageErrorMessage({ type: 'state', state: 'listening', error: 'x' }), null)
  assert.equal(stageErrorMessage({ type: 'speaking_start' }), null)
  assert.equal(stageErrorMessage(null), null)
})

test('友善提示文字不含技術用語', () => {
  for (const message of [STAGE_TURN_ERROR_MESSAGE, STAGE_UNAVAILABLE_MESSAGE]) {
    assert.doesNotMatch(message, /error|tts|403|commit|未出聲|移除/i)
  }
})

test('獨立舞台以友善提示取代後端錯誤字串，技術細節只寫瀏覽器主控台', () => {
  assert.match(stageHtml, /import \{ stageErrorMessage \} from '\/src\/stageErrorMessage\.js'/)
  assert.doesNotMatch(stageHtml, /showReply\(String\(ev\.error\)/)
  assert.match(
    stageHtml,
    /const friendly = stageErrorMessage\(ev\);[\s\S]*?console\.warn\([\s\S]*?showReply\(friendly, null\)/
  )
})
