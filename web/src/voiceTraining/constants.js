// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Facts shared by the voice-training screens. Usage labels are never
// translated: they are the original English strings plus an icon.

export const USAGE_DEV = 'Development only'
export const USAGE_RESEARCH = 'Research / Non-commercial'
export const USAGE_LABELS = [USAGE_DEV, USAGE_RESEARCH]

// Exactly the text src/tts/training/edge_acknowledgement.py records as shown.
export const MSA_CLAUSE = {
  reference: 'Microsoft Services Agreement §14(s)(iv)',
  text: 'You may not use the AI services, or data from the AI services, to create, train, or improve (directly or indirectly) any AI technology'
}

export const SOURCE_EDGE = 'edge-test-teacher'
export const SOURCE_SELF = 'self-recorded'
export const SOURCE_WRITTEN = 'written-authorization'
export const SOURCE_DEV = 'development-unlicensed'

// The three upload declarations of spec decision 5. ``consent`` declarations
// need the ticked statement; the development one only states the limit.
export const DECLARATIONS = [
  { key: 'own', source: SOURCE_SELF, needsConsent: true, usage: USAGE_RESEARCH },
  { key: 'written', source: SOURCE_WRITTEN, needsConsent: true, usage: USAGE_RESEARCH },
  { key: 'dev', source: SOURCE_DEV, needsConsent: false, usage: USAGE_DEV }
]

export const EDGE_VOICES = [
  { id: 'zh-TW-HsiaoChenNeural', name: 'HsiaoChen', isDefault: true },
  { id: 'zh-TW-HsiaoYuNeural', name: 'HsiaoYu', isDefault: false },
  { id: 'zh-TW-YunJheNeural', name: 'YunJhe', isDefault: false }
]

// Server presets (src/tts/training/sentences.py): about 220 and 833 sentences.
export const EDGE_PRESETS = [
  { key: 'quick-test', lines: 220, minutes: 15 },
  { key: 'standard', lines: 833, minutes: 60 }
]

export const WHISPER_MODELS = ['small', 'medium', 'large-v3']
export const DEFAULT_WHISPER_MODEL = 'medium'

export const MAX_NAME_CHARS = 40
export const MIN_CORPUS_MINUTES = 15
export const EDGE_TEXT_ACCEPT = '.txt,text/plain'
export const UPLOAD_ACCEPT = 'audio/*,.wav,.mp3,.flac,.ogg,.m4a,.webm'
export const TRANSCRIPT_ACCEPT = '.txt,.csv,text/plain,text/csv'
export const MAX_UPLOAD_MB = 20
export const AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac', '.ogg', '.m4a', '.webm']

// The three preset preview sentences of the done screen (no custom sentence in
// version 1). The first is the sentence the server's profile preview speaks.
export const PREVIEW_SENTENCES = [
  { key: 'zh', text: '您好，歡迎光臨，很高興為您服務。' },
  { key: 'digits', text: '今天是2026年11月24日，票價是150元。' },
  { key: 'en', text: 'Welcome to the exhibition hall, how can I help you?' }
]
