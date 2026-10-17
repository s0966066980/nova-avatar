// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export function normalizeRagSelection(value = {}) {
  return {
    enabled: Boolean(value.enabled),
    dataset_ids: [...(value.dataset_ids || [])],
    document_scope: value.document_scope || (value.document_ids?.length ? 'selected' : 'all'),
    document_ids: [...(value.document_ids || [])]
  }
}

export function toggleDataset(value, id, checked) {
  const next = normalizeRagSelection(value)
  next.dataset_ids = checked ? [...new Set([...next.dataset_ids, id])] : next.dataset_ids.filter(x => x !== id)
  // A removed dataset must never leave ambiguous document assignments behind.
  if (!checked) next.document_ids = []
  return next
}

export function selectionError(value) {
  if (!value.dataset_ids.length) return '請先選擇至少一個知識庫。'
  if (value.document_scope === 'selected' && !value.document_ids.length) return '請選擇至少一份文本，或切換為全部文件。'
  return ''
}

export function ragScopeLabel(value) {
  if (!value.enabled) return '未啟用檢索'
  return value.document_scope === 'selected'
    ? `${value.dataset_ids.length} 個知識庫 · 指定 ${value.document_ids.length} 份文本`
    : `${value.dataset_ids.length} 個知識庫 · 全部文件`
}
