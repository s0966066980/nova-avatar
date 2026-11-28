import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { shouldFadeStageReply } from '../src/stage/stageReplyLifecycle.js'

const stageHtml = readFileSync(new URL('../stage.html', import.meta.url), 'utf8')

test('片段播放結束不會在整輪回答完成前淡出字幕', () => {
  assert.equal(shouldFadeStageReply('assistant_fragment_end'), false)
})

test('整輪語音播放結束後才淡出字幕', () => {
  assert.equal(shouldFadeStageReply('speaking_end'), true)
})

test('獨立舞台把整輪淡出策略接到事件處理器', () => {
  const fragmentEndHandler = stageHtml.match(
    /if\(ev\.type === 'assistant_fragment_end'\)\{([\s\S]*?)\n\s*\}/
  )
  assert.ok(fragmentEndHandler)
  assert.doesNotMatch(fragmentEndHandler[1], /fadeReply/)
  assert.match(
    stageHtml,
    /if\(ev\.type === 'speaking_end'\)\{[\s\S]*?shouldFadeStageReply\(ev\.type\)[\s\S]*?fadeReply/
  )
})
