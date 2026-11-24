// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Voice choices of an avatar profile. Edge TTS names a server-side voice;
// BreezyVoice clones a voice-library recording and needs what it says; Matcha
// names a voice model listed by the server.

export const DEFAULT_EDGE_VOICE = 'zh-TW-HsiaoChenNeural'
// Recordings imported for development; the speaker has not consented to cloning.
export const DEVELOPMENT_VOICE_NOTICE = '開發用，未取得說話者授權'

const hasTranscript = voice => Boolean(String(voice?.transcript || '').trim())

// Only transcribed recordings can be cloned, so only they are offered.
export const referenceVoices = voices => (Array.isArray(voices) ? voices : []).filter(hasTranscript)

export function voiceLabel(voice) {
  const label = `${voice.name}（${voice.seconds} 秒）`
  return voice.development ? `${label} · ${DEVELOPMENT_VOICE_NOTICE}` : label
}

// Switch engines without carrying the other engine's voice over: an Edge voice
// name is neither a library ID nor a voice-model ID, and neither BreezyVoice
// nor Matcha gets a recording or voice model picked for it.
export function switchTtsEngine(tts, engine) {
  if (tts.type === engine) return
  tts.type = engine
  tts.ref_text = null
  if (engine === 'breezyvoice') {
    tts.ref_file = ''
  } else if (engine === 'matcha') {
    Object.assign(tts, { ref_file: '', tts_server: '', model: '' })
  } else {
    Object.assign(tts, { ref_file: DEFAULT_EDGE_VOICE, tts_server: '', model: '' })
  }
}

// A voice model's name followed by its usage label, e.g. "Development only".
export const voiceModelLabel = model => `${model.name} · ${model.usage}`

// Quality measured in the 2026-11-23 bake-off (.scratch/matcha-voice/spec.md):
// 500 sentences, CPU with 4 threads, MuseTalk not loaded.
const MEASURED_VOICE_MODELS = {
  'zh-tw-hsiaochen-edge': { cer: '13.2%', wer: '5.6%', firstAudio: '0.05' }
}

// ``t`` is useI18n's translate; '' for a voice model that was never measured.
export function voiceModelMeasurement(t, id) {
  const measured = MEASURED_VOICE_MODELS[id]
  if (!measured) return ''
  return Object.entries(measured).reduce((text, [key, value]) => text.replace(`{${key}}`, value), t('settings.voiceModels.measured'))
}

// Why ``tts`` cannot be saved yet; '' when it can. ``voices`` is the voice
// library (BreezyVoice), ``voiceModels`` the listed Matcha voice models.
export function ttsVoiceProblem(tts, voices, voiceModels = []) {
  if (tts?.type === 'matcha') return voiceModelProblem(tts.ref_file, voiceModels)
  if (tts?.type !== 'breezyvoice') return ''
  if (!tts.ref_file) return '請選擇有逐字稿的參考音檔'
  const voice = (Array.isArray(voices) ? voices : []).find(item => item.id === tts.ref_file)
  if (!voice) return '所選參考音檔不在音訊庫中，請重新選擇或上傳'
  if (!hasTranscript(voice)) return '所選參考音檔沒有逐字稿，請改選或重新上傳並填寫逐字稿'
  return ''
}

function voiceModelProblem(id, voiceModels) {
  if (!id) return '請選擇聲線模型'
  if ((Array.isArray(voiceModels) ? voiceModels : []).some(model => model.id === id)) return ''
  return '所選聲線模型不在已安裝的聲線模型中；請重新選擇，或把附使用限制標示的聲線模型複製到 models/tts'
}
