<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
<template>
  <section class="setting-card prerecorded-settings" aria-labelledby="presentation-title">
    <h3 id="presentation-title">數位人呈現方式</h3>
    <p>同一角色可選即時嘴型或預錄影片。預錄說話動作不逐字同步，回答仍使用目前的聲音。</p>
    <div v-if="loading" role="status">正在載入素材設定…</div>
    <template v-else-if="data">
      <fieldset :disabled="busy || data.busy" :aria-busy="busy">
        <legend>這位數位人的呈現方式</legend>
        <label class="mode-option"><input type="radio" name="avatar-presentation" value="musetalk" v-model="modeDraft">MuseTalk 即時嘴型</label>
        <label class="mode-option"><input type="radio" name="avatar-presentation" value="prerecorded" v-model="modeDraft" :disabled="!data.ready">預錄呈現</label>
      </fieldset>
      <label class="hint" v-if="isCurrent"><input type="checkbox" v-model="autoReconnect" :disabled="busy">切換時自動重新連線控制台與舞台（會結束目前對話）</label>
      <button type="button" :disabled="busy || data.busy || modeDraft === data.mode || (!autoReconnect && data.active_sessions > 0)" @click="applyMode">{{ busy && !jobId ? '正在切換，請稍候…' : '套用呈現方式' }}</button>
      <p v-if="data.mode === 'prerecorded' && data.ready" class="hint">預錄畫質：{{ data.slots.idle.current.width }}×{{ data.slots.idle.current.height }}，保留上傳影片原始尺寸。</p>
      <p v-if="!data.ready" class="hint">{{ data.reason }}。先上傳、預覽並套用兩支影片。</p>
      <p class="hint">目前有 {{ data.active_sessions }} 個連線。關閉自動重連時，請先斷開控制台與舞台再切換；套用素材與製作影片仍需先斷線。</p>
      <div class="asset-grid">
        <div v-for="slot in ['idle', 'talking']" :key="slot" class="asset-slot">
          <h4>{{ slot === 'idle' ? '待機影片' : '說話影片' }}</h4>
          <video v-if="asset(slot)" :key="asset(slot).url" :src="asset(slot).url" controls muted loop playsinline preload="metadata" :aria-label="`${slot === 'idle' ? '待機' : '說話'}素材預覽`"></video>
          <div v-else class="empty-preview">尚未上傳</div>
          <p class="hint" v-if="asset(slot)">{{ asset(slot).width }}×{{ asset(slot).height }} · 25 fps · {{ asset(slot).duration.toFixed(2) }} 秒{{ data.slots[slot].candidate ? ' · 待套用' : ' · 使用中' }}</p>
          <label :for="`presentation-upload-${slot}`">上傳 MP4</label>
          <input :id="`presentation-upload-${slot}`" type="file" accept="video/mp4,.mp4" :disabled="busy" @change="upload(slot, $event)">
          <div class="actions">
            <button v-if="data.slots[slot].candidate" type="button" :disabled="busy || data.active_sessions > 0" @click="applySlot(slot)">套用為{{ slot === 'idle' ? '待機' : '說話' }}影片</button>
            <button v-if="data.slots[slot].previous" type="button" :disabled="busy || data.active_sessions > 0" @click="applySlot(slot, true)">還原上一版</button>
            <button v-if="asset(slot)" type="button" :disabled="Boolean(downloading)" @click="downloadSlot(slot)">{{ downloading === slot ? '正在下載…' : '下載素材' }}</button>
          </div>
        </div>
      </div>
      <p class="hint">上限 100 MB、十分鐘、4K。兩支影片須相同人物、尺寸、構圖與綠幕；原音會移除。循環接縫請以預覽確認。</p>
      <div v-if="data.ready" class="combined-preview">
        <div class="actions">
          <button type="button" :disabled="busy" @click="previewScene('idle')">預覽待機與背景</button>
          <button type="button" :disabled="busy" @click="previewScene('talking')">預覽說話與背景</button>
          <button v-if="preview" type="button" @click="closePreview">關閉預覽</button>
        </div>
        <div v-show="preview" class="preview-stage"><video ref="previewTransport" muted playsinline></video></div>
      </div>
      <div class="production">
        <h4>錄製 5 秒說話素材</h4>
        <label for="speaking-asset-text">朗讀文字</label>
        <textarea id="speaking-asset-text" v-model="text" rows="3" maxlength="1000" :disabled="busy" aria-describedby="speaking-asset-hint"></textarea>
        <p id="speaking-asset-hint" class="hint">使用完整品質 MuseTalk 離線製作。五秒是影片長度，製作可能超過五秒；文字不足五秒會提示加長，超過則取前五秒。</p>
        <button type="button" :disabled="busy || data.busy || data.active_sessions > 0 || !text.trim() || !isCurrent || engine !== 'musetalk'" @click="generate">製作 5 秒說話影片</button>
        <p v-if="!isCurrent" class="hint">請先套用這位角色，再製作說話素材。</p>
      </div>
      <div v-if="busy" class="job-progress" role="status" aria-live="polite">
        <label for="speaking-job-progress">{{ progressLabel }}</label>
        <progress id="speaking-job-progress" max="100" :value="progress"></progress>
        <span>{{ progress }}%</span>
        <button v-if="jobId" type="button" @click="cancel">取消工作</button>
      </div>
      <p v-if="message" role="status">{{ message }}</p>
    </template>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
  </section>
