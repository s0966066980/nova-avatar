// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// State and actions of the voice-training workbench. Screens render ``state``
// and call these actions; the server stays the authority for every rule, so
// each action sends a request and shows the answer or its refusal reason.
import { computed, reactive } from 'vue'
import { TrainingApiError, createTrainingApi } from './api.js'
import {
  DECLARATIONS, DEFAULT_WHISPER_MODEL, EDGE_VOICES, EDGE_PRESETS, PREVIEW_SENTENCES, SOURCE_EDGE
} from './constants.js'
import { classifyUploadFile, declarationFor, edgeConfirmGate, nameProblem, newSlug, uploadGate } from './flow.js'
import { announcementFor, emptyLog, isActive, mergeLog, transcriptionView } from './jobView.js'
import { startGate } from './preflight.js'
import {
  cleanSentenceList, confirmableIds, edgeTextRows, removeSentence, replaceSentence
} from './reviewTable.js'
import { previewEdgeText } from './textPreviewClient.js'

const initialState = () => ({
  screen: 'home', path: null, slug: '', name: '', error: '', announcement: null, focusToken: 0,
  // The Microsoft clause as the server delivered it ({reference, effective, text}); null until it has.
  edgeClause: null,
  corpora: [], loadingHome: false, job: null, preflight: null, settings: null, checking: false,
  edge: { voice: EDGE_VOICES[0].id, preset: EDGE_PRESETS[0].key, textSrc: 'builtin', checked: false, acknowledged: false, sentences: [], preview: null, previewing: false, showSample: false },
  up: { declared: '', consent: false, files: [], locked: false, uploading: false },
  tr: { src: 'file', model: DEFAULT_WHISPER_MODEL, imported: null, problems: [], busy: false },
  transcriptionStatus: null,
  corpus: null,
  review: { filter: 'all', page: 0, editingId: null, editError: '', playingId: null },
  confirmCancel: false, cancelling: false, log: emptyLog(),
  preview: { key: '', audio: '', loading: false, error: '' }
})

