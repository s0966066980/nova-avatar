// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// State and request plumbing shared by every settings module.

import { reactive } from 'vue'

export const runtime = reactive({
  pending_settings: { items: [], error: '' },
  llm: {
    model: '',
    base_url: '',
    endpoint: '',
    provider: 'ollama',
    system_prompt: '',
    assistant_profile: { assistant_name: '', system_prompt: '', restriction_prompt: '', output_locale: 'zh-TW', enforce_output_locale: true, forbidden_self_names: [] },
    response_max_chars: 120,
    board_max_items: 8,
    reply_mode: 'legacy',
    semantic_wait_seconds: 0.5,
    reply_rules: { revision: 1, activation: '', speech: '', board: '' }
  },
  stage: {
    background_id: '',
    caption_max_chars: 120,
    idle_reset_seconds: 60,
    idle_greeting_enabled: false,
    idle_greeting_seconds: 30,
    caption_x: 50,
    caption_y: 90,
    caption_width: 100,
    board_style: 'glass',
    board_width: 252,
    board_height: 300,
    board_transparency: 28,
    board_x: 100,
    board_y: 0,
    board_preset: 'tr',
    board_preview: false,
    board_open_x: 50,
    board_open_y: 8,
    mic_x: 50,
    mic_y: 62,
    mic_preset: 'custom'
  },
  avatar: {
    type: '',
    avatar_id: ''
  },
  video: {
    max_height: 0,
    height_options: [450, 540, 720, 960, 1280, 1920, 0],
    source_width: null,
    source_height: null,
    output_width: null,
    output_height: null
  },
  avatar_quality: {
    mouth_sharpen: 0.5,
    paste_interpolation: 'lanczos',
    musetalk: {
      bbox_shift: 0,
      extra_margin: 10,
      parsing_mode: 'jaw',
      left_cheek_width: 90,
      right_cheek_width: 90,
      upper_boundary_ratio: 0.5,
      expand: 1.5,
      mask_blur_ratio: 0.05
    }
  },
  engines: [],
  characters: [],
  session_count: 0,
  switching: false,
  ready: false,
  model_ready: false
})

export async function parseJson(response) {
  let data = {}
  try {
    data = await response.json()
  } catch (error) {
    if (response.status === 404) {
      throw new Error('後端尚未更新設定介面，請重啟後端與前端服務')
    }
    throw error
  }
  if (!response.ok || data.code !== 0) {
    const message = data.msg || (
      response.status === 404
        ? '後端尚未更新設定介面，請重啟後端與前端服務'
        : `HTTP ${response.status}`
    )
    const error = new Error(message)
    error.status = response.status
    error.payload = data
    throw error
  }
  if (data.pending_settings) runtime.pending_settings = data.pending_settings
  return data.pending ? { ...data.data, pending: true } : data.data
}
