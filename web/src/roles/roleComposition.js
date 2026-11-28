// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// 當次角色組合 in the console (ADR 0023): one draft per scope (the main
// avatar, each specialist, the transitions), each saved on its own with its
// own revision so a conflict only affects that scope.

export const MAX_ENABLED = 5
export const MAX_MEMBERS = 29
export const HANDOFF_FIELDS = ['description', 'rules', 'announcement', 'announcement_en']
export const EFFECTS = { fade: '淡入淡出', slide_left: '向左滑動', slide_right: '向右滑動', zoom: '縮放' }
export const DEFAULT_TRANSITION = { kind: 'effect', effect: 'fade', duration: 0.6, asset_id: '' }

const clone = value => JSON.parse(JSON.stringify(value))
const pick = (source, keys) => Object.fromEntries(keys.map(key => [key, source?.[key] ?? '']))
const site = value => String(value ?? '').replaceAll('台', '臺')

// What each scope's draft holds; the server assigns every revision.
const fields = {
  main: base => ({ enabled: base.enabled, ...pick(base, HANDOFF_FIELDS) }),
  member: base => ({
    profile_id: base.profile_id, enabled: base.enabled, ...pick(base, HANDOFF_FIELDS),
    tools: { weather: { enabled: Boolean(base.tools?.weather?.enabled), county: base.tools?.weather?.county || '', town: base.tools?.weather?.town || '' } }
  }),
  transitions: base => ({ default: { ...base.default }, overrides: base.overrides.map(edge => ({ ...edge })) })
}

function scope(kind, base) {
  return { kind, base: clone(base), draft: clone(fields[kind](base)), status: 'idle', error: '', field: '', reasons: [], conflict: null, savedAt: '' }
}

const mainBase = composition => ({ ...composition.main, enabled: composition.enabled })

export function scopesFrom(library) {
  const composition = library.composition
  return {
    main: scope('main', mainBase(composition)),
    members: Object.fromEntries(composition.members.map(m => [m.profile_id, scope('member', m)])),
    transitions: scope('transitions', composition.transitions)
  }
}

// A member chosen in an empty seat; disabled until saved and switched on.
export function newMemberScope(profileId, name) {
  const base = { profile_id: profileId, enabled: false, description: '', rules: '',
    announcement: `這題我請${name}來回答。`, announcement_en: '', tools: { weather: { enabled: false, county: '', town: '' } } }
  return { ...scope('member', base), kind: 'new' }
}

// Base a scope on ``current`` (another console's save): its draft is replaced
// unless ``keepDraft``, in which case saving again overwrites that version.
export function rebase(item, current, keepDraft = false) {
  item.base = clone(current)
  if (!keepDraft) item.draft = clone(fields[item.kind](current))
  Object.assign(item, { status: 'idle', error: '', field: '', reasons: [], conflict: null })
  return item
}

export function isDirty(item) {
  if (!item) return false
  if (item.kind === 'new') return true
  return JSON.stringify(item.draft) !== JSON.stringify(fields[item.kind](item.base))
}

// Adopt the server's library: a clean scope takes the new content, a dirty one
// keeps its draft and the revision it was based on, so saving it can still
// detect another console's change. Removed members without a draft disappear.
export function reconcile(scopes, library) {
  const fresh = scopesFrom(library)
  const keep = (old, next) => (old && isDirty(old) ? old : next)
  const members = {}
  for (const [id, next] of Object.entries(fresh.members)) members[id] = keep(scopes.members[id], next)
  for (const [id, old] of Object.entries(scopes.members)) {
    if (!members[id] && isDirty(old)) members[id] = { ...old, missing: true }
  }
  return { main: keep(scopes.main, fresh.main), members, transitions: keep(scopes.transitions, fresh.transitions) }
}

function memberBody(draft) {
  const weather = draft.tools.weather
  return { ...clone(draft), tools: { weather: { ...weather, county: site(weather.county).trim(), town: site(weather.town).trim() } } }
}

// The requests that save one scope, in order; each checks only its own revision.
export function savePlan(item, library) {
  const composition = library.composition
  const draft = item.draft
  if (item.kind === 'new') {
    return [{ path: '/composition/members', method: 'POST', body: { expected_revision: composition.revision, member: memberBody(draft) } }]
  }
  if (item.kind === 'member') {
    const body = { expected_revision: item.base.revision, member: memberBody(draft) }
    if (draft.enabled !== item.base.enabled || draft.profile_id !== item.base.profile_id) {
      body.expected_composition_revision = composition.revision
    }
    return [{ path: `/composition/members/${encodeURIComponent(item.base.profile_id)}`, method: 'PUT', body }]
  }
  if (item.kind === 'transitions') {
    return [{ path: '/composition/transitions', method: 'PUT', body: { expected_revision: item.base.revision, transitions: clone(draft) } }]
  }
  const plan = []
  const text = pick(draft, HANDOFF_FIELDS)
  if (JSON.stringify(text) !== JSON.stringify(pick(item.base, HANDOFF_FIELDS))) {
    plan.push({ path: '/composition/main', method: 'PUT', body: { expected_revision: item.base.revision, main: text } })
  }
  if (draft.enabled !== item.base.enabled) {
    plan.push({ path: '/composition', method: 'PUT', body: { expected_revision: composition.revision, enabled: draft.enabled } })
  }
  return plan
}

export function readFailure(error) {
  const data = error?.data || {}
  return { message: error?.message || '儲存失敗', field: data.field || '', conflict: data.conflict || null,
    reasons: data.reasons || [], disableRequired: data.disable_required || [] }
}

// Members that take part in handoffs: handoff on, enabled and compatible.
export function liveMemberIds(library, compatibility = {}) {
  const composition = library.composition
  if (!composition.enabled) return []
  return composition.members.filter(m => m.enabled && !(compatibility[m.profile_id] || []).length).map(m => m.profile_id)
}

export const enabledCount = library => library.composition.members.filter(m => m.enabled).length

// The member whose saved weather tool is on, enabled or not.
export const weatherHolder = library => library.composition.members.find(m => m.tools?.weather?.enabled)?.profile_id || ''

// Evenly spaced points on a circle, the first at the top, then clockwise.
export function ringLayout(count, { cx, cy, r }) {
  return Array.from({ length: count }, (_, index) => {
    const angle = (-90 + (360 / count) * index) * Math.PI / 180
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle), cos: Math.cos(angle), sin: Math.sin(angle) }
  })
}

// Avatar colours, each at least 4.5:1 against white initials.
const AVATAR_COLORS = ['#3b5bdb', '#0e7d63', '#b0521a', '#7647c2', '#a33a63', '#2f7a99', '#5b6577', '#8a5a00']
export const avatarColor = (profiles, id) => AVATAR_COLORS[Math.max(0, profiles.findIndex(p => p.id === id)) % AVATAR_COLORS.length]
