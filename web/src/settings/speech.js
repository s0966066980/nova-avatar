// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Speech settings: speech recognition (STT), voice activity detection (VAD) and the
// speech-synthesis catalog a role's voice is chosen from. The store in
// composables/useRuntimeSettings.js composes this with the other settings.

import { computed, reactive, ref, watch } from 'vue'
import { parseJson } from './shared.js'

export const SILERO_ENGINE = {
  id: 'silero',
  label: 'Silero VAD',
  available: true,
  install: 'uv pip install "silero-vad>=5.1"'
}

export const vad = reactive({
  supported: false,
  enabled: true,
  type: 'silero',
  threshold: 0.5,
  aggressiveness: 2,
  min_speech_ms: 250,
  min_silence_ms: 500,
  speech_pad_ms: 150,
  engines: [SILERO_ENGINE],
  asr_mode: 'server',
  effective: false
})

// 面板上正在編輯的值；啟用開關會立刻提交
export const vadDraft = reactive({
  enabled: true,
  type: 'silero',
  threshold: 0.5,
  aggressiveness: 2,
  min_silence_ms: 500,
  asr_mode: 'server'
})

export const speech = reactive({
  stt: {
    type: 'whisper',
    model_size: 'base',
    language: 'zh',
    device: 'auto',
    engines: [],
    model_sizes: ['tiny', 'base', 'small', 'medium', 'large-v3'],
    models_by_engine: {
      whisper: ['tiny', 'base', 'small', 'medium', 'large-v3']
    },
    languages: ['zh', 'en', 'auto'],
    devices: ['auto', 'cpu', 'cuda']
  },
  // Catalogs a role profile's voice is chosen from; the default voice is the
  // main role's, so there is no global voice here.
  tts: {
    engines: [],
    models: [],
    voices: [],
    edge_voices: [],
    edge_english_voices: [],
    // Matcha voice models with their usage labels, listed by the server.
    voice_models: [],
    notice: ''
  }
})

export const sttDraft = reactive({
  type: 'whisper',
  model_size: 'base',
  language: 'zh',
  device: 'auto'
})

export const applyingStt = ref(false)

export const speechError = ref('')

export const voiceLibraryBusy = ref(false)

export const applyingVad = ref(false)

export const comparingVad = ref(false)

export const vadError = ref('')

export const vadCompareError = ref('')

export const vadCompareResult = ref(null)

export const vadDirty = computed(() => {
  return (
    vadDraft.enabled !== vad.enabled ||
    vadDraft.type !== vad.type ||
    Number(vadDraft.threshold) !== Number(vad.threshold) ||
    Number(vadDraft.aggressiveness) !== Number(vad.aggressiveness) ||
    Number(vadDraft.min_silence_ms) !== Number(vad.min_silence_ms) ||
    vadDraft.asr_mode !== vad.asr_mode
  )
})

export const sttDirty = computed(() => (
  sttDraft.type !== speech.stt.type ||
  sttDraft.model_size !== speech.stt.model_size ||
  sttDraft.language !== speech.stt.language ||
  sttDraft.device !== speech.stt.device
))

export const STT_ENGINE_FALLBACK = [
  { id: 'whisper', label: 'Whisper' }
]

export const sttEngineOptions = computed(() => {
  const available = Array.isArray(speech.stt.engines) && speech.stt.engines.length
    ? speech.stt.engines
    : STT_ENGINE_FALLBACK
  return available.some((engine) => engine.id === sttDraft.type)
    ? available
    : [{ id: sttDraft.type, label: sttDraft.type }, ...available]
})

// The form follows each engine's server entry (its models), so adding or
// replacing an engine needs no console change.
export const selectedSttEngine = computed(() => sttEngineOptions.value.find((engine) => engine.id === sttDraft.type) || null)

export const sttModelOptions = computed(() => (
  selectedSttEngine.value?.models || speech.stt.models_by_engine?.[sttDraft.type] || []
))

// Reference audio comes from the server-side voice library, never typed paths.
export const ttsVoiceOptions = computed(() => (Array.isArray(speech.tts.voices) ? speech.tts.voices : []))

export const selectedVadEngine = computed(() => {
  return vad.engines.find((item) => item.id === vadDraft.type) || null
})

export function applyVadSnapshot(data) {
  if (!data) return
  Object.assign(vad, data)
  vad.type = 'silero'
  vad.engines = [SILERO_ENGINE]
  vadDraft.enabled = Boolean(data.enabled)
  vadDraft.type = 'silero'
  vadDraft.threshold = Number(data.threshold ?? 0.5)
  vadDraft.aggressiveness = Number(data.aggressiveness ?? 2)
  vadDraft.min_silence_ms = Number(data.min_silence_ms ?? 500)
  vadDraft.asr_mode = data.asr_mode || 'browser'
}

