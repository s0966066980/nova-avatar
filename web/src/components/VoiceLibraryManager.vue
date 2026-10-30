<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section class="voice-library" aria-labelledby="voice-library-title">
    <div class="voice-library-head">
      <h4 id="voice-library-title">參考音檔音訊庫</h4>
      <button type="button" :disabled="voiceLibraryBusy" @click="refresh">重新整理</button>
    </div>
    <p>上傳自錄或有書面授權的台灣華語錄音（0.5–60 秒），並填寫錄音實際說出的逐字稿；BreezyVoice 只能使用有逐字稿的音檔。音訊庫由所有設定檔共用。</p>
    <p v-if="error" class="voice-library-alert" role="alert">{{ error }}</p>
    <p v-if="!usableCount" class="voice-library-empty" role="status">音訊庫還沒有附逐字稿的參考音檔，請先在下方上傳。</p>
    <ul v-if="voices.length" class="voice-library-list">
      <li v-for="voice in voices" :key="voice.id" :aria-current="voice.id === selected ? 'true' : undefined">
        <div class="voice-library-meta">
          <strong>{{ voice.name }}</strong><span>{{ voice.seconds }} 秒</span>
          <span v-if="voice.id === selected" class="voice-library-tag">此設定檔使用中</span>
          <span v-if="voice.development" class="voice-library-tag voice-library-dev">{{ DEVELOPMENT_VOICE_NOTICE }}</span>
        </div>
        <p class="voice-library-transcript">{{ voice.transcript || '沒有逐字稿，BreezyVoice 無法使用' }}</p>
        <div class="voice-library-actions">
          <button type="button" :aria-pressed="previewId === voice.id" @click="previewId = previewId === voice.id ? '' : voice.id">{{ previewId === voice.id ? '停止試聽' : '試聽' }}</button>
          <button v-if="confirmId === voice.id" type="button" class="voice-library-danger" :disabled="voiceLibraryBusy" @click="remove(voice.id)">確認刪除</button>
          <button v-if="confirmId === voice.id" type="button" @click="confirmId = ''">取消</button>
          <button v-else type="button" :disabled="voiceLibraryBusy" @click="confirmId = voice.id">刪除</button>
        </div>
        <audio v-if="previewId === voice.id" :src="audioUrl(voice.id)" controls autoplay preload="none"></audio>
      </li>
    </ul>
    <div class="voice-library-upload">
      <label>錄音檔<input ref="fileInput" type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a,.webm" @change="file = $event.target.files?.[0] || null"></label>
      <label>名稱（選填，預設為檔名）<input v-model="name" maxlength="80"></label>
      <label class="voice-library-wide">逐字稿（必填）<textarea v-model="transcript" rows="2" maxlength="500" placeholder="錄音中實際說出的內容，例如：您好，歡迎光臨。"></textarea></label>
      <button type="button" :disabled="voiceLibraryBusy || !file || !transcript.trim()" @click="upload">{{ voiceLibraryBusy ? '處理中…' : '上傳到音訊庫' }}</button>
    </div>
  </section>
</template>

<script setup>
// The reference-audio library: upload with transcript, preview and delete.
// Shared by every profile; the server converts, stores and recycles the audio.
import { computed, onMounted, ref } from 'vue'
import { useRuntimeSettings } from '../composables/useRuntimeSettings.js'
import { DEVELOPMENT_VOICE_NOTICE, referenceVoices } from '../voiceSelection.js'
defineProps({ selected: { type: String, default: '' } })
const emit = defineEmits(['uploaded', 'deleted'])
const { ttsVoiceOptions, voiceLibraryBusy, refreshTtsVoices, uploadTtsVoice, deleteTtsVoice } = useRuntimeSettings()
const voices = computed(() => ttsVoiceOptions.value)
const usableCount = computed(() => referenceVoices(voices.value).length)
const error = ref(''), previewId = ref(''), confirmId = ref('')
const file = ref(null), name = ref(''), transcript = ref(''), fileInput = ref(null)
const audioUrl = id => `/api/speech/voices/${encodeURIComponent(id)}/audio`

async function attempt(action) {
  error.value = ''
  try { await action() } catch (e) { error.value = e.message || String(e) }
}
const refresh = () => attempt(refreshTtsVoices)
const upload = () => attempt(async () => {
  const voice = await uploadTtsVoice(file.value, name.value.trim(), transcript.value.trim())
  file.value = null; name.value = ''; transcript.value = ''
  if (fileInput.value) fileInput.value.value = ''
  emit('uploaded', voice)
})
const remove = id => attempt(async () => {
  confirmId.value = ''
  if (previewId.value === id) previewId.value = ''
  await deleteTtsVoice(id)
  emit('deleted', id)
})
onMounted(refresh)
</script>

<style scoped>
.voice-library{margin:20px 0;padding:18px;border:1px solid var(--border-default);border-radius:12px;background:var(--bg-surface);min-width:0}
.voice-library-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.voice-library h4{font-size:15px;margin:0}
.voice-library p{font-size:13px;line-height:1.7;color:var(--text-secondary);margin:10px 0}
.voice-library .voice-library-alert{color:var(--danger)}
.voice-library .voice-library-empty{color:var(--warning)}
.voice-library-list{list-style:none;margin:12px 0;padding:0;display:grid;gap:10px}
.voice-library-list li{padding:12px 14px;border:1px solid var(--border-subtle);border-radius:10px;background:var(--bg-surface-elevated);min-width:0}
.voice-library-list li[aria-current=true]{border-color:var(--brand-light)}
.voice-library-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;font-size:13px;color:var(--text-secondary)}
.voice-library-meta strong{color:var(--text-primary);overflow-wrap:anywhere}
.voice-library-tag{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--border-default)}
.voice-library-dev{color:var(--warning);border-color:var(--warning)}
.voice-library .voice-library-transcript{margin:6px 0 8px;overflow-wrap:anywhere}
.voice-library-actions{display:flex;flex-wrap:wrap;gap:8px}
.voice-library audio{width:100%;margin-top:10px}
.voice-library-upload{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 16px;align-items:end;border-top:1px solid var(--border-subtle);padding-top:6px}
.voice-library-upload label{display:flex;flex-direction:column;gap:8px;margin:12px 0;font-size:13px}
.voice-library-upload .voice-library-wide{grid-column:1/-1}
.voice-library-upload input,.voice-library-upload textarea{width:100%;padding:10px 12px;border:1px solid var(--border-default);border-radius:8px;background:var(--bg-surface-elevated);color:var(--text-primary);font:inherit;box-sizing:border-box}
.voice-library-upload textarea{resize:vertical;min-height:64px}
.voice-library-upload button{justify-self:start}
.voice-library button{padding:8px 12px;border:1px solid var(--border-default);border-radius:8px;background:var(--bg-surface);color:var(--text-primary);font-size:13px;cursor:pointer}
.voice-library button:disabled{opacity:.55;cursor:not-allowed}
.voice-library .voice-library-danger{border-color:var(--danger);color:var(--danger)}
.voice-library :focus-visible{outline:2px solid var(--brand-light);outline-offset:3px}
@media(max-width:700px){.voice-library-upload{grid-template-columns:1fr}}
</style>
