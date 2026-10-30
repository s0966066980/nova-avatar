// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Stubbed backend answers for rendering the settings center without a server.
// Values are long enough to exercise wrapping: several avatars, backgrounds,
// voices and profiles with full prompts.

const longText = (seed, repeat) => Array.from({ length: repeat }, (_, i) => `${seed}第 ${i + 1} 段說明。`).join('')

const stage = {
  background_id: 'bg-1', caption_max_chars: 120, idle_reset_seconds: 60, clear_display_seconds: 15,
  idle_greeting_enabled: true, idle_greeting_seconds: 30,
  caption_x: 50, caption_y: 90, caption_width: 100,
  board_style: 'glass', board_width: 252, board_height: 300, board_transparency: 28,
  board_x: 100, board_y: 0, board_preset: 'tr', board_preview: true,
  board_open_x: 50, board_open_y: 8, mic_x: 50, mic_y: 62, mic_preset: 'custom',
  composer_enabled: true
}

const characters = Array.from({ length: 7 }, (_, i) => ({
  id: `avatar_${i + 1}`, type: 'musetalk', label: `接待數位人 ${i + 1} 號（綠幕長名稱測試）`, resolution: '1080x1920', fps: 25,
  preview_url: `/api/avatars/avatar_${i + 1}/preview`,
  green_screen: i % 2 === 0
}))

const voices = Array.from({ length: 4 }, (_, i) => ({
  id: `voice_${i + 1}`, name: `參考音檔 ${i + 1}`, seconds: 6.5 + i,
  transcript: i === 3 ? '' : longText('您好，歡迎光臨。', 2), development: i === 0
}))

function profile(id, name) {
  return {
    id, name, avatar_id: 'avatar_1', engine: 'musetalk',
    assistant_profile: {
      assistant_name: name, system_prompt: longText(`${name}的身分說明。`, 12),
      restriction_prompt: longText('限制說明。', 4), output_locale: 'zh-TW', enforce_output_locale: true,
      forbidden_self_names: ['AI', '機器人']
    },
    llm: {
      endpoint: 'local', model: 'local-model', response_max_chars: 120, max_tokens: 512,
      board_max_items: 8, reply_mode: 'streaming', semantic_wait_seconds: 0.5
    },
    reply_rules: { activation: longText('看板時機。', 3), speech: longText('口語規則。', 3), board: longText('看板內容。', 3) },
    tts: { type: 'breezyvoice', ref_file: 'voice_2', ref_text: null, voice_en_us: '', tts_server: '', model: '' },
    rag: { enabled: false, dataset_ids: [], document_scope: 'all', document_ids: [] },
    tools: { weather: false },
    greeting: {
      mode: 'scripts', prompt: '', min_chars: 20, max_chars: 60,
      scripts: [longText('歡迎來到展場。', 3), longText('需要協助嗎？', 3)], scripts_en: ['Welcome!']
    }
  }
}

const library = {
  version: 1, revision: 3, enabled: true,
  profiles: [profile('main', '接待員'), profile('weather', '氣象員'), profile('guide', '導覽員')],
  pair: { main: 'main', specialist: 'weather' },
  transitions: [{ source: 'main', target: 'weather', kind: 'effect', effect: 'fade', duration: 0.6, asset_id: '' }],
  handoff: {
    description: longText('天氣專長。', 3), rules: longText('交接規則。', 5), announcement: '稍等，我請氣象員回答。',
    announcement_en: '', return_announcement: '', return_announcement_en: ''
  },
  weather: { county: '臺北市', town: '中正區' }
}

const session = (sessionid, role) => ({
  sessionid, role, locale: 'zh-TW', history_max_messages: 20, voice_zh_tw: 'zh-TW-HsiaoChenNeural',
  voice_en_us: 'en-US-JennyNeural', idle_reset_seconds: 15, full_reset_seconds: 60,
  profiles: [{ id: 'main', name: '接待員', memory: {
    retained_messages: 12, max_messages: 20, evicted_messages: 4, oldest_message_number: 5,
    oldest_message: { role: 'user', content: longText('請問展場怎麼走？', 4) },
    context: {
      estimated: false, input_tokens: 2100, reserved_output_tokens: 512, capacity: 8192, history_tokens: 1300,
      other_input_tokens: 800, remaining_tokens: 5580, usage_percent: 32, model: 'local-model', source: 'llama.cpp',
      observed_at: 1767225600
    }
  } }]
})