export function applySpeechSnapshot(data) {
  if (!data) return
  if (data.stt) {
    Object.assign(speech.stt, data.stt)
    Object.assign(sttDraft, {
      type: data.stt.type,
      model_size: data.stt.model_size,
      language: data.stt.language,
      device: data.stt.device
    })
  }
  if (data.tts) Object.assign(speech.tts, data.tts)
}

export async function loadSpeechSettings() {
  speechError.value = ''
  try {
    const data = await parseJson(await fetch('/api/speech'))
    applySpeechSnapshot(data)
    return data
  } catch (error) {
    speechError.value = error.message
    throw error
  }
}

export async function applySttSettings() {
  applyingStt.value = true
  speechError.value = ''
  try {
    const data = await parseJson(await fetch('/api/speech/stt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sttDraft)
    }))
    if (data.pending) return data
    applySpeechSnapshot({ stt: data })
    return data
  } catch (error) {
    speechError.value = error.message
    throw error
  } finally {
    applyingStt.value = false
  }
}

export async function refreshTtsVoices() {
  const data = await parseJson(await fetch('/api/speech/voices'))
  speech.tts.voices = Array.isArray(data?.items) ? data.items : []
  return speech.tts.voices
}

export async function uploadTtsVoice(file, name = '', transcript = '') {
  if (!file) throw new Error('請先選擇參考音訊檔')
  voiceLibraryBusy.value = true
  speechError.value = ''
  try {
    const form = new FormData()
    if (name) form.append('name', name)
    if (transcript) form.append('transcript', transcript)
    form.append('voice', file)
    const voice = await parseJson(await fetch('/api/speech/voices', { method: 'POST', body: form }))
    await refreshTtsVoices()
    return voice
  } catch (error) {
    speechError.value = error.message
    throw error
  } finally {
    voiceLibraryBusy.value = false
  }
}

export async function deleteTtsVoice(voiceId) {
  if (!voiceId) return
  voiceLibraryBusy.value = true
  speechError.value = ''
  try {
    await parseJson(await fetch(`/api/speech/voices/${encodeURIComponent(voiceId)}`, { method: 'DELETE' }))
    await refreshTtsVoices()
  } catch (error) {
    speechError.value = error.message
    throw error
  } finally {
    voiceLibraryBusy.value = false
  }
}

// The voice fields a preview sends; the server resolves them as library and model IDs.
export function previewVoiceFields(tts) {
  return { type: tts.type, ref_file: tts.ref_file || '', tts_server: tts.tts_server || '', model: tts.model || '' }
}

// Whether a profile's BreezyVoice server already runs, so the console can say it is starting.
export async function breezyVoiceServerReady(tts) {
  const { model, tts_server } = previewVoiceFields(tts)
  const query = new URLSearchParams({ model, tts_server })
  const data = await parseJson(await fetch(`/api/speech/breezyvoice/status?${query}`))
  return Boolean(data?.ready)
}

// Synthesize a short sentence with a profile's unsaved voice; resolves to a WAV data URI.
export async function previewProfileVoice(tts) {
  const data = await parseJson(await fetch('/api/speech/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tts: previewVoiceFields(tts) })
  }))
  return data.audio
}

export async function loadVadSettings() {
  vadError.value = ''
  try {
    const data = await parseJson(await fetch('/api/vad'))
    if (data.pending) return data
    applyVadSnapshot(data)
    return data
  } catch (error) {
    vadError.value = error.message
    throw error
  }
}

export async function compareVadEngines(file) {
  comparingVad.value = true
  vadCompareError.value = ''
  vadCompareResult.value = null
  try {
    const form = new FormData()
    form.append('file', file)
    const data = await parseJson(await fetch('/api/vad/compare', {
      method: 'POST',
      body: form
    }))
    vadCompareResult.value = data
    return data
  } catch (error) {
    vadCompareError.value = error.message
    throw error
  } finally {
    comparingVad.value = false
  }
}

export async function applyVadSettings() {
  applyingVad.value = true
  vadError.value = ''
  try {
    const data = await parseJson(await fetch('/api/vad', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled: vadDraft.enabled,
        type: 'silero',
        threshold: Number(vadDraft.threshold),
        aggressiveness: Number(vadDraft.aggressiveness),
        min_silence_ms: Number(vadDraft.min_silence_ms),
        asr_mode: vadDraft.enabled ? 'server' : 'browser'
      })
    }))
    if (data.pending) return data
    applyVadSnapshot(data)
    if (data.warmup_error) {
      vadError.value = data.warmup_error
    }
    return data
  } catch (error) {
    vadError.value = error.message
    throw error
  } finally {
    applyingVad.value = false
  }
}