</template>

<script setup>
import { downloadMedia } from '../mediaDownload.js'
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { presentationRequest, waitPresentationJob, mountPresentation, presentationPlayer } from '../prerecordedPlayer.js'

const props = defineProps({ avatarId: String, engine: String, isCurrent: Boolean })
const emit = defineEmits(['applied', 'loaded'])
const modeDraft = ref(''), autoReconnect = ref(true), downloading = ref('')
const data = ref(null), loading = ref(false), busy = ref(false), error = ref(''), message = ref('')
const progress = ref(0), progressLabel = ref(''), jobId = ref(''), preview = ref(false), previewTransport = ref(null)
const text = ref('您好，我是您的數位助理，很高興為您服務。請告訴我您想了解的問題，我會盡力提供清楚的回答。')
let previewPlayer = null
let previewToken = 0
let disposed = false
let pollToken = 0
const asset = (slot) => data.value?.slots[slot]?.candidate || data.value?.slots[slot]?.current
const key = (id) => `nova-speaking-job:${id}`
const endpoint = () => `/api/presentation/${encodeURIComponent(props.avatarId)}`

async function load() {
  if (!props.avatarId) { data.value = null; return }
  const id = props.avatarId
  const result = await presentationRequest(endpoint())
  if (!disposed && id === props.avatarId) {
    if (!modeDraft.value || modeDraft.value === data.value?.mode) modeDraft.value = result.mode
    data.value = result
    emit('loaded', result)
  }
}

async function action(params) {
  const id = props.avatarId
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''; progressLabel.value = '正在套用呈現設定…'; closePreview()
  try {
    const result = await presentationRequest(endpoint(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) })
    if (id === props.avatarId && !disposed) { data.value = result; modeDraft.value = result.mode; message.value = params.reconnect ? '設定已套用，控制台與舞台正在自動重新連線。' : '設定已套用，請重新連線。'; emit('loaded', result) }
    emit('applied')
  } catch (failure) { if (id === props.avatarId && !disposed) { error.value = failure.message; await load().catch(() => {}) } }
  finally { if (id === props.avatarId && !disposed) busy.value = false }
}
const applyMode = () => action({ mode: modeDraft.value, reconnect: props.isCurrent && autoReconnect.value })
const applySlot = (slot, restore = false) => action({ action: restore ? 'restore' : 'apply', slot })

async function downloadSlot(slot) {
  downloading.value = slot; error.value = ''
  const item = asset(slot)
  try { await downloadMedia(item.url, `${props.avatarId}-${slot}.mp4`) }
  catch (failure) { error.value = failure.message }
  finally { downloading.value = '' }
}

async function observe(job, id) {
  const token = ++pollToken
  jobId.value = job.id
  localStorage.setItem(key(id), job.id)
  try {
    await waitPresentationJob(job, (current) => {
      if (disposed || token !== pollToken) return
      progress.value = current.progress
      progressLabel.value = current.kind === 'generate' ? '正在製作完整品質說話影片' : '正在準備影片'
    })
    if (!disposed && token === pollToken) {
      message.value = '素材已完成。請先預覽，再按套用；原有影片尚未替換。'
      await load()
    }
  } catch (failure) { if (!disposed && token === pollToken) error.value = failure.message }
  finally {
    localStorage.removeItem(key(id))
    if (token === pollToken) { busy.value = false; jobId.value = '' }
  }
}

