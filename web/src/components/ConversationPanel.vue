<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section class="conversation-panel" aria-labelledby="conversation-heading" :aria-busy="saving">
    <div class="conversation-overview">
    <div class="conversation-heading">
      <h2 id="conversation-heading">對話記憶與語系</h2>
      <label>檢視與控制場次
        <select v-model="target" class="std-select" :disabled="saving">
          <option value="defaults">新對話預設</option>
          <option v-for="item in sessions" :key="item.sessionid" :value="String(item.sessionid)">
            {{ item.role === 'stage' ? '數字人舞台' : '控制台對話' }} #{{ item.sessionid }}{{ item.sessionid === sessionId ? '（目前控制台）' : '' }}
          </option>
        </select>
      </label>
    </div>
    <label v-if="selected?.profiles?.length">檢視角色記憶
      <select v-model="profileTarget" class="std-select"><option v-for="p in selected.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select>
    </label>
    <div v-if="selected" class="memory-summary" aria-live="polite">
      <div><span class="metric-label">目前保留的歷史訊息</span><strong>{{ memory.retained_messages }} / {{ memory.max_messages }} <small>則</small></strong></div>
      <div><span class="metric-label">較早已移出記憶</span><strong>{{ memory.evicted_messages }} <small>則</small></strong></div>
      <p class="memory-note">{{ selected.full_reset_seconds > 0 ? `此場對話閒置 ${selected.idle_reset_seconds} 秒清字幕與看板；${selected.full_reset_seconds} 秒清空記憶、附件與草稿並返回主數位人` : '此場對話已停用自動清場，可手動清空。' }}</p>
      <p v-if="selected.pending_history_max_messages" class="memory-note">目前輪次結束後，保留上限改為 {{ selected.pending_history_max_messages }} 則。</p>
      <p v-if="memory.oldest_message" class="oldest-message">最早仍保留：第 {{ memory.oldest_message_number }} 則 · {{ memory.oldest_message.role === 'user' ? '使用者' : '助手' }}：{{ memory.oldest_message.content }}</p>
      <div class="context-meter">
        <div><span>最近一次請求的 Context{{ context?.estimated ? '（估算）' : '' }}</span><b>{{ context?.capacity ? `${context.input_tokens} + ${context.reserved_output_tokens} / ${context.capacity} tokens` : deployment.capacity ? `上限 ${deployment.capacity} tokens；尚未量測用量` : '實際容量未知' }}</b></div>
        <progress v-if="context?.capacity && !context.visual_tokens_unknown" :value="Math.min(100, context.usage_percent)" max="100" aria-label="輸入與預留回答占用的 Context 百分比"></progress>
        <p v-if="context" class="memory-note">聊天歷史約 {{ context.history_tokens }} · 其他輸入約 {{ context.other_input_tokens }} · 預留回答 {{ context.reserved_output_tokens }} tokens<span v-if="context.capacity && !context.visual_tokens_unknown"> · 剩餘 {{ context.remaining_tokens }}（已占用 {{ context.usage_percent }}%）</span></p>
        <p v-if="context?.visual_tokens_unknown" class="memory-note">圖片占用尚待模型回報，目前只顯示文字估算，無法確定剩餘空間。</p>
        <p v-if="context" class="memory-note">{{ context.model }} · {{ context.estimated ? '用量估算' : context.source }} · {{ new Date(context.observed_at * 1000).toLocaleTimeString('zh-TW') }}</p>
        <p v-else class="memory-note">尚無 LLM 請求用量；歷史訊息數與模型 Context 容量分開計算。</p>
        <p v-if="context?.over_capacity" class="conversation-error">Context 容量不足，請降低保留上限、縮短問題或清空對話。</p>
      </div>
    </div>
    <p v-else class="memory-note">預設只套用之後建立的新對話；不改變其他已連線場次。</p>
    </div>
    <!-- Open by default: on a 16:9 screen it fills the second column. -->
    <details class="conversation-settings" open>
    <summary>調整保留上限與語音</summary>
    <form class="conversation-form" @submit.prevent="save">
      <label>歷史訊息保留上限
        <input v-model.number="draft.history_max_messages" class="std-select" type="number" min="1" max="2000" step="1" required :disabled="saving" aria-describedby="history-limit-hint">
      </label>
      <label>回覆語系
        <select v-model="draft.locale" class="std-select" :disabled="saving"><option value="zh-TW">繁體中文</option><option value="en-US">English</option></select>
      </label>
      <label>中文聲音
        <select v-model="draft.voice_zh_tw" class="std-select" :disabled="saving"><option v-for="voice in voices['zh-TW']" :key="voice.id" :value="voice.id">{{ voice.label }}</option></select>
      </label>
      <label>英文聲音
        <select v-model="draft.voice_en_us" class="std-select" :disabled="saving"><option v-for="voice in voices['en-US']" :key="voice.id" :value="voice.id">{{ voice.label }}</option></select>
      </label>
      <p id="history-limit-hint" class="memory-note form-hint">使用者與助手各算一則，20 則通常約 10 組問答。調高上限不會恢復已移出的內容；Context 容量仍限制實際可用空間。</p>
      <button class="sample-btn" type="submit" :disabled="saving || !loaded || !dirty">{{ saving ? '正在套用…' : target === 'defaults' ? '儲存新對話預設' : '套用至此場次' }}</button>
      <button v-if="selected" class="sample-btn" type="button" :disabled="saving" @click="clearConversation">清空此場對話、附件與草稿</button>
      <p class="conversation-feedback" :class="{ 'conversation-error': error }" role="status">{{ error || feedback }}</p>
    </form>
    </details>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