export function createVoiceTrainingStore({
  api = createTrainingApi(), onModelsChanged = () => {}, sessionExpired = () => false
} = {}) {
  const state = reactive(initialState())

  const message = error => (error instanceof TrainingApiError ? error.message : error?.message || String(error))
  async function guard(action) {
    try { return await action() } catch (error) {
      state.error = message(error)
      return undefined
    }
  }

  // ---------------------------------------------------------------- navigation
  function go(screen) {
    state.screen = screen
    state.error = ''
    state.focusToken += 1
    // The clause is the server's: fetch it whenever the confirmation is shown.
    if (screen === 'edge-confirm') loadEdgeClause()
  }
  function reset() {
    releasePreview()
    Object.assign(state, initialState(), { corpora: state.corpora, job: state.job })
  }
  function newCorpus() { reset(); go('source') }
  function chooseSource(path) {
    if (state.slug) return
    state.path = path
  }

  // ---------------------------------------------------------------- home
  async function refreshHome() {
    state.loadingHome = true
    await guard(async () => {
      const [list, training] = await Promise.all([api.listCorpora(), api.getTraining()])
      state.corpora = list?.corpora || []
      state.job = training?.job || null
    })
    state.loadingHome = false
  }

  async function loadCorpus() {
    if (!state.slug) return
    await guard(async () => { state.corpus = await api.getCorpus(state.slug) })
  }

  async function openCorpus(slug) {
    await guard(async () => {
      const corpus = await api.getCorpus(slug)
      reset()
      state.slug = slug
      state.corpus = corpus
      if (corpus.source === SOURCE_EDGE) {
        state.path = 'edge'
        state.edge.checked = true
        go('text')
      } else {
        state.path = 'upload'
        const declaration = DECLARATIONS.find(item => item.source === corpus.source)
        state.up.declared = declaration?.key || ''
        state.up.locked = true
        go('review')
      }
    })
  }

  // ---------------------------------------------------------------- edge
  async function ensureCorpus(request) {
    if (state.slug) return
    const slug = newSlug(request.source === SOURCE_EDGE ? 'edge' : 'upload')
    const created = await api.createCorpus({ slug, ...request })
    state.slug = created?.slug || slug
  }

  // The clause text only ever comes from the server (settings.edge_clause).
  const clauseOf = value => (value && typeof value.text === 'string' && value.text && typeof value.reference === 'string' ? value : null)
  async function loadEdgeClause() {
    await guard(async () => {
      const data = await api.getTraining()
      state.edgeClause = clauseOf(data?.settings?.edge_clause)
    })
  }

  async function confirmEdge() {
    const clause = state.edgeClause
    if (edgeConfirmGate({ checked: state.edge.checked, sessionExpired: sessionExpired(), clauseReady: Boolean(clause) }).length) return
    try {
      await ensureCorpus({ source: SOURCE_EDGE })
      if (!state.edge.acknowledged) {
        // Send back exactly the text the server delivered and the screen showed.
        await api.recordAcknowledgement(state.slug, clause.text)
        state.edge.acknowledged = true
      }
      go('text')
    } catch (error) {
      state.error = message(error)
      // The server's clause is not the one shown (it was reworded): show the current one and ask again.
      if (error instanceof TrainingApiError && error.status === 400) {
        state.edge.checked = false
        await loadEdgeClause()
        state.error = message(error)
      }
    }
  }

  async function refreshEdgePreview() {
    if (!state.edge.sentences.length) { state.edge.preview = null; return }
    state.edge.previewing = true
    await guard(async () => { state.edge.preview = await previewEdgeText(api, state.edge.sentences) })
    state.edge.previewing = false
  }
  async function loadEdgeTextFile(file) {
    const raw = await file.text()
    state.edge.sentences = cleanSentenceList(raw)
    await refreshEdgePreview()
  }
  async function editEdgeSentence(position, text) {
    state.edge.sentences = replaceSentence(state.edge.sentences, position, text)
    await refreshEdgePreview()
  }
  async function removeEdgeSentence(position) {
    state.edge.sentences = removeSentence(state.edge.sentences, position)
    await refreshEdgePreview()
  }
  function clearEdgeText() { state.edge.sentences = []; state.edge.preview = null }

  // ---------------------------------------------------------------- upload
  function selectDeclaration(key) {
    if (state.up.locked || state.up.declared === key) return
    state.up.declared = key
    state.up.consent = false
  }

  async function addUploadFiles(files) {
    const declaration = declarationFor(state.up.declared)
    if (!declaration || (declaration.needsConsent && !state.up.consent)) return
    state.up.uploading = true
    await guard(async () => {
      await ensureCorpus({ source: declaration.source, consent: declaration.needsConsent })
      state.up.locked = true
      for (const file of files) {
        const known = state.up.files.filter(item => item.status === 'accepted').map(item => item.name)
        const problem = classifyUploadFile(file, known)
        if (problem) { state.up.files.push({ name: file.name, status: 'rejected', ...problem }); continue }
        try {
          const result = await api.uploadLine(state.slug, file)
          state.up.files.push({ name: file.name, status: 'accepted', duration: result?.duration ?? null })
        } catch (error) {
          state.up.files.push({ name: file.name, status: 'rejected', code: 'server', reason: message(error) })
        }
      }
    })
    state.up.uploading = false
  }
  const acceptedCount = computed(() => state.up.files.filter(f => f.status === 'accepted').length || (state.up.locked ? state.corpus?.lines?.length || 0 : 0))
  const uploadReasons = computed(() => uploadGate({ declared: state.up.declared, consent: state.up.consent, accepted: acceptedCount.value, uploading: state.up.uploading }))

  // ---------------------------------------------------------------- transcripts
  async function importTranscripts(files) {
    state.tr.busy = true
    state.tr.problems = []
    state.tr.imported = null
    try {
      const result = await api.importTranscripts(state.slug, files)
      state.tr.imported = { applied: result?.applied ?? 0, without: result?.without_transcript || [] }
      await loadCorpus()
    } catch (error) {
      state.tr.problems = error instanceof TrainingApiError && error.problems.length ? error.problems : [message(error)]
    }
    state.tr.busy = false
  }

  async function startAutoTranscription() {
    await guard(async () => { state.transcriptionStatus = await api.startTranscription(state.slug, state.tr.model) })
  }
  async function pollTranscription() {
    await guard(async () => {
      const wasRunning = transcription.value.running
      state.transcriptionStatus = await api.getTranscription(state.slug)
      if (wasRunning && !transcription.value.running) await loadCorpus()
    })
  }
  async function cancelAutoTranscription() {
    await guard(async () => { state.transcriptionStatus = await api.cancelTranscription(state.slug) })
  }
  const transcription = computed(() => transcriptionView(state.transcriptionStatus))
  const transcriptionShouldPoll = computed(() => transcription.value.running)

  // ---------------------------------------------------------------- review
  const replaceLine = line => {
    const lines = state.corpus?.lines
    const index = lines ? lines.findIndex(item => item.id === line.id) : -1
    if (index >= 0) lines[index] = line
  }
  async function setReview(id, review) {
    return guard(async () => {
      const result = await api.editLine(state.slug, id, { review })
      replaceLine(result.line)
      return result.line
    })
  }
  const confirmRow = id => setReview(id, 'confirmed')
  const excludeRow = id => setReview(id, 'excluded')
  const restoreRow = id => setReview(id, 'pending')

  function startEdit(id) { state.review.editingId = id; state.review.editError = '' }
  function cancelEdit() { state.review.editingId = null; state.review.editError = '' }
  async function saveEdit(id, text) {
    const value = String(text).trim()
    if (!value) { state.review.editError = 'empty'; return }
    await guard(async () => {
      const result = await api.editLine(state.slug, id, { text: value })
      replaceLine(result.line)
      state.review.editingId = null
      state.review.editError = ''
      // A saved line with nothing left to resolve is confirmed in the same step.
      if (!result.line.unresolved?.length) {
        const confirmed = await api.editLine(state.slug, id, { review: 'confirmed' })
        replaceLine(confirmed.line)
      }
    })
  }
  async function confirmAllPending() {
    const ids = confirmableIds(state.corpus?.lines || [])
    if (!ids.length) return 0
    await guard(async () => {
      await api.confirmLines(state.slug, ids)
      await loadCorpus()
      state.announcement = { code: 'confirmed', count: ids.length }
    })
    return ids.length
  }
  function togglePlay(id) { state.review.playingId = state.review.playingId === id ? null : id }
  const audioUrl = id => api.lineAudioUrl(state.slug, id)

  const edgeReview = computed(() => edgeTextRows(state.edge.preview))

  // ---------------------------------------------------------------- preflight and job
  const gate = computed(() => startGate(state.preflight, nameProblem(state.name)))

  async function loadPreflight() {
    state.checking = true
    await guard(async () => {
      const data = await api.getTraining({ corpus: state.slug, name: state.name.trim() })
      state.preflight = data?.preflight || null
      state.settings = data?.settings || null
      if (data?.job) state.job = data.job
    })
    state.checking = false
  }

  function startBody() {
    const body = { corpus: state.slug, name: state.name.trim() }
    if (state.path === 'edge') {
      body.voice = state.edge.voice
      if (state.edge.textSrc === 'file') body.sentences = state.edge.sentences.join('\n')
      else body.preset = state.edge.preset
    }
    return body
  }

  async function startTraining() {
    if (nameProblem(state.name)) return
    try {
      const job = await api.startTraining(startBody())
      state.job = job
      state.log = emptyLog()
      state.confirmCancel = false
      go('job')
      state.announcement = announcementFor(null, job)
      await pollJob()
    } catch (error) {
      if (error instanceof TrainingApiError && error.preflight) state.preflight = error.preflight
      state.error = message(error)
      // Unresolved digits are a text problem: go back to the sentence table that marks them.
      if (error instanceof TrainingApiError && error.unresolved.length) {
        await refreshEdgePreview()
        go('review')
        state.error = message(error)
      }
    }
  }

  async function pollJob() {
    await guard(async () => {
      const previous = state.job ? { status: state.job.status, stage: state.job.stage } : null
      const [training, log] = await Promise.all([api.getTraining(), api.getTrainingLog(state.log.next)])
      state.job = training?.job || state.job
      if (log) state.log = mergeLog(state.log, log)
      const announcement = announcementFor(previous, state.job)
      if (announcement) state.announcement = announcement
      if (previous?.status !== 'done' && state.job?.status === 'done') onModelsChanged()
    })
  }
  const shouldPoll = computed(() => isActive(state.job))

  function askCancel() { if (isActive(state.job)) state.confirmCancel = true }
  function keepTraining() { state.confirmCancel = false }
  async function confirmCancelJob() {
    state.confirmCancel = false
    await guard(async () => {
      const job = await api.cancelTraining()
      if (job) state.job = job
      state.announcement = { code: 'cancelling' }
    })
  }

  // ---------------------------------------------------------------- done: preset preview
  // The server speaks the three preset sentences (by code) in the finished voice model's voice.
  const previewAvailable = key => Boolean(state.job?.voice_id) && PREVIEW_SENTENCES.some(item => item.key === key)
  const releasePreview = () => { if (state.preview.audio) URL.revokeObjectURL(state.preview.audio) }
  async function previewVoice(key) {
    const voiceId = state.job?.voice_id
    if (!voiceId || !previewAvailable(key)) return
    releasePreview()
    state.preview = { key, audio: '', loading: true, error: '' }
    try {
      const wav = await api.previewVoice(voiceId, key)
      state.preview = { key, audio: URL.createObjectURL(wav), loading: false, error: '' }
    } catch (error) {
      state.preview = { key, audio: '', loading: false, error: message(error) }
    }
  }

  // Derived values are plain getters, so a component reads ``store.gate`` whether or not Vue unwraps refs for it.
  return {
    state, go, reset, newCorpus, chooseSource, refreshHome, loadCorpus, openCorpus,
    loadEdgeClause, confirmEdge, loadEdgeTextFile, editEdgeSentence, removeEdgeSentence, clearEdgeText, refreshEdgePreview,
    selectDeclaration, addUploadFiles,
    importTranscripts, startAutoTranscription, pollTranscription, cancelAutoTranscription,
    confirmRow, excludeRow, restoreRow, startEdit, cancelEdit, saveEdit, confirmAllPending, togglePlay, audioUrl,
    loadPreflight, startTraining, pollJob, askCancel, keepTraining, confirmCancelJob,
    previewAvailable, previewVoice,
    get edgeClause() { return state.edgeClause },
    get edgeReview() { return edgeReview.value },
    get acceptedCount() { return acceptedCount.value },
    get uploadReasons() { return uploadReasons.value },
    get transcription() { return transcription.value },
    get transcriptionShouldPoll() { return transcriptionShouldPoll.value },
    get gate() { return gate.value },
    get shouldPoll() { return shouldPoll.value }
  }
}
