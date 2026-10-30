<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="profile-editor">
    <nav class="profile-sections" aria-label="數位人設定分區">
      <button v-for="item in sections" :key="item.id" type="button" :aria-pressed="section === item.id" @click="section = item.id"><i :class="item.icon" aria-hidden="true"></i>{{ item.label }}</button>
    </nav>
    <section v-show="section === 'identity'" class="profile-section">
      <h3>身分與人物素材</h3>
      <p>這些設定只屬於「{{ profile.name }}」。人物素材可供其他設定檔共用。</p>
      <div class="profile-grid">
        <label>顯示名稱<input v-model="profile.name" required maxlength="80"></label>
        <label>人物素材<select v-model="profile.avatar_id"><option v-for="a in avatars" :key="a.id" :value="a.id">{{ a.label || a.name || a.id }}</option><option v-if="!avatars.some(a => a.id === profile.avatar_id)" :value="profile.avatar_id">{{ profile.avatar_id }}</option></select></label>
        <label>推理引擎<select v-model="profile.engine"><option value="musetalk">MuseTalk</option><option value="wav2lip">Wav2Lip · Research / Non-commercial</option><option v-if="!['musetalk','wav2lip'].includes(profile.engine)" :value="profile.engine">{{ profile.engine }}</option></select></label>
        <label>助手自稱<input v-model="profile.assistant_profile.assistant_name" maxlength="200"></label>
      </div>
      <p>即時角色組合使用 MuseTalk。變更推理或語音引擎前，請先在對應設定頁載入引擎。</p>
      <label for="llm-system-prompt">身分 Prompt</label>
      <p id="llm-system-prompt-hint">角色身分、專長、語氣與回答原則。</p>
      <textarea id="llm-system-prompt" v-model="profile.assistant_profile.system_prompt" rows="8" maxlength="12000" data-editor-key="prompt" :style="{ height: `${editorHeights.prompt}px` }" @pointerup="rememberEditorHeight" aria-describedby="llm-system-prompt-hint llm-system-prompt-count"></textarea>
      <small id="llm-system-prompt-count">{{ profile.assistant_profile.system_prompt.length }} / 12000</small>
      <label>限制 Prompt<textarea v-model="profile.assistant_profile.restriction_prompt" rows="4" maxlength="12000"></textarea></label>
      <div class="profile-grid">
        <label>輸出語系<select v-model="profile.assistant_profile.output_locale"><option value="zh-TW">繁體中文（臺灣）</option><option value="zh-CN">簡體中文</option><option value="en-US">English (US)</option><option value="en">English</option><option value="auto">自動</option></select></label>
        <label>禁止自稱名稱（逗號分隔）<input :value="profile.assistant_profile.forbidden_self_names.join(', ')" @input="profile.assistant_profile.forbidden_self_names = $event.target.value.split(/[,，]/).map(x => x.trim()).filter(Boolean)"></label>
      </div>
      <label class="profile-check"><input type="checkbox" v-model="profile.assistant_profile.enforce_output_locale">限制輸出語系</label>
    </section>
    <section v-show="section === 'model'" class="profile-section">
      <h3>AI 模型與回覆規則</h3>
      <p>模型、回答長度、回覆模式與看板規則隨這份數位人設定檔一起儲存。</p>
      <div class="profile-grid">
        <label>LLM 端點<select v-model="profile.llm.endpoint" required><option value="" disabled>請選擇端點</option><option v-for="e in endpointOptions" :key="e.name" :value="e.name">{{ e.name }} · {{ e.label || e.provider }}</option></select></label>
        <label>回答模型<input v-model="profile.llm.model" required list="role-models"></label>
      </div>
      <datalist id="role-models"><option v-for="m in modelNames" :key="m" :value="m"></option></datalist>
      <p v-if="selectedEndpoint">服務網址：{{ selectedEndpoint.base_url }}</p>
      <p v-else-if="endpoints.length" role="alert">此設定檔的原服務網址不在伺服器設定檔的 LLM 端點清單中，請改選端點後再儲存套用。</p>
      <p>LLM 端點、網址與 API 金鑰只能由伺服器設定檔 <code>llm.endpoints</code> 管理；本機 llama.cpp 會在套用時載入所選模型。即時交接的兩位角色需使用相同端點與模型。</p>
      <div class="profile-grid">
        <label for="llm-response-max-chars">口語字數上限<input id="llm-response-max-chars" type="number" v-model.number="profile.llm.response_max_chars" min="20" max="2000" required aria-describedby="llm-response-max-chars-hint"></label>
        <label>模型 Token 預算<input type="number" v-model.number="profile.llm.max_tokens" min="16" max="8192" required></label>
        <label for="llm-board-max-items">看板項目上限<input id="llm-board-max-items" type="number" v-model.number="profile.llm.board_max_items" min="1" max="12" required></label>
        <label for="llm-reply-mode">回覆模式<select id="llm-reply-mode" v-model="profile.llm.reply_mode"><option value="legacy">完整生成後回覆</option><option value="streaming">回覆語音串流</option></select></label>
      </div>
      <p id="llm-response-max-chars-hint">口語上限為 20–2000 字。看板的系統固定規則會維持資料與語音分流，JSON 不會送入語音。</p>
      <label for="semantic-wait">語意等待上限（秒）<input id="semantic-wait" type="number" v-model.number="profile.llm.semantic_wait_seconds" min="0.5" max="30" step="0.5" required></label>
      <p>串流回覆尚未形成完整句子時，最多等待多久才尋找下一個可朗讀子句。</p>
      <div class="profile-heading"><h4>回答與看板規則</h4><button type="button" @click="$emit('restore-rules')">還原此角色的預設規則</button></div>
      <label v-for="rule in ruleFields" :key="rule.key" :for="`rule-${rule.key}`">{{ rule.label }}<textarea :id="`rule-${rule.key}`" v-model="profile.reply_rules[rule.key]" rows="4" maxlength="12000" :data-editor-key="rule.key" :style="{ height: `${editorHeights[rule.key]}px` }" @pointerup="rememberEditorHeight"></textarea></label>
    </section>
    <section v-show="section === 'rag'" class="profile-section">
      <RagFlowSettings :key="profile.id" v-model="profile.rag" :profile-id="profile.id" :profile-name="profile.name" :disabled="disabled" />
    </section>
    <section v-show="section === 'voice'" class="profile-section">
      <h3>聲音與工具</h3><p>每位角色可選擇自己的聲線；即時組合共用同一語音合成引擎。主數位人的聲音也是尚未套用設定檔時的預設聲音。</p>
      <!-- A saved role named a removed engine; the server switched it to Edge TTS. -->
      <p v-if="speech.tts.notice" class="profile-alert" role="status">{{ speech.tts.notice }}</p>
      <div class="profile-grid">
        <label>語音引擎<select :value="profile.tts.type" @change="switchTtsEngine(profile.tts, $event.target.value)"><option v-for="engine in ttsEngines" :key="engine" :value="engine">{{ ttsEngineLabel(engine) }}</option></select></label>
        <label v-if="usesVoiceLibrary">參考音檔<select v-model="profile.tts.ref_file" :aria-invalid="Boolean(voiceProblem)" :aria-describedby="voiceProblem ? 'profile-voice-problem' : undefined" @change="profile.tts.ref_text = null"><option value="" disabled>請選擇參考音檔</option><option v-for="voice in referenceVoiceOptions" :key="voice.id" :value="voice.id">{{ voiceLabel(voice) }}</option></select></label>
        <label v-else>聲線<input v-model="profile.tts.ref_file" placeholder="zh-TW-HsiaoChenNeural"></label>
      </div>
      <p v-if="ttsEngineDescription">{{ ttsEngineDescription }}</p>
      <p v-if="voiceProblem" id="profile-voice-problem" class="profile-alert" role="alert">{{ voiceProblem }}</p>
      <p v-if="selectedVoice?.transcript">逐字稿：{{ selectedVoice.transcript }}</p>
      <div class="profile-preview">
        <button type="button" :disabled="previewDisabled" @click="previewVoice"><i class="bi bi-play-circle" aria-hidden="true"></i> 試聽此設定檔的聲音</button>
        <span v-if="previewPhase" role="status">{{ previewPhase === 'starting' ? 'BreezyVoice 伺服器啟動中，首次載入約需 1–2 分鐘…' : '合成試聽句中…' }}</span>
      </div>
      <p v-if="previewError" class="profile-alert" role="alert">{{ previewError }}</p>
      <audio v-if="previewAudio" :src="previewAudio" controls autoplay></audio>
      <label v-if="profile.tts.type === 'edgetts'">英文聲音<input v-model="profile.tts.voice_en_us" placeholder="en-US-JennyNeural"></label>
      <VoiceLibraryManager v-if="usesVoiceLibrary" :selected="profile.tts.ref_file" @uploaded="voice => chooseVoice(voice.id)" @deleted="id => { if (profile.tts.ref_file === id) chooseVoice('') }" />
      <details v-if="usesVoiceLibrary"><summary>其他 BreezyVoice 設定</summary><div class="profile-grid"><label v-for="(label,key) in voiceFields" :key="key">{{ label }}<input :value="profile.tts[key] || ''" @input="profile.tts[key] = $event.target.value"></label></div></details>
      <label class="profile-check"><input type="checkbox" v-model="profile.tools.weather">使用 CWA 即時天氣工具（臺灣，角色交接模式）</label>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import RagFlowSettings from './RagFlowSettings.vue'
