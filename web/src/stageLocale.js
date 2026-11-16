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
  '重試': 'Retry', '重新連線': 'Reconnect',
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
  '連線已取消': 'Connection cancelled', '請重試或聯絡現場管理人員。': 'Please retry or contact the administrator.',
  '開始錄影': 'Start recording', '停止錄影': 'Stop recording', '正在匯出…': 'Exporting…',
  '下載錄影': 'Download recording', '正在下載…': 'Downloading…',
  '錄影期間請保持這個視窗在前景': 'Keep this window in the foreground while recording.',
  '正在切換語系…': 'Switching language…', '語系切換失敗，已保留原設定': 'Language switch failed. Previous settings were kept.',
  '已重新連線，已建立新的對話，先前記憶已清空': 'Reconnected to a new conversation. Previous conversation memory was cleared.',
  'context_capacity': 'Conversation context is full. Please shorten your question or start a new conversation.',
  'pipeline_error': 'The reply could not be completed. Please try again.',
  'english_requires_whisper': 'English speech recognition is not ready yet. Please contact the administrator.',
  'english_requires_edge_tts': 'English voice output is not ready yet. Please contact the administrator.',
  '請先在設定中選擇並套用數字人引擎與角色': 'The avatar is not ready yet. Please wait or contact the administrator.',
  '正在準備對話，請稍後再連線': 'Preparing conversation. Please try again shortly.',
  '正在製作或切換數位人，請稍候': 'The avatar is being prepared. Please wait.',
  '舞台使用中': 'Stage in use',
  '目前已有其他裝置正在使用舞台': 'Another device is currently using the stage.',
  '接管此舞台': 'Take over stage',
  '舞台已由其他裝置接管': 'Stage taken over by another device',
  '此舞台連線已中斷。如需在此裝置繼續使用，請重新接管舞台。': 'This stage connection was closed. To use the stage here, take over again.',
  '重新接管此舞台': 'Take over stage again',
}
const chineseErrors = {
  context_capacity: 'Context 容量不足，請縮短問題或重新建立對話。',
  pipeline_error: '回覆未能完成，請重試。',
  voice_unavailable: '所選聲音暫時無法使用，已保留原設定，請重試。',
  english_requires_whisper: '英文語音辨識尚未就緒，請聯絡管理人員。',
  english_requires_edge_tts: '英文語音輸出尚未就緒，請聯絡管理人員。',
}
export function stageText(text, locale = 'zh-TW') {
  if (/^(tts_error|playback_error)/.test(text)) {
    return locale === 'en-US' ? 'The reply could not be played. Please try again.' : '回覆語音暫時無法播放，請重試。'
  }
  if (locale === 'en-US') return english[text] || text
  const key = Object.keys(english).find(key => english[key] === text) || text
  return chineseErrors[key] || key
}
export function stageItemCount(count, locale) {
  return locale === 'en-US' ? `${count} ${count === 1 ? 'item' : 'items'}` : `${count} 項`
}
