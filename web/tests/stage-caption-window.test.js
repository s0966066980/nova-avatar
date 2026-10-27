import assert from 'node:assert/strict'
import test from 'node:test'
import {
  MAX_STAGE_CAPTION_MAX_CHARS,
  MIN_STAGE_CAPTION_MAX_CHARS,
  StageCaptionWindow,
  countGraphemes
} from '../src/stageCaptionWindow.js'

test('舞台字幕以使用者感知字元計算', () => {
  assert.equal(countGraphemes('A你🙂́'), 3)
})

test('英文字幕在完整片段之間保留句子空白', () => {
  const window = new StageCaptionWindow(100)
  window.append('Hello.', 'turn')
  window.append('How are you?', 'turn')
  assert.equal(window.text, 'Hello. How are you?')
  assert.equal(window.totalChars, countGraphemes(window.text))
})

test('舞台字幕超限時淘汰最早的完整片段', () => {
  const window = new StageCaptionWindow(4)
  window.append('你好', 'turn-1')
  window.append('世界', 'turn-1')
  const result = window.append('！', 'turn-1')

  assert.deepEqual(result.removed.map((fragment) => fragment.text), ['你好'])
  assert.equal(window.text, '世界！')
  assert.equal(window.totalChars, 3)
})

test('單一片段超過上限時仍保留完整片段', () => {
  const window = new StageCaptionWindow(MIN_STAGE_CAPTION_MAX_CHARS)
  window.append('這是一個超過最小上限的完整語意片段，不能被拆開顯示', 'turn-1')

  assert.equal(window.fragments.length, 1)
  assert.ok(window.totalChars > MIN_STAGE_CAPTION_MAX_CHARS)
})

test('不同輪次不共用字幕片段，取消可清空窗口', () => {
  const window = new StageCaptionWindow(MAX_STAGE_CAPTION_MAX_CHARS)
  window.append('上一輪', 'turn-1')
  window.append('新一輪', 'turn-2')

  assert.equal(window.text, '新一輪')
  window.clear()
  assert.equal(window.text, '')
  assert.equal(window.turnId, null)
})