const responses = {
  '/api/session': { code: 0, data: { configured: true, authenticated: true } },
  '/health': { ready: true, model_ready: true, llm_full_gpu: true },
  '/api/settings': { code: 0, data: {
    llm: { model: 'local-model', endpoint: 'local', provider: 'llamacpp', system_prompt: '', reply_rules: { revision: 1, activation: '', speech: '', board: '' } },
    stage, avatar: { type: 'musetalk', avatar_id: 'avatar_1' }, characters,
    engines: [{ id: 'musetalk' }, { id: 'wav2lip' }], ready: true, model_ready: true,
    vad: { supported: true, enabled: true, threshold: 0.5, min_silence_ms: 500, asr_mode: 'server' }
  } },
  '/api/llm/rules': { code: 0, data: { rules: { activation: '', speech: '', board: '' }, defaults: { activation: 'a', speech: 's', board: 'b' }, limits: {} } },
  '/api/llm/models': { code: 0, data: { endpoints: [{ name: 'local', label: 'llama.cpp', provider: 'llamacpp', base_url: 'http://127.0.0.1:8080/v1', models: ['local-model'] }] } },
  '/api/speech': { code: 0, data: {
    stt: {
      type: 'whisper', model_size: 'small', language: 'zh', output_script: 'traditional-tw', device: 'auto',
      engines: [
        { id: 'whisper', label: 'Whisper（中英文）', description: longText('本機 Whisper 辨識。', 2), available: true, models: ['tiny', 'base', 'small', 'medium', 'large-v3'],
          output_scripts: [{ id: 'traditional-tw', label: '繁體中文（臺灣）' }, { id: 'original', label: '原始輸出' }] },
        { id: 'funasr', label: 'Fun-ASR-Nano', available: false, models: ['Fun-ASR-Nano-2512'] }
      ],
      models_by_engine: { whisper: ['tiny', 'base', 'small', 'medium', 'large-v3'] }
    },
    tts: {
      engines: [
        { id: 'edgetts', label: 'Edge TTS（僅開發用）', description: '線上服務，僅供開發測試。' },
        { id: 'breezyvoice', label: 'BreezyVoice', description: '本機聲音複製，需要參考音檔與逐字稿。' }
      ],
      notice: ''
    }
  } },
  '/api/speech/voices': { code: 0, data: { items: voices } },
  '/api/vad': { code: 0, data: { supported: true, enabled: true, threshold: 0.5, min_silence_ms: 500, asr_mode: 'server' } },
  '/api/stage': { code: 0, data: stage, greetings: [{ status: 'waiting' }] },
  '/api/profiles': { code: 0, library, greeting_profile: library.profiles[0], media: [],
    runtime: { enabled: true, phase: 'idle', profiles_applied: true, active_revision: 3, active_profile_id: 'main', weather_configured: false } },
  '/api/backgrounds': { code: 0, data: { background_id: 'bg-1', items: Array.from({ length: 9 }, (_, i) => ({
    id: `bg-${i + 1}`, label: `展場背景 ${i + 1}（很長的背景名稱用來測試截斷）`, kind: ['image', 'video', 'gif'][i % 3],
    preview_url: `/api/backgrounds/bg-${i + 1}/preview`
  })) } },
  '/api/backgrounds/deleted': { code: 0, data: { items: [{ archive_name: 'old-bg', label: '舊背景' }] } },
  '/api/avatars/deleted': { code: 0, data: { items: [{ archive_name: 'old-avatar', avatar_id: 'old_avatar' }] } },
  '/api/conversations': { code: 0, data: {
    sessions: [session(11, 'console'), session(12, 'stage')],
    voices: { 'zh-TW': [{ id: 'zh-TW-HsiaoChenNeural', label: '曉臻' }], 'en-US': [{ id: 'en-US-JennyNeural', label: 'Jenny' }] },
    defaults: { locale: 'zh-TW', history_max_messages: 20, voice_zh_tw: 'zh-TW-HsiaoChenNeural', voice_en_us: 'en-US-JennyNeural' },
    model_context: { capacity: 8192 }
  } },
  '/api/ragflow/status': { code: 0, configured: false }
}

// Paths the console sends to the backend; everything else is served by Vite.
export function isBackendPath(pathname) {
  return /^\/(api|health|human|humanaudio|asr|record|offer|interrupt_talk|is_speaking|set_audiotype|download|clear_history)(\/|$)/.test(pathname)
}

// A portrait placeholder for avatar, scene and background previews.
const previewImage = `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920"><defs><linearGradient id="g" x2="0" y2="1"><stop offset="0" stop-color="#3b4a6b"/><stop offset="1" stop-color="#121826"/></linearGradient></defs><rect width="1080" height="1920" fill="url(#g)"/><ellipse cx="540" cy="760" rx="210" ry="260" fill="#8090b0"/><rect x="250" y="1080" width="580" height="840" rx="200" fill="#5d6b88"/></svg>`

// Returns { contentType, body } for a backend request.
export function settingsApi(pathname) {
  if (/\/(scene-)?preview$/.test(pathname)) return { contentType: 'image/svg+xml', body: previewImage }
  return { contentType: 'application/json', body: JSON.stringify(responses[pathname] || { code: 0, data: {} }) }
}