import VoiceLibraryManager from './VoiceLibraryManager.vue'
import { referenceAudioProblem, referenceVoices, switchTtsEngine, voiceLabel } from '../voiceSelection.js'
import { useRuntimeSettings } from '../composables/useRuntimeSettings'
import { STORAGE_KEYS, LEGACY_STORAGE_KEYS, readMigratedStorage } from '../storageKeys.js'
const profile = defineModel({ type: Object, required: true })
const props = defineProps({ avatars: { type: Array, default: () => [] }, endpoints: { type: Array, default: () => [] }, initialSection: { type: String, default: 'identity' }, disabled: Boolean })
defineEmits(['restore-rules'])
const section = ref(props.initialSection)
const sections = [
  { id: 'identity', icon: 'bi bi-person-badge', label: '身分與素材' },
  { id: 'model', icon: 'bi bi-cpu', label: 'AI 模型與規則' },
  { id: 'rag', icon: 'bi bi-journal-text', label: 'RAG 知識文本' },
  { id: 'voice', icon: 'bi bi-soundwave', label: '聲音與工具' }
]
const ruleFields = [{ key: 'activation', label: '何時使用看板' }, { key: 'speech', label: '口語回覆規則' }, { key: 'board', label: '看板內容規則' }]
const voiceFields = { tts_server: 'BreezyVoice 服務網址（限本機，留空為預設）', model: 'models/ 內的 BreezyVoice 模型（留空為預設）' }
// Reference audio is a voice-library ID; the server rejects file paths.
const { ttsVoiceOptions, speech, breezyVoiceServerReady, previewProfileVoice } = useRuntimeSettings()
const referenceVoiceOptions = computed(() => referenceVoices(ttsVoiceOptions.value))
const selectedVoice = computed(() => usesVoiceLibrary.value ? referenceVoiceOptions.value.find(v => v.id === profile.value.tts.ref_file) : null)
const voiceProblem = computed(() => referenceAudioProblem(profile.value.tts, ttsVoiceOptions.value))
// The library transcript describes the chosen recording; drop any older override.
function chooseVoice(id) { profile.value.tts.ref_file = id; profile.value.tts.ref_text = null }
// Server catalog labels carry each engine's usage restriction (e.g. Edge TTS is development only).
const ttsEngineLabel = id => speech.tts.engines.find(engine => engine.id === id)?.label || id
const ttsEngineDescription = computed(() => speech.tts.engines.find(engine => engine.id === profile.value.tts.type)?.description || '')
// The only TTS engines; the server switches saved roles of removed engines to Edge TTS.
const ttsEngines = ['edgetts', 'breezyvoice']
// BreezyVoice clones a voice-library recording and needs what it says.
const usesVoiceLibrary = computed(() => profile.value.tts.type === 'breezyvoice')
// Preview the unsaved voice: '' idle, 'starting' (BreezyVoice server loading) or 'synthesizing'.
const previewPhase = ref(''), previewAudio = ref(''), previewError = ref('')
const previewDisabled = computed(() => Boolean(previewPhase.value || !profile.value.tts.ref_file || voiceProblem.value))
let previewRequest = 0
const voiceKey = computed(() => ['type', 'ref_file', 'tts_server', 'model'].map(key => profile.value.tts[key] || '').join('\n'))
// A sample of another voice is stale; a late answer for it is dropped.
watch(voiceKey, () => { previewRequest++; previewPhase.value = ''; previewAudio.value = ''; previewError.value = '' })
async function previewVoice() {
  const request = ++previewRequest
  const tts = profile.value.tts
  previewAudio.value = ''; previewError.value = ''
  try {
    previewPhase.value = 'synthesizing'
    if (tts.type === 'breezyvoice' && !(await breezyVoiceServerReady(tts))) {
      if (request === previewRequest) previewPhase.value = 'starting'
    }
    const audio = await previewProfileVoice(tts)
    if (request === previewRequest) previewAudio.value = audio
  } catch (error) {
    if (request === previewRequest) previewError.value = error.message || String(error)
  } finally {
    if (request === previewRequest) previewPhase.value = ''
  }
}
const endpointOptions = computed(() => {
  const listed = props.endpoints || []
  const current = profile.value.llm.endpoint
  // Keep an unlisted saved name visible so the admin sees what must be changed.
  return current && !listed.some(e => e.name === current) ? [...listed, { name: current, label: '未列於伺服器設定' }] : listed
})
const selectedEndpoint = computed(() => (props.endpoints || []).find(e => e.name === profile.value.llm.endpoint))
const modelNames = computed(() => (selectedEndpoint.value?.models || []).map(m => typeof m === 'string' ? m : m.name || m.id).filter(Boolean))
const EDITOR_HEIGHT_STORAGE_KEY = STORAGE_KEYS.editorHeights
const defaults = { prompt: 200, activation: 120, speech: 120, board: 120 }
function loadHeights() {
  try {
    const stored = JSON.parse(readMigratedStorage(localStorage, EDITOR_HEIGHT_STORAGE_KEY, LEGACY_STORAGE_KEYS.editorHeights) || '{}')
    return Object.fromEntries(Object.entries(defaults).map(([key, fallback]) => [key, Number.isFinite(stored[key]) && stored[key] >= 72 && stored[key] <= 1600 ? stored[key] : fallback]))
  } catch { return { ...defaults } }
}
const editorHeights = ref(loadHeights())
function rememberEditorHeight(event) {
  const key = event.currentTarget.dataset.editorKey
  const height = Math.round(parseFloat(getComputedStyle(event.currentTarget).height))
  if (!key || !Number.isFinite(height) || height < 72) return
  editorHeights.value = { ...editorHeights.value, [key]: height }
  try { localStorage.setItem(EDITOR_HEIGHT_STORAGE_KEY, JSON.stringify(editorHeights.value)) } catch { /* Storage can be unavailable in private browsing. */ }
}
defineExpose({ openSection: value => { section.value = value } })
</script>

