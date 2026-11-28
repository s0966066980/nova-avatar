import assert from 'node:assert/strict'
import test from 'node:test'

import { applyConsoleBoardEvent, createConsoleBoardState } from '../src/console/consoleBoardState.js'

test('控制台看板依序接收 begin/item 並可清空', () => {
  const board = createConsoleBoardState()

  assert.equal(applyConsoleBoardEvent(board, {
    type: 'board_begin',
    title: '部署步驟'
  }), true)
  assert.equal(applyConsoleBoardEvent(board, {
    type: 'board_item',
    title: '檢查設定',
    body: '確認環境變數。'
  }), true)
  assert.deepEqual(board, {
    title: '部署步驟',
    items: [{ title: '檢查設定', body: '確認環境變數。' }],
    hidden: false
  })

  assert.equal(applyConsoleBoardEvent(board, { type: 'board_clear' }), true)
  assert.deepEqual(board, { title: '', items: [], hidden: false })
})

test('完整看板事件會以最新內容取代舊內容', () => {
  const board = createConsoleBoardState()
  applyConsoleBoardEvent(board, {
    type: 'assistant_board',
    board: {
      title: '核心摘要',
      items: [
        { title: '第一項', content: '新內容' },
        { title: '第二項', body: '補充內容' }
      ]
    }
  })

  assert.deepEqual(board, {
    title: '核心摘要',
    items: [
      { title: '第一項', body: '新內容' },
      { title: '第二項', body: '補充內容' }
    ],
    hidden: false
  })
})
