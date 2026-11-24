// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Client of the admin-only voice-training routes (tickets 05, 06, 12). Every
// route answers {code, msg, data}; errors carry the Traditional Chinese reason.
// No download or export call exists: the first version has no such route.

export class TrainingApiError extends Error {
  constructor(message, { status = 0, problems = [], preflight = null, unresolved = [] } = {}) {
    super(message)
    this.name = 'TrainingApiError'
    this.status = status
    this.problems = problems
    this.preflight = preflight
    // Start refused for digits no one can read aloud: [{index, text, reason}], index = position in the cleaned list.
    this.unresolved = unresolved
  }
}

const CORPORA = '/api/tts/corpora'
const TRAINING = '/api/tts/training'
const corpusPath = slug => `${CORPORA}/${encodeURIComponent(slug)}`

async function readBody(response) {
  try { return await response.json() } catch { return null }
}

// ``fetchImpl`` defaults to the page's fetch at call time, so the console's
// session-expiry wrapper (adminSession.js) sees every request.
export function createTrainingApi(fetchImpl = (...args) => globalThis.fetch(...args)) {
  async function request(method, url, { json, form } = {}) {
    const init = { method }
    if (json !== undefined) {
      init.headers = { 'Content-Type': 'application/json' }
      init.body = JSON.stringify(json)
    } else if (form) init.body = form
    const response = await fetchImpl(url, init)
    const body = await readBody(response)
    if (!response.ok || !body || body.code !== 0) {
      throw new TrainingApiError(body?.msg || `HTTP ${response.status}`, {
        status: response.status,
        problems: Array.isArray(body?.problems) ? body.problems : [],
        preflight: body?.preflight || body?.data?.preflight || null,
        unresolved: Array.isArray(body?.unresolved) ? body.unresolved : []
      })
    }
    return body.data
  }
  const get = url => request('GET', url)
  const post = (url, json) => request('POST', url, { json })

  // The one route that answers audio instead of {code, msg, data}: a preset sentence
  // spoken by a finished voice model. Resolves to the WAV as a Blob (never a download).
  async function previewVoice(voiceId, sentence) {
    const response = await fetchImpl(`${TRAINING}/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voice_id: voiceId, sentence })
    })
    if (!response.ok) {
      const body = await readBody(response)
      throw new TrainingApiError(body?.msg || `HTTP ${response.status}`, { status: response.status })
    }
    return response.blob()
  }

  return {
    get,
    post,
    listCorpora: () => get(CORPORA),
    getCorpus: slug => get(corpusPath(slug)),
    createCorpus: body => post(CORPORA, body),
    // Edge only: records the confirmation and the clause text that was shown
    // (exactly the text the server delivered as settings.edge_clause). The server also
    // requires `confirmed: true`, which the caller passes only once the box is ticked.
    recordAcknowledgement: (slug, shownText, confirmed) =>
      post(`${corpusPath(slug)}/acknowledgement`, { shown_text: shownText, confirmed: confirmed === true }),
    uploadLine(slug, file, filename = file.name) {
      const form = new FormData()
      form.append('audio', file, filename)
      return request('POST', `${corpusPath(slug)}/lines`, { form })
    },
    editLine: (slug, lineId, changes) => request('PUT', `${corpusPath(slug)}/lines/${encodeURIComponent(lineId)}`, { json: changes }),
    lineAudioUrl: (slug, lineId) => `${corpusPath(slug)}/lines/${encodeURIComponent(lineId)}/audio`,
    importTranscripts(slug, files) {
      const form = new FormData()
      for (const file of files) form.append('files', file, file.name)
      return request('POST', `${corpusPath(slug)}/transcripts`, { form })
    },
    confirmLines: (slug, lineIds) => post(`${corpusPath(slug)}/confirm`, lineIds ? { line_ids: lineIds } : {}),
    startTranscription: (slug, model) => post(`${corpusPath(slug)}/transcription`, model ? { model } : {}),
    getTranscription: slug => get(`${corpusPath(slug)}/transcription`),
    cancelTranscription: slug => request('DELETE', `${corpusPath(slug)}/transcription`),
    getTraining({ corpus, name } = {}) {
      const query = new URLSearchParams()
      if (corpus) query.set('corpus', corpus)
      if (name) query.set('name', name)
      const text = query.toString()
      return get(text ? `${TRAINING}?${text}` : TRAINING)
    },
    startTraining: body => post(`${TRAINING}/start`, body),
    cancelTraining: () => post(`${TRAINING}/cancel`),
    getTrainingLog: offset => get(`${TRAINING}/log?offset=${Math.max(0, Number(offset) || 0)}`),
    previewVoice
  }
}
