<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section class="idle-greeting-settings" :aria-busy="busy" aria-labelledby="idle-greeting-settings-title">
    <header class="page-heading">
      <div><h2 id="idle-greeting-settings-title">閒置招呼</h2><p>在這一頁設定自動招呼的開關、時間、內容與 AI Prompt，並預覽或試播。</p></div>
      <div class="actions"><button type="button" :disabled="busy" @click="load">{{ dirty ? '放棄修改並重新載入' : '重新載入' }}</button><button type="button" class="primary" :disabled="busy || !profile || Boolean(validation)" @click="save">{{ busy ? '處理中…' : '儲存並套用招呼設定' }}</button></div>
    </header>
    <p v-if="error" class="feedback" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="!profile && busy" role="status">正在載入招呼設定…</p>
    <template v-if="profile">
      <p class="profile-context">目前主數位人：<strong>{{ profile.name }}</strong>。招呼內容隨這位數位人保存，開關與時間套用至整個舞台。</p>
      <fieldset :disabled="busy" class="schedule-fields">
        <legend>自動招呼</legend>
        <label class="check"><input id="greeting-enabled" type="checkbox" v-model="enabled">啟用閒置招呼</label>
        <label for="greeting-seconds">閒置多久開始準備招呼（秒）<input id="greeting-seconds" type="number" v-model.number="seconds" min="0" step="any" :aria-invalid="intervalInvalid" aria-describedby="greeting-interval-hint"></label>
        <p id="greeting-interval-hint">預設 30 秒。訪客互動會重新計時；先完成上一位訪客的清場，再準備一次招呼。AI 準備最多 15 秒，語音合成另計。</p>
      </fieldset>
      <IdleGreetingEditor :profile="profile" :disabled="busy" />
      <p v-if="validation" class="feedback" role="status">{{ validation }}</p>
      <div class="status-row"><span role="status">{{ statusText }}</span><button type="button" :disabled="busy" @click="refreshStatus">更新招呼狀態</button></div>
      <details class="mode-help"><summary>控制台試播會影響舞台嗎？</summary><p>控制台與舞台各自對話，試播草稿不暫停舞台收音或招呼。儲存的招呼內容由下一場舞台對話採用。</p></details>
      <div class="actions save-row"><span v-if="dirty">有尚未套用的招呼設定</span><button type="button" class="primary" :disabled="busy || Boolean(validation)" @click="save">{{ busy ? '處理中…' : '儲存並套用招呼設定' }}</button></div>
    </template>
  </section>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref, toRaw, watch } from 'vue'
