// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// View rules of the training job (ticket 06) and the automatic transcription
// job (tickets 05, 12): stage rows, log merging by absolute offset, live-region
// announcements.

export const LOG_LIMIT = 2000

const STAGE_LOOK = {
  done: { icon: 'check-circle', tone: 'ok' },
  running: { icon: 'spin', tone: 'run' },
  pending: { icon: 'dot', tone: 'idle' },
  failed: { icon: 'x-circle', tone: 'bad' },
  cancelled: { icon: 'ban', tone: 'idle' }
}

export function stageRows(job) {
  return (job?.stages || []).map(stage => {
    const status = STAGE_LOOK[stage.status] ? stage.status : 'pending'
    return { id: stage.id, label: stage.label, status, ...STAGE_LOOK[status], detail: stage.detail || '', progress: stage.progress || 0, seconds: stage.seconds ?? null }
  })
}

export const jobPercent = job => Math.min(100, Math.max(0, Math.round(Number(job?.progress) || 0)))
export const isActive = job => job?.status === 'running' || job?.status === 'cancelling'

export const emptyLog = () => ({ jobId: null, lines: [], next: 0, gap: false })

// The log route answers {job_id, start, lines, next}: ``lines`` begin at the
// absolute line ``start`` and ``next`` is the offset of the following poll.
export function mergeLog(log, payload) {
  const fresh = log.jobId !== payload.job_id
  const base = fresh ? emptyLog() : log
  const skip = Math.max(0, base.next - payload.start)
  const lines = [...base.lines, ...payload.lines.slice(skip)]
  return {
    jobId: payload.job_id,
    lines: lines.length > LOG_LIMIT ? lines.slice(lines.length - LOG_LIMIT) : lines,
    next: Math.max(base.next, payload.next),
    gap: (!fresh && base.gap) || (!fresh && payload.start > base.next) || (fresh && payload.start > 0)
  }
}

export function logTone(line) {
  if (/Traceback|Error\b|錯誤|失敗且|CUDA out of memory/.test(line)) return 'error'
  if (/失敗|重試|HTTP [45]\d\d|警告|warning/i.test(line)) return 'warn'
  return ''
}

// What the hidden live region says: a stage change or a final state, never each progress tick.
export function announcementFor(previous, job) {
  if (!job) return null
  if (job.status === 'done') return previous?.status === 'done' ? null : { code: 'done' }
  if (job.status === 'failed') return previous?.status === 'failed' ? null : { code: 'failed', error: job.error || '' }
  if (job.status === 'cancelled') return previous?.status === 'cancelled' ? null : { code: 'cancelled' }
  if (job.status === 'cancelling') return previous?.status === 'cancelling' ? null : { code: 'cancelling' }
  return previous?.stage === job.stage && previous?.status === job.status ? null : { code: 'stage', stage: job.stage }
}

// Ticket 12 adds ``device`` and ``fallback_reason`` to the status; either may be missing.
export function transcriptionView(status) {
  const s = status || {}
  const total = Number(s.total) || 0, done = Number(s.done) || 0
  const device = s.device === 'cuda' || s.device === 'cpu' ? s.device : null
  const state = s.state || 'idle'
  return {
    state,
    running: state === 'running',
    finished: state === 'done' || state === 'failed' || state === 'cancelled',
    percent: total ? Math.min(100, Math.round((done / total) * 100)) : 0,
    total,
    done,
    skipped: Number(s.skipped) || 0,
    failed: Array.isArray(s.failed) ? s.failed : [],
    message: s.message || '',
    device,
    fallbackReason: s.fallback_reason || '',
    slowNote: device === 'cpu',
    cancelling: Boolean(s.cancel_requested)
  }
}
