import assert from 'node:assert/strict'
import test from 'node:test'
import {
  applyTurnCommitted,
  isTurnCommitError,
} from '../src/console/consoleTurnCommit.js'

test('輪次提交後控制台改為已播回覆並結束預覽', () => {
  const next = applyTurnCommitted(
    [
      {
        type: 'ai',
        text: '已播放。後面還沒唸。',
        voiceTurnId: 'turn-1',
        streamingPreview: true,
      },
    ],
    {
      type: 'turn_committed',
      turn_id: 'turn-1',
      played_text: '已播放。',
      reason: 'tts_error_after_commit',
    }
  )

  assert.equal(next.length, 1)
  assert.equal(next[0].text, '已播放。')
  assert.equal(next[0].streamingPreview, false)
  assert.equal(next[0].terminalReason, 'tts_error_after_commit')
})

test('沒有已播回覆時刪除該則預覽', () => {
  const next = applyTurnCommitted(
    [
      { type: 'user', text: '你好' },
      {
        type: 'ai',
        text: '模型已經寫完但沒出聲',
        voiceTurnId: 'turn-1',
        streamingPreview: true,
      },
    ],
    {
      type: 'turn_committed',
      turn_id: 'turn-1',
      played_text: '',
      reason: 'tts_error_before_commit',
    }
  )

  assert.deepEqual(next, [{ type: 'user', text: '你好' }])
})

test('成功提交不影響其他輪次，錯誤原因可辨識', () => {
  const next = applyTurnCommitted(
    [
      { type: 'ai', text: '上一輪', voiceTurnId: 'turn-0', streamingPreview: false },
      { type: 'ai', text: '預覽全文', voiceTurnId: 'turn-1', streamingPreview: true },
    ],
    {
      type: 'turn_committed',
      turn_id: 'turn-1',
      played_text: '實際唸出',
      reason: 'completed',
    }
  )

  assert.equal(next[0].text, '上一輪')
  assert.equal(next[1].text, '實際唸出')
  assert.equal(isTurnCommitError('tts_error_before_commit'), true)
  assert.equal(isTurnCommitError('interrupt'), false)
  assert.equal(isTurnCommitError('completed'), false)
})
