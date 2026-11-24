// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// State of the review table. Lines come from GET /api/tts/corpora/{slug}:
// {id, text, normalized_text, unresolved: [{text, start, end}], review}.
// Every function is pure; the server stays the authority (it refuses to
// confirm a line without text or with unresolved digits).

const hasUnresolved = line => Array.isArray(line.unresolved) && line.unresolved.length > 0
const hasText = line => String(line.text ?? '').trim().length > 0

// pending | confirmed | excluded | unresolved
export function rowState(line) {
  if (line.review === 'excluded') return 'excluded'
  if (hasUnresolved(line)) return 'unresolved'
  return line.review === 'confirmed' ? 'confirmed' : 'pending'
}

export const needsText = line => rowState(line) === 'pending' && !hasText(line)

export function countRows(lines) {
  const counts = { pending: 0, confirmed: 0, excluded: 0, unresolved: 0, total: lines.length }
  for (const line of lines) counts[rowState(line)] += 1
  return counts
}

// What the bulk-confirm button may touch: pending lines that have text.
export const confirmableIds = lines => lines.filter(line => rowState(line) === 'pending' && hasText(line)).map(line => line.id)

export function filterRows(lines, filter) {
  switch (filter) {
    case 'pending': return lines.filter(line => rowState(line) === 'pending')
    case 'attention': return lines.filter(line => rowState(line) === 'unresolved' || needsText(line))
    case 'excluded': return lines.filter(line => rowState(line) === 'excluded')
    default: return lines
  }
}

export function paginate(items, page, perPage) {
  const pages = Math.max(1, Math.ceil(items.length / perPage))
  const current = Math.min(Math.max(0, page), pages - 1)
  return { items: items.slice(current * perPage, (current + 1) * perPage), page: current, pages, total: items.length }
}

// Why "next" is disabled: one entry per cause with its count.
export function reviewGate(lines) {
  const counts = countRows(lines)
  const reasons = []
  if (counts.pending) reasons.push({ code: 'pending', count: counts.pending })
  if (counts.unresolved) reasons.push({ code: 'unresolved', count: counts.unresolved })
  if (!reasons.length && !counts.confirmed) reasons.push({ code: 'none_confirmed', count: 0 })
  return reasons
}

// The text split so the unresolved spans (positions in ``text``) can be underlined.
export function textSegments(text, unresolved) {
  const spans = (unresolved || [])
    .filter(part => Number.isInteger(part.start) && Number.isInteger(part.end) && part.start >= 0 && part.end > part.start && part.end <= text.length)
    .sort((a, b) => a.start - b.start)
  const segments = []
  let cursor = 0
  for (const span of spans) {
    if (span.start < cursor) continue
    if (span.start > cursor) segments.push({ text: text.slice(cursor, span.start), bad: false })
    segments.push({ text: text.slice(span.start, span.end), bad: true })
    cursor = span.end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), bad: false })
  return segments.length ? segments : text ? [{ text, bad: false }] : []
}

// The spoken text split into characters kept from the original and characters
// the digit expansion added (found with a longest-common-subsequence match).
export function expansionSegments(original, spoken) {
  const a = [...original], b = [...spoken]
  const table = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }
  const kept = new Array(b.length).fill(false)
  for (let i = 0, j = 0; i < a.length && j < b.length;) {
    if (a[i] === b[j]) { kept[j] = true; i++; j++ } else if (table[i + 1][j] >= table[i][j + 1]) i++
    else j++
  }
  const segments = []
  b.forEach((char, index) => {
    const expanded = !kept[index]
    const last = segments[segments.length - 1]
    if (last && last.expanded === expanded) last.text += char
    else segments.push({ text: char, expanded })
  })
  return segments
}

// ---- Edge text list, reviewed before synthesis (no audio exists yet) ----

export function cleanSentenceList(raw) {
  const seen = new Set()
  const sentences = []
  for (const row of String(raw).split(/\r?\n/)) {
    const text = row.trim()
    if (text && !seen.has(text)) { seen.add(text); sentences.push(text) }
  }
  return sentences
}

// An empty replacement removes the sentence; a duplicate of another merges into it.
export function replaceSentence(list, position, text) {
  const next = [...list]
  next[position] = String(text).trim()
  return cleanSentenceList(next.join('\n'))
}

export const removeSentence = (list, position) => list.filter((_, index) => index !== position)

// Rows of the pre-synthesis table from the text-preview result.
export function edgeTextRows(preview) {
  const items = preview?.items || []
  const rows = items.map((item, position) => ({
    position,
    text: item.text,
    spoken: item.spoken,
    unresolved: item.unresolved,
    state: item.unresolved.length ? 'unresolved' : 'confirmed'
  }))
  const unresolved = rows.filter(row => row.state === 'unresolved').length
  return {
    rows,
    counts: { confirmed: rows.length - unresolved, unresolved, total: rows.length },
    canContinue: Boolean(preview?.ok) && rows.length > 0 && unresolved === 0
  }
}