<style scoped>
.profile-sections{display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--border-default);padding-bottom:18px}.profile-sections button{display:flex;gap:7px;align-items:center}.profile-sections button[aria-pressed=true]{border-color:var(--brand-light);color:var(--brand-light);background:var(--bg-surface-elevated)}.profile-section{padding-top:24px}.profile-section h3{font-size:18px;margin:0 0 10px}.profile-section h4{font-size:15px;margin:16px 0}.profile-section p{font-size:13px;line-height:1.7;color:var(--text-secondary)}.profile-section label{display:flex;flex-direction:column;gap:8px;margin:16px 0;font-size:13px}.profile-section .profile-check{flex-direction:row;align-items:center}.profile-section .profile-alert{color:var(--warning);font-weight:600}.profile-section .profile-alert[role=alert]{color:var(--danger)}.profile-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 20px}.profile-section input,.profile-section textarea,.profile-section select{width:100%;padding:10px 12px;border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--bg-input);color:var(--text-primary);font:inherit;box-sizing:border-box}.profile-section .profile-check input{width:auto}.profile-section textarea{resize:vertical;min-height:90px}.profile-section small{font-size:12px;color:var(--text-secondary)}.profile-heading{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}.profile-editor button{padding:9px 12px;border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--bg-surface);color:var(--text-primary);font-size:13px;cursor:pointer}.profile-editor :focus-visible{outline:2px solid var(--focus-ring);outline-offset:3px}.profile-editor summary{font-size:13px;cursor:pointer;padding:12px 0}@media(min-width:1280px) and (min-height:640px){.profile-sections{position:sticky;top:0;z-index:2;margin-top:-12px;padding-top:12px;background:var(--bg-surface)}}
.profile-preview{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0;font-size:13px;color:var(--text-secondary)}.profile-preview button{display:flex;gap:7px;align-items:center}.profile-preview button:disabled{opacity:.55;cursor:not-allowed}.profile-section audio{display:block;width:100%;max-width:420px;margin:8px 0 16px}
@media(max-width:700px){.profile-grid{grid-template-columns:1fr}.profile-sections button{flex:1;justify-content:center}}
</style>
