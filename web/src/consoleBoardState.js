// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export function createConsoleBoardState() {
  return { title: '', items: [], hidden: false }
}

function normalizeBoardItem(item = {}) {
  return {
    title: String(item.title || ''),
    body: String(item.content || item.body || '')
  }
}

export function applyConsoleBoardEvent(board, event = {}) {
  if (!board || !event || typeof event.type !== 'string') return false

  if (event.type === 'board_clear') {
    board.title = ''
    board.items = []
    board.hidden = false
    return true
  }

  if (event.type === 'assistant_board' && event.board) {
    board.title = String(event.board.title || '')
    board.items = Array.isArray(event.board.items)
      ? event.board.items.map(normalizeBoardItem)
      : []
    board.hidden = false
    return true
  }

  if (event.type === 'board_begin') {
    board.title = String(event.title || '')
    board.items = []
    board.hidden = false
    return true
  }

  if (event.type === 'board_item') {
    board.items.push(normalizeBoardItem(event))
    board.hidden = false
    return true
  }

  return false
}
