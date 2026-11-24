// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// The only caller of POST /api/tts/training/text-preview (ticket 13). The exact
// response shape is still being finalised on the server, so it is normalised
// here: if a field name changes, this file is the only fix.
//
// Request  {sentences: "<one sentence per line>"}
// Response {ok, total, unresolved_count, estimated_seconds,
//           sentences: [{index (1-based, in the cleaned list), text, spoken, unresolved: [{text, start, end, reason}]}]}

export const TEXT_PREVIEW_PATH = '/api/tts/training/text-preview'

function normalizeItem(raw, position) {
  const text = String(raw?.text ?? '')
  const unresolved = (Array.isArray(raw?.unresolved) ? raw.unresolved : []).map(part => ({
    text: String(part?.text ?? ''),
    start: Number.isInteger(part?.start) ? part.start : null,
    end: Number.isInteger(part?.end) ? part.end : null,
    reason: String(part?.reason ?? '')
  }))
  return {
    index: Number.isInteger(raw?.index) ? raw.index : position + 1,
    text,
    spoken: typeof raw?.spoken === 'string' ? raw.spoken : text,
    unresolved
  }
}

// ``api`` is createTrainingApi() (anything with ``post``); ``sentences`` is an array of strings.
export async function previewEdgeText(api, sentences) {
  const data = await api.post(TEXT_PREVIEW_PATH, { sentences: sentences.join('\n') })
  const items = (Array.isArray(data?.sentences) ? data.sentences : Array.isArray(data?.items) ? data.items : []).map(normalizeItem)
  const clean = items.every(item => !item.unresolved.length)
  return {
    ok: typeof data?.ok === 'boolean' ? data.ok && clean : clean,
    total: Number.isInteger(data?.total) ? data.total : items.length,
    estimatedSeconds: Number.isFinite(data?.estimated_seconds) ? data.estimated_seconds : null,
    items
  }
}
