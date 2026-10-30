// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Voice choices of an avatar profile. Edge TTS names a server-side voice;
// BreezyVoice clones a voice-library recording and needs what it says.

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
// name is not a library ID, and BreezyVoice never gets a recording picked for it.
export function switchTtsEngine(tts, engine) {
  if (tts.type === engine) return
  tts.type = engine
  tts.ref_text = null
  if (engine === 'breezyvoice') {
    tts.ref_file = ''
  } else {
    Object.assign(tts, { ref_file: DEFAULT_EDGE_VOICE, tts_server: '', model: '' })
  }
}

// Why ``tts`` cannot be saved yet; '' when it can.
export function referenceAudioProblem(tts, voices) {
  if (tts?.type !== 'breezyvoice') return ''
  if (!tts.ref_file) return '請選擇有逐字稿的參考音檔'
  const voice = (Array.isArray(voices) ? voices : []).find(item => item.id === tts.ref_file)
  if (!voice) return '所選參考音檔不在音訊庫中，請重新選擇或上傳'
  if (!hasTranscript(voice)) return '所選參考音檔沒有逐字稿，請改選或重新上傳並填寫逐字稿'
  return ''
}
