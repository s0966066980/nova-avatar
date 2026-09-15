// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export const VOICE_TEST_STAGE_LABELS = {
  vad_endpoint: 'VAD 端點',
  asr: 'ASR 轉寫',
  llm_first_token: 'LLM 首字',
  llm_total: 'LLM 完成',
  first_fragment: '首個語意片段',
  tts_first_encoded: 'TTS 首個編碼',
  tts_first_pcm: 'TTS 首個 PCM',
  musetalk_first_batch: 'MuseTalk 首批',
  musetalk_inference_first_result: 'MuseTalk 首幀推論',
  avatar_pasteback_done: 'Avatar 貼回',
  webrtc_audio_enqueue: 'WebRTC 音訊入列',
  webrtc_video_enqueue: 'WebRTC 影像入列',
  avatar_to_webrtc_commit: 'Avatar → WebRTC',
  webrtc_audio_commit: 'WebRTC 音訊提交',
}

export function formatSeconds(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toFixed(3)} s`
}

export function statusLabel(status) {
  return {
    running: '測試中',
    passed: '通過',
    failed: '未通過',
    interrupted: '已中斷',
  }[status] || '未知'
}

export function voicePhaseLabel(state) {
  return {
    stt: '正在轉寫',
    llm: '正在生成回覆',
    tts_ready: '正在合成語音',
    avatar_speaking: '數字人正在播放',
    tail_guard: '正在確認播放收尾',
    listening: '正在完成紀錄',
  }[state] || '正在送出測試'
}

export function stageRows(metrics = {}) {
  const stages = metrics.stage_seconds || {}
  return Object.entries(VOICE_TEST_STAGE_LABELS).map(([key, label]) => ({
    key,
    label,
    value: stages[key],
  }))
}