import IdleGreetingEditor from './IdleGreetingEditor.vue'
import { useRoles } from '../composables/useRoles.js'
import { useRuntimeSettings } from '../composables/useRuntimeSettings.js'
import { greetingError } from '../greeting.js'
const props = defineProps({ active: Boolean })
const { roleRequest } = useRoles()
const { runtime } = useRuntimeSettings()
const activeProfile = ref(null)
const library = ref(null), enabled = ref(false), seconds = ref(60), published = ref('')
const busy = ref(false), error = ref(''), notice = ref(''), statuses = ref([])
const profile = computed(() => activeProfile.value)
const snapshot = () => JSON.stringify({ profile: profile.value?.greeting, main: profile.value?.id, enabled: enabled.value, seconds: seconds.value })
const dirty = computed(() => Boolean(profile.value && snapshot() !== published.value))
const intervalInvalid = computed(() => typeof seconds.value !== 'number' || !Number.isFinite(seconds.value) || seconds.value <= 0)
const validation = computed(() => {
  if (intervalInvalid.value) return '招呼間隔須為正數秒。'
  if (!profile.value) return ''
  const settings = profile.value.greeting
  if (!Number.isInteger(settings.min_chars) || !Number.isInteger(settings.max_chars) || settings.min_chars < 1 || settings.max_chars < settings.min_chars) return '請填寫有效的正整數字數範圍。'
  return enabled.value ? greetingError(settings) : ''
})
const statusText = computed(() => {
  if (!runtime.stage.idle_greeting_enabled) return '自動招呼尚未啟用。'
  const labels = { paused: '暫停／等待舞台、收音及有聲播放就緒', waiting: '等待閒置間隔', waiting_clear: '等待訪客清場及返回主角色', preparing: '準備招呼中', playing: '播放招呼中', failed: '本次已略過' }
  return statuses.value.map(item => `${labels[item.status] || item.status}${item.error ? '：' + item.error : ''}`).join('；') || '尚無訪客舞台連線。啟動舞台並允許收音與有聲播放後才會倒數。'
})
async function stageRequest(body) {
  const response = await fetch('/api/stage', body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' })
  const result = await response.json()
  if (!response.ok || result.code !== 0) throw Error(result.msg || '無法讀取或套用招呼設定')
  Object.assign(runtime.stage, result.data)
  if (result.greetings) statuses.value = result.greetings
  return result.data
}
async function load() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const [roles, stage] = await Promise.all([roleRequest(), stageRequest()])
    library.value = structuredClone(roles.library)
    activeProfile.value = structuredClone(roles.greeting_profile || roles.library.profiles.find(p => p.id === roles.library.pair.main))
    enabled.value = Boolean(stage.idle_greeting_enabled)
    seconds.value = Number(stage.idle_greeting_seconds ?? 60)
    published.value = snapshot()
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function save() {
  if (!profile.value || validation.value || busy.value) return
  busy.value = true; error.value = ''; notice.value = ''
  let savedContent = false
  try {
    // Disable first so an intentionally empty, disabled draft can be applied.
    if (!enabled.value && runtime.stage.idle_greeting_enabled) await stageRequest({ idle_greeting_enabled: false })
    const savedProfile = library.value.profiles.find(p => p.id === profile.value.id)
    if (!savedProfile) throw Error('主數位人設定已變更，請重新載入。')
    savedProfile.greeting = structuredClone(toRaw(profile.value.greeting))
    const result = await roleRequest('', 'PUT', { library: library.value, expected_revision: library.value.revision })
    library.value.revision = result.library.revision
    savedContent = true
    await roleRequest('/greeting/apply', 'POST', { profile_id: profile.value.id, expected_revision: library.value.revision })
    await stageRequest({ idle_greeting_enabled: enabled.value, idle_greeting_seconds: seconds.value })
    published.value = snapshot()
    notice.value = '招呼設定已儲存，內容由下一場舞台對話採用；開關與間隔已更新。'
    await refreshStatus()
  } catch (e) { error.value = `${savedContent ? '招呼內容已儲存，尚未完成全部套用，請重試。' : ''}${e.message}` }
  finally { busy.value = false }
}
async function refreshStatus() {
  try { await stageRequest() } catch (e) { error.value = e.message }
}
watch(() => props.active, active => { if (active && !busy.value && !dirty.value) load() })
let statusTimer
onMounted(() => { load(); statusTimer = setInterval(() => { if (props.active && !busy.value) refreshStatus() }, 5000) })
onUnmounted(() => clearInterval(statusTimer))
defineExpose({ dirty })
</script>
<style scoped>
.idle-greeting-settings{color:var(--text-primary);max-width:1100px}.page-heading,.actions,.status-row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.page-heading h2{font-size:24px;margin:0 0 10px}.idle-greeting-settings p{font-size:13px;line-height:1.8;color:var(--text-secondary)}.idle-greeting-settings button{min-height:40px;padding:10px 14px;border:1px solid var(--border-default);border-radius:8px;background:var(--bg-surface);color:var(--text-primary);cursor:pointer}.idle-greeting-settings button.primary{background:var(--brand-light);color:var(--bg-base,#111827);font-weight:600}.idle-greeting-settings button:disabled{opacity:.5;cursor:default}.profile-context,.schedule-fields,.status-row,.mode-help{padding:18px;margin-top:20px;border:1px solid var(--border-default);border-radius:12px;background:var(--bg-surface)}.schedule-fields legend{font-size:16px}.schedule-fields label{display:flex;flex-direction:column;gap:10px;margin:12px 0;font-size:14px}.schedule-fields .check{flex-direction:row;align-items:center}.schedule-fields input[type=number]{max-width:260px;padding:10px;border:1px solid var(--border-default);border-radius:8px;background:var(--bg-surface-elevated);color:var(--text-primary);font:inherit}.feedback{padding:12px;border-left:3px solid var(--warning);color:var(--text-primary)}.save-row{margin-top:24px;justify-content:flex-end}.mode-help summary{cursor:pointer}.idle-greeting-settings :focus-visible{outline:2px solid var(--brand-light);outline-offset:3px}@media(max-width:700px){.page-heading .actions{width:100%}.schedule-fields input[type=number]{max-width:none;width:100%;box-sizing:border-box}}
</style>