async function upload(slot, event) {
  const id = props.avatarId
  const file = event.target.files[0]
  if (!file) return
  event.target.value = ''
  if (!file.name.toLowerCase().endsWith('.mp4') || file.size > 100 * 1024**2) { error.value = '請選擇不超過 100 MB 的 MP4'; return }
  busy.value = true; error.value = ''; message.value = ''; closePreview()
  try {
    const form = new FormData(); form.append('file', file)
    const job = await presentationRequest(`${endpoint()}/upload/${slot}`, { method: 'POST', body: form })
    if (id === props.avatarId && !disposed) await observe(job, id)
    else localStorage.setItem(key(id), job.id)
  } catch (failure) { error.value = failure.message; busy.value = false }
}

async function generate() {
  const id = props.avatarId
  busy.value = true; error.value = ''; message.value = ''; closePreview()
  try {
    const job = await presentationRequest(`${endpoint()}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text.value }) })
    if (id === props.avatarId && !disposed) await observe(job, id)
    else localStorage.setItem(key(id), job.id)
  } catch (failure) { error.value = failure.message; busy.value = false }
}

async function cancel() {
  try { await presentationRequest(`/api/presentation/jobs/${jobId.value}/cancel`, { method: 'POST' }); progressLabel.value = '正在取消並釋放資源…' }
  catch (failure) { error.value = failure.message }
}

function closePreview() {
  previewToken++
  presentationPlayer(previewTransport.value)?.dispose()
  previewPlayer = null
  preview.value = false
}
async function previewScene(state) {
  try {
    if (!previewPlayer) {
      const token = ++previewToken
      preview.value = true
      await nextTick()
      if (disposed || token !== previewToken) return
      const player = await mountPresentation(previewTransport.value, { ...data.value, mode: 'prerecorded' }, (failure) => { if (token === previewToken) error.value = failure })
      if (disposed || token !== previewToken) { player?.dispose(); return }
      previewPlayer = player
    }
    previewPlayer.previewState = state
  } catch (failure) { error.value = failure.message }
}

watch(() => props.avatarId, async (id) => {
  closePreview(); pollToken++; busy.value = false; jobId.value = ''; error.value = ''; message.value = ''
  modeDraft.value = ''
  loading.value = true
  try {
    await load()
    const previous = localStorage.getItem(key(id))
    if (previous) { busy.value = true; observe({ id: previous }, id) }
  } catch (failure) { error.value = failure.message }
  finally { loading.value = false }
}, { immediate: true })
const refresh = setInterval(() => { if (!busy.value && !loading.value) load().catch(() => {}) }, 2000)
onBeforeUnmount(() => { disposed = true; clearInterval(refresh); closePreview() })
</script>

<style scoped>
.prerecorded-settings { color: var(--text-primary); }
h3,h4 { margin: 0 0 12px; }
p { line-height: 1.6; }
fieldset { border: 1px solid var(--border-default); border-radius: var(--radius-md); padding: 12px; display: flex; flex-wrap: wrap; gap: 16px; }
.mode-option { display: flex; gap: 10px; align-items: center; min-height: 44px; cursor: pointer; }
.asset-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; margin: 20px 0; }
.asset-slot { min-width: 0; padding: 16px; background: var(--bg-input); border: 1px solid var(--border-default); border-radius: var(--radius-md); }
.asset-slot video,.empty-preview { display: block; width: 100%; height: 220px; object-fit: contain; background: var(--bg-surface); border-radius: var(--radius-md); }
.empty-preview { display: grid; place-items: center; }
.hint { color: var(--text-secondary); font-size: 13px; }
label { display: block; margin-bottom: 8px; }
input[type=file] { width: 100%; min-height: 44px; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 12px; }
button,a { min-height: 44px; padding: 10px 14px; border: 1px solid var(--border-default); border-radius: var(--radius-md); color: var(--text-primary); background: var(--bg-surface); cursor: pointer; }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible { outline: 2px solid var(--brand); outline-offset: 3px; }
textarea { width: 100%; padding: 12px; color: var(--text-primary); background: var(--bg-input); border: 1px solid var(--border-default); border-radius: var(--radius-md); resize: vertical; }
.production { border-top: 1px solid var(--border-default); padding-top: 20px; margin-top: 20px; }
.job-progress { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 16px; }
progress { flex: 1; min-width: 160px; accent-color: var(--brand); }
.error { color: var(--danger); }
.preview-stage { position: relative; height: 320px; background: var(--bg-input); margin-top: 12px; }
.preview-stage > video { position: absolute; width: 1px; height: 1px; }
@media(max-width:640px) { .asset-grid { grid-template-columns: 1fr; } }
</style>
