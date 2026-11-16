// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// UI strings only: never run this over replies, transcripts or previous boards.
const english = {
  '數字人舞台': 'Avatar stage', '數位人舞台': 'Avatar stage',
  '無法連線': 'Unable to connect',
  '第一次展示，準備這四件事': 'Four steps to prepare your first presentation',
  '先定義展示目標': 'Define the presentation goal',
  '選定一個主要情境，例如接待、導覽或常見問題。': 'Choose a primary use case, such as reception, guided tours or frequently asked questions.',
  '確認人物與聲音': 'Check the avatar and voice',
  '檢查數字人構圖、音量與嘴型，用一段短句試播。': 'Check framing, volume and lip sync with a short test sentence.',
  '安排互動與看板': 'Arrange the controls and board',
  '調整看板與麥克風位置，讓人物、字幕和條列都能閱讀。': 'Position the board and microphone so the avatar, captions and details remain visible.',
  '彩排異常情境': 'Rehearse recovery',
  '試一次關閉再開看板，下一輪對話應清掉舊項目。': 'Try hiding and reopening the board. A new turn should clear previous items.',
  'voice_unavailable': 'The selected voice is unavailable. Previous settings were kept. Please try again.',
  '選擇語言即可進入，瀏覽器會詢問麥克風權限。': 'Choose your language to enter. Your browser will ask for microphone access.',
  '準備中': 'Preparing', '收音': 'Microphone', '回答看板': 'Answer board',
  '關閉看板': 'Close board', '展開看板': 'Show board', '收合看板': 'Hide board',
  '連線中': 'Connecting', '自動收音': 'Hands-free', '自動收音・已暫停': 'Hands-free · paused',
  '按鍵收音': 'Push to talk', '點一下插話': 'Tap to interrupt',
  '已暫停收音，點一下恢復': 'Paused · tap to resume', '直接說話': 'Speak naturally',
  '放開送出': 'Release to send', '按住說話': 'Hold to speak', '預覽': 'Preview',
  '控制台預覽 · 對位置與大小，非本輪回答': 'Layout preview from the console',
  '本輪條列 · 可關閉後再展開': 'Answer details · hide and reopen anytime',
  '重試': 'Retry', '重新連線': 'Reconnect', '開啟控制台': 'Open console',
  '正在建立與數字人的即時通道。': 'Connecting to the avatar.',
  '連線中斷': 'Disconnected', '與數字人的通道已斷開。': 'The connection to the avatar was lost.',
  '切換呈現方式': 'Updating presentation',
  '正在準備數位人，完成後會自動重新連線。': 'Preparing the avatar. The stage will reconnect automatically.',
  '麥克風無法使用，目前為純觀看': 'Microphone unavailable. You can still watch the avatar.',
  '需要受信任的 HTTPS 連線才能使用麥克風，目前為純觀看': 'Trusted HTTPS is required for the microphone. You can still watch the avatar.',
  '需要受信任的 HTTPS 連線才能啟用麥克風，仍可使用文字與附件。': 'Trusted HTTPS is required for the microphone. Text and attachments are still available.',
  '麥克風權限未允許，請在瀏覽器設定允許麥克風，目前為純觀看': 'Microphone permission was denied. Allow microphone access in browser settings, or continue watching.',
  '麥克風權限未允許，請在瀏覽器設定允許麥克風，仍可使用文字與附件。': 'Microphone permission was denied. Allow microphone access in browser settings; text and attachments remain available.',
  '無法啟用麥克風，仍可使用文字與附件。': 'Microphone unavailable. Text and attachments are still available.',
  '點擊開啟聲音': 'Tap to enable sound',
  '數字人尚未就緒': 'Avatar not ready', '連線失敗': 'Connection failed',
  '連線已取消': 'Connection cancelled', '請重試或開啟控制台檢查設定。': 'Retry or open the console to check the settings.',
  '開始錄影': 'Start recording', '停止錄影': 'Stop recording', '正在匯出…': 'Exporting…',
  '下載錄影': 'Download recording', '正在下載…': 'Downloading…',
  '錄影期間請保持這個視窗在前景': 'Keep this window in the foreground while recording.',
  '正在切換語系…': 'Switching language…', '語系切換失敗，已保留原設定': 'Language switch failed. Previous settings were kept.',
  '已重新連線，已建立新的對話，先前記憶已清空': 'Reconnected to a new conversation. Previous conversation memory was cleared.',
  'context_capacity': 'Conversation context is full. Reduce the history limit, shorten your question or clear the conversation from the console.',
  'pipeline_error': 'The reply could not be completed. Please try again.',
  'english_requires_whisper': 'English conversation requires Whisper speech recognition. Select it in the console first.',
  'english_requires_edge_tts': 'English conversation requires Edge TTS. Select it in the console first.',
  '請先在設定中選擇並套用數字人引擎與角色': 'Select and apply an avatar in the console first.',
  '正在準備對話，請稍後再連線': 'Preparing conversation. Please try again shortly.',
  '正在製作或切換數位人，請稍候': 'The avatar is being prepared. Please wait.',
  '舞台使用中': 'Stage in use',
  '目前已有其他裝置正在使用舞台': 'Another device is currently using the stage.',
  '接管此舞台': 'Take over stage',
  '舞台已由其他裝置接管': 'Stage taken over by another device',
  '此舞台連線已中斷。如需在此裝置繼續使用，請重新接管舞台。': 'This stage connection was closed. To use the stage here, take over again.',
  '重新接管此舞台': 'Take over stage again',
  '推薦提問': 'Suggested questions',
  '重試麥克風': 'Retry microphone',
  '再試一次': 'Try again',
  '清空對話重試': 'Reset & retry',
  '關閉': 'Dismiss',
  '關閉提示': 'Dismiss notice',
  '麥克風權限未允許，請點擊網址列鎖頭允許麥克風，或改用文字／推薦提問。': 'Microphone permission denied. Allow mic access in your browser address bar, or use text / suggested questions.',
  'speech_too_short': 'That was too short. Please move closer to the mic and try again.',
  'audio_too_quiet': 'Your voice was too quiet. Please move closer and speak again.',
  'empty_transcript': 'I could not catch that clearly. Please speak again or tap a prompt.',
  'transcript_low_confidence': 'Could not recognize clearly. Please speak a bit more slowly and try again.',
  'transcript_invalid_confidence': 'Speech recognition could not be verified. Please try again.',
  'unsupported_file': 'Supported formats: PDF, JPG, PNG, WebP.',
  'page_limit': 'Up to 40 PDF pages per question. Please select a smaller page range.',
  'invalid_pages': 'Invalid page range. Use a format such as 1-3,5.',
  'file_size': 'Each file must be between 1 byte and 20 MB.',
  'reference_limit': 'Up to 4 attachments per question.',
  'encrypted_pdf': 'This PDF is encrypted. Please unlock it before uploading.',
  'session_quota': 'Session attachment limit reached (20 files / 200 MB). Remove an older file first.',
  'pixel_limit': 'Image exceeds 24 megapixels. Please resize and try again.',
  'analysis_capacity': 'Attachment analysis exceeded model capacity. Select fewer pages and retry.',
  'analysis_unreadable': 'Unable to read the page reliably. Select fewer pages or retry.',
  'vision_unavailable': 'Vision analysis is not ready yet. Try again shortly or ask in text.',
  'prompt_send_failed': 'Could not send this question right now. Please try again.',
}
const chineseErrors = {
  context_capacity: 'Context 容量不足，請由控制台降低保留上限、縮短問題或清空對話。',
  pipeline_error: '回覆或語音合成失敗，請再試一次。',
  voice_unavailable: '所選聲音暫時無法使用，已保留原設定，請重試。',
  english_requires_whisper: '英文對話需先在控制台套用 Whisper 語音辨識。',
  english_requires_edge_tts: '英文對話需先在控制台套用 Edge TTS。',
  speech_too_short: '說話時間太短，請靠近麥克風再試一次。',
  audio_too_quiet: '聲音較小未能辨識，請靠近麥克風再說一次。',
  empty_transcript: '剛剛沒有聽清楚，請再說一次或點選推薦提問。',
  transcript_low_confidence: '語音辨識不清楚，請放慢語速再說一次。',
  transcript_invalid_confidence: '語音辨識異常，請再說一次。',
  unsupported_file: '僅支援 PDF、JPG、PNG、WebP 檔案格式。',
  page_limit: 'PDF 每輪最多 40 頁，請選取較小的頁碼範圍。',
  invalid_pages: '頁碼格式無效，請使用例如 1-3,5。',
  file_size: '單檔大小須為 1 byte 至 20 MB。',
  reference_limit: '每輪最多可參考 4 個附件。',
  encrypted_pdf: '此 PDF 已加密，請先解除密碼保護後再上傳。',
  session_quota: '本場附件已達上限（20 個／200 MB），請先移除舊檔案。',
  pixel_limit: '圖片解析度超過 2400 萬像素，請縮小後再試。',
  analysis_capacity: '檔案分析超出模型容量，請減少頁碼範圍後重試。',
  analysis_unreadable: '無法可靠讀取頁面內容，請改選較小頁碼範圍或重試。',
  vision_unavailable: '視覺分析模型尚未就緒，請稍後再試或改用純文字提問。',
  prompt_send_failed: '暫時無法送出此問題，請再試一次。',
}
export function stageText(text, locale = 'zh-TW') {
  if (/^(tts_error|playback_error)/.test(text)) {
    return locale === 'en-US' ? 'Voice synthesis or playback failed. Please try again.' : '回覆語音合成或播放失敗，請再試一次。'
  }
  if (locale === 'en-US') return english[text] || text
  const key = Object.keys(english).find(key => english[key] === text) || text
  return chineseErrors[key] || key
}
export function stageErrorGuidance(code, locale = 'zh-TW') {
  const key = String(code || 'pipeline_error')
  if (key === 'mic_permission_denied') {
    return {
      message: stageText('麥克風權限未允許，請點擊網址列鎖頭允許麥克風，或改用文字／推薦提問。', locale),
      actionKind: 'retry_mic',
      actionLabel: stageText('重試麥克風', locale)
    }
  }
  if (key === 'mic_insecure_context') {
    return {
      message: stageText('需要受信任的 HTTPS 連線才能啟用麥克風，仍可使用文字與附件。', locale),
      actionKind: 'dismiss',
      actionLabel: stageText('關閉', locale)
    }
  }
  if (key === 'mic_unavailable') {
    return {
      message: stageText('無法啟用麥克風，仍可使用文字與附件。', locale),
      actionKind: 'retry_mic',
      actionLabel: stageText('重試麥克風', locale)
    }
  }
  if (['speech_too_short', 'audio_too_quiet', 'empty_transcript', 'transcript_low_confidence', 'transcript_invalid_confidence'].includes(key)) {
    return {
      message: stageText(key, locale),
      actionKind: 'retry_speech',
      actionLabel: stageText('再試一次', locale)
    }
  }
  if (key === 'context_capacity') {
    return {
      message: stageText(key, locale),
      actionKind: 'reset_conversation',
      actionLabel: stageText('清空對話重試', locale)
    }
  }
  if (['unsupported_file', 'page_limit', 'invalid_pages', 'file_size', 'reference_limit', 'encrypted_pdf', 'session_quota', 'pixel_limit', 'analysis_capacity', 'analysis_unreadable', 'vision_unavailable'].includes(key)) {
    return {
      message: stageText(key, locale),
      actionKind: 'dismiss',
      actionLabel: stageText('關閉', locale)
    }
  }
  return {
    message: stageText(key, locale),
    actionKind: 'reconnect_or_retry',
    actionLabel: stageText('再試一次', locale)
  }
}
export function stageItemCount(count, locale) {
  return locale === 'en-US' ? `${count} ${count === 1 ? 'item' : 'items'}` : `${count} 項`
}
