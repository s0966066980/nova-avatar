// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// View rules of the pre-flight checks from GET /api/tts/training:
// preflight = {can_start, checks: [{id, label, status: pass|fail|warn, reason, detail}]}.

const TONES = {
  pass: { tone: 'ok', icon: 'check-circle' },
  fail: { tone: 'bad', icon: 'x-circle' },
  warn: { tone: 'warn', icon: 'alert' }
}

export function checkView(check) {
  const status = TONES[check.status] ? check.status : 'fail'
  return { id: check.id, status, ...TONES[status], reason: check.reason ?? '', detail: check.detail ?? {} }
}

// Whether the start button is enabled, and every reason when it is not. A
// refusal is never hidden: each failing check contributes its server reason.
export function startGate(preflight, nameIssue) {
  if (!preflight) return { canStart: false, reasons: [{ id: 'unchecked', text: '' }], warnings: [] }
  const checks = (preflight.checks || []).map(checkView)
  const reasons = checks.filter(check => check.status === 'fail').map(check => ({ id: check.id, text: check.reason }))
  if (nameIssue && !reasons.some(reason => reason.id === 'model_name')) {
    reasons.push({ id: 'model_name', text: '', code: nameIssue })
  }
  const warnings = checks.filter(check => check.status === 'warn').map(check => ({ id: check.id, text: check.reason }))
  return { canStart: preflight.can_start === true && reasons.length === 0, reasons, warnings }
}

// Position of the free VRAM and of the threshold on a bar; the server gives no
// total, so the scale ends 25% above the larger of the two.
export function vramGauge(check) {
  const free = check?.detail?.free_gb, threshold = check?.detail?.threshold_gb
  if (check?.id !== 'free_vram' || !Number.isFinite(free) || !Number.isFinite(threshold)) return null
  const max = Math.max(free, threshold, 1) * 1.25
  return { free, threshold, max, freePct: (free / max) * 100, thresholdPct: (threshold / max) * 100 }
}