const props = defineProps({ sessionId: { type: Number, default: 0 } })
const emit = defineEmits(['session-summary'])
const target = ref('defaults'), sessions = ref([]), voices = ref({}), defaults = ref({}), deployment = ref({})
const saving = ref(false), loaded = ref(false), error = ref(''), feedback = ref('')
const draft = reactive({ locale: 'zh-TW', history_max_messages: 20, voice_zh_tw: '', voice_en_us: '' })
const baseline = ref(''), selected = computed(() => sessions.value.find(s => String(s.sessionid) === target.value))
const profileTarget = ref('')
const memory = computed(() => selected.value?.profiles?.find(p => p.id === profileTarget.value)?.memory || selected.value?.profiles?.[0]?.memory || selected.value?.memory || {}), context = computed(() => memory.value.context)
const dirty = computed(() => JSON.stringify(draft) !== baseline.value)
watch(() => sessions.value.find(session => session.sessionid === props.sessionId), session => {
  emit('session-summary', session ? { sessionId: session.sessionid, locale: session.locale } : null)
}, { immediate: true })
let timer, disposed = false, refreshing = false, ownSession = 0
function fill() {
  const value = target.value === 'defaults' ? defaults.value : selected.value
  if (!value) return
  for (const key of Object.keys(draft)) draft[key] = value[key]
  draft.history_max_messages = value.pending_history_max_messages ?? value.history_max_messages
  baseline.value = JSON.stringify(draft)
}
watch(target, () => { error.value = ''; feedback.value = ''; fill() })
async function refresh() {
  if (disposed || refreshing || saving.value) return
  refreshing = true
  try {
    const response = await fetch('/api/conversations', { cache: 'no-store' })
    const result = await response.json()
    if (!response.ok || result.code !== 0) throw new Error(result.msg || '載入對話資訊失敗')
    if (disposed) return
    const preserveDraft = loaded.value && dirty.value
    sessions.value = result.data.sessions; voices.value = result.data.voices; defaults.value = result.data.defaults
    deployment.value = result.data.model_context || {}
    if (props.sessionId && props.sessionId !== ownSession && sessions.value.some(s => s.sessionid === props.sessionId)) {
      ownSession = props.sessionId; target.value = String(props.sessionId)
    }
    if (target.value !== 'defaults' && !selected.value) {
      target.value = 'defaults'; feedback.value = '原場次已結束，已切回新對話預設。'
    }
    if (!preserveDraft || !loaded.value) fill()
    loaded.value = true
  } catch (e) { if (!disposed) error.value = e.message }
  finally { refreshing = false }
}
async function save() {
  saving.value = true; error.value = ''; feedback.value = ''
  try {
    const response = await fetch(`/api/conversations/${target.value}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(draft) })
    const result = await response.json()
    if (!response.ok || result.code !== 0) throw new Error(({ english_requires_whisper: '英文對話需先在「訪客互動與語音辨識」套用 Whisper 辨識引擎', english_requires_edge_tts: '英文對話需要目前數位人使用 Edge TTS，請在數位人設定檔的「聲音與工具」改選並套用', voice_controls_require_edge_tts: '此聲音選擇適用 Edge TTS，請在數位人設定檔的「聲音與工具」改選 Edge TTS 並套用' })[result.msg] || result.msg || '套用失敗')
    baseline.value = JSON.stringify(draft)
    feedback.value = target.value === 'defaults' ? '已儲存，之後的新對話會使用此預設。' : '已套用；保留上限若有變更，會在目前輪次結束後生效。'
  } catch (e) { error.value = e.message }
  finally { saving.value = false; await refresh() }
}
async function clearConversation() {
  saving.value = true; error.value = ''; feedback.value = ''
  try {
    const response = await fetch(`/api/conversations/${target.value}/clear`, { method: 'POST' })
    const result = await response.json()
    if (!response.ok || result.code !== 0) throw new Error(result.msg || '清空失敗')
    feedback.value = '已清空此場對話、看板、附件與草稿。'
  } catch (e) { error.value = e.message }
  finally { saving.value = false; await refresh() }
}
onMounted(() => { refresh(); timer = setInterval(() => { if (!document.hidden) refresh() }, 3000) })
onUnmounted(() => { disposed = true; clearInterval(timer) })
</script>

<style scoped>
.conversation-panel{min-width:0;padding:24px;border:1px solid var(--border-default,#303642);border-radius:var(--radius-lg,14px);color:var(--text-primary,#dbe0e9);background:var(--bg-surface,transparent)}
summary{min-height:44px;padding:12px 0;font-size:13px;cursor:pointer}summary:focus-visible{outline:2px solid #83a8ff}
.conversation-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.conversation-heading h2{font-size:15px;margin:0;font-weight:700}.conversation-heading label{display:flex;align-items:center;gap:8px;font-size:12px;white-space:nowrap}
.std-select{min-height:44px;max-width:100%;width:100%;padding:8px;border:1px solid var(--border-default,#697386);border-radius:8px;background:var(--bg-input,#161b26);color:inherit}.std-select:focus-visible,.sample-btn:focus-visible{outline:2px solid #83a8ff;outline-offset:2px}
.memory-summary{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}.metric-label{display:block;font-size:12px;opacity:.8}.memory-summary strong{display:block;font-size:24px}.memory-summary small{font-size:13px;font-weight:400}.memory-note{font-size:12px;line-height:1.6;opacity:.85;margin:0}.oldest-message{font-size:12px;line-height:1.6;margin:0;overflow-wrap:anywhere;max-height:4.8em;overflow:auto;grid-column:1/-1}.context-meter{grid-column:1/-1}.context-meter>div{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;font-size:12px}.context-meter progress{display:block;width:100%;height:10px;margin:8px 0;accent-color:#7c9cff}.memory-summary>.memory-note{grid-column:1/-1}
.conversation-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:12px}.conversation-form label{display:flex;flex-direction:column;gap:6px;font-size:12px}.form-hint,.conversation-feedback{grid-column:1/-1}.conversation-form button{min-height:44px;justify-self:start}.conversation-feedback{font-size:12px;margin:0}.conversation-error{color:var(--danger,#d85b50);opacity:1}.sample-btn:disabled{opacity:.55;cursor:default}
@media(min-width:1280px) and (min-height:640px){.conversation-panel{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:0 28px;align-items:start}.conversation-settings{padding-left:28px;border-left:1px solid var(--border-subtle,#262c38)}.conversation-settings>summary{padding-top:0}}
@media(max-width:560px){.conversation-panel{padding:14px}.conversation-heading label{width:100%;flex-wrap:wrap}.conversation-form{grid-template-columns:1fr}.memory-summary strong{font-size:20px}}
</style>
