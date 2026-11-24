// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Pure rules of the training flow: steps, usage-label derivation, the gates of
// each "next" button (reason codes, translated by the screens) and file checks.
import {
  AUDIO_EXTENSIONS, DECLARATIONS, MAX_NAME_CHARS, MAX_UPLOAD_MB, SOURCE_DEV, SOURCE_EDGE, SOURCE_SELF, SOURCE_WRITTEN,
  USAGE_DEV, USAGE_LABELS, USAGE_RESEARCH
} from './constants.js'

// The label of a model trained on ``source`` from the Research / Non-commercial base model: the strictest wins.
const SOURCE_USAGE = {
  [SOURCE_EDGE]: USAGE_DEV,
  [SOURCE_DEV]: USAGE_DEV,
  [SOURCE_SELF]: USAGE_RESEARCH,
  [SOURCE_WRITTEN]: USAGE_RESEARCH
}
const BASE_USAGE = USAGE_RESEARCH
const strictest = (...labels) => labels.reduce((a, b) => (USAGE_LABELS.indexOf(a) <= USAGE_LABELS.indexOf(b) ? a : b))

export function usageLabelFor(source) {
  return strictest(BASE_USAGE, SOURCE_USAGE[source] || USAGE_DEV)
}

export function labelDerivation(source) {
  const corpus = SOURCE_USAGE[source] || USAGE_DEV
  return { corpus, base: BASE_USAGE, result: strictest(BASE_USAGE, corpus), noExport: source === SOURCE_EDGE }
}

export function declarationFor(key) {
  return DECLARATIONS.find(item => item.key === key) || null
}

// The six steps of the stepper; the second one is named after what the path needs.
export function stepList(path) {
  return [
    { id: 'source', labelKey: 'source' },
    { id: 'text', labelKey: path === 'edge' ? 'readingText' : 'transcripts' },
    { id: 'review', labelKey: 'review' },
    { id: 'preflight', labelKey: 'preflight' },
    { id: 'job', labelKey: 'training' },
    { id: 'done', labelKey: 'done' }
  ]
}

export const sourceGate = path => (path ? [] : ['pick_source'])

export function uploadGate({ declared, consent, accepted, uploading = false }) {
  const reasons = []
  const declaration = declarationFor(declared)
  if (!declaration) reasons.push('declare')
  else if (declaration.needsConsent && !consent) reasons.push('consent')
  if (!accepted) reasons.push('files')
  if (uploading) reasons.push('uploading')
  return reasons
}

// ``clauseReady``: the server has delivered the clause text; without it there is nothing to confirm.
export function edgeConfirmGate({ checked, sessionExpired, clauseReady = false }) {
  if (sessionExpired) return ['session']
  if (!clauseReady) return ['clause']
  return checked ? [] : ['check']
}

export function nameProblem(name) {
  const text = String(name ?? '').trim()
  if (!text) return 'required'
  return [...text].length > MAX_NAME_CHARS ? 'too_long' : null
}

// A slug the server accepts (VOICE_MODEL_ID); it also names the corpus folder, so it is made here only as a request.
export function newSlug(prefix, now = new Date()) {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15)
  const random = Math.floor(Math.random() * 0x10000).toString(16).padStart(4, '0')
  return `${prefix}-${stamp}-${random}`
}

// Early, cheap checks; the server decodes and validates again.
export function classifyUploadFile(file, existingNames) {
  const dot = file.name.lastIndexOf('.')
  const extension = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (!AUDIO_EXTENSIONS.includes(extension)) return { code: 'format', detail: extension }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return { code: 'size', detail: String(MAX_UPLOAD_MB) }
  if (existingNames.includes(file.name)) return { code: 'duplicate', detail: file.name }
  return null
}
