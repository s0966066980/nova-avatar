<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section v-show="enabled" ref="root" class="conversation-composer" :class="{ 'stage-composer': stage, 'composer-preview': preview }"
    :style="stage ? placement : {}" @dragover.prevent @drop.prevent="drop" @paste="paste"
    @focusin="edit(true)" @focusout="focusOut">
    <label class="composer-label" :for="inputId">{{ tr('問題與附件', 'Question and attachments') }}</label>
    <div class="composer-body">
    <textarea :id="inputId" v-model="text" rows="2" :placeholder="placeholder"
      :disabled="preview || !connected" @input="touch" @keydown="keydown"></textarea>
    <div v-if="draft.length" class="composer-files" :aria-label="tr('未送出附件', 'Unsent attachments')">
      <div v-for="(item, index) in draft" :key="item.key" class="composer-file">
        <img v-if="item.preview" :src="item.preview" :alt="item.file.name">
        <span>{{ item.file.name }} · {{ (item.file.size / 1e6).toFixed(1) }} MB</span>
        <button type="button" :disabled="sending" @click="removeDraft(index)" :aria-label="tr('移除', 'Remove') + ' ' + item.file.name">×</button>
      </div>
    </div>
    <details v-if="files.length" class="composer-references">
      <summary>{{ tr('本輪參考附件', 'Attachments for this question') }} · {{ selected.length }}/4 · {{ (bytes / 1e6).toFixed(1) }}/200 MB</summary>
      <div class="composer-reference-list">
        <div v-for="file in files" :key="file.id" class="composer-file">
          <label><input type="checkbox" :checked="selected.some(item => item.id === file.id)"
            :disabled="sending || !connected" @change="toggle(file, $event.target.checked)"> {{ file.name }}</label>
          <input v-if="file.kind === 'pdf' && selected.some(item => item.id === file.id)" class="composer-pages"
            :aria-label="tr('頁碼', 'Pages') + ': ' + file.name" :placeholder="`1-${file.pages}`"
            :value="selected.find(item => item.id === file.id)?.pages" :disabled="sending || !connected"
            @change="pages(file.id, $event.target.value)">
          <button type="button" :disabled="sending || !connected" @click="removeFile(file.id)" :aria-label="tr('刪除附件', 'Delete attachment') + ': ' + file.name">×</button>
        </div>
      </div>
    </details>

    <p class="composer-help" v-if="connected && !ready">{{ tr('附件分析尚未就緒：請載入相容的本機視覺模型。仍可文字對話。', 'Attachments unavailable: load a compatible local vision model. Text chat is available.') }}</p>
    <p class="composer-help" v-else-if="ready || preview">{{ tr('每輪最多 4 個、單檔 20 MB；每場最多 20 個／200 MB。PDF 每輪最多 40 頁，可選頁碼。', 'Up to 4 files per question, 20 MB each; 20 files / 200 MB per session. Up to 40 PDF pages per question; choose a page range.') }}</p>
    <p v-if="!connected && !preview" class="composer-help">{{ tr('連線後可使用文字與附件。', 'Connect to use text and attachments.') }}</p>
    <p v-if="status" class="composer-status" role="status" aria-live="polite">{{ status }}</p>
    <p v-if="lastSources.length" class="composer-help">{{ tr('分析來源：', 'Analyzed sources: ') }}{{ lastSources.join(' · ') }}</p>
    <p v-if="error" class="composer-error" role="alert">{{ error }}</p>
    </div>
    <div class="composer-actions">
      <input ref="picker" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" multiple hidden @change="pick" @cancel="edit(false)">
      <button type="button" :disabled="preview || !connected || !ready || sending" @click="openPicker">{{ tr('附加 PDF／圖片', 'Attach PDF / image') }}</button>
      <button v-if="sending || active" type="button" @click="cancel">{{ tr('取消', 'Cancel') }}</button>
      <button type="button" class="composer-send" :disabled="preview || !connected || (!text.trim() && !draft.length && !selected.length)" @click="send">{{ tr('送出', 'Send') }}</button>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { attachmentRequest, composerDefaults, composerGeometry, composerPlacement, shouldSend, validateDraft } from '../conversationAttachments.js'

const props = defineProps({ sessionId: { type: Number, default: 0 }, connected: Boolean,
  locale: { type: String, default: 'zh-TW' }, stage: Boolean, preview: Boolean, enabled: { type: Boolean, default: true },
  settings: { type: Object, default: () => ({ ...composerDefaults }) }, modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'submitting', 'accepted', 'submission-finished', 'editing', 'layout'])
const text = ref(props.modelValue), root = ref(null), picker = ref(null), draft = ref([])
const files = ref([]), selected = ref([]), bytes = ref(0), ready = ref(false), sending = ref(false)
const status = ref(''), error = ref(''), active = ref(false), placement = ref({})
const lastSources = ref([])
let acceptedSources = []
const inputId = `composer-${crypto.randomUUID()}`
let request = null, requestId = null, ownedTurnId = null, conversationBusy = false
let epoch = 0, operation = 0, retry = null, timer = null, poll = null, observer = null, lastTouch = 0
let selectionRevision = 0, preserveSelection = false, selectionWrites = Promise.resolve()
const selectionPending = new Set()
let editing = false
const tr = (zh, en) => props.locale === 'en-US' ? en : zh
const placeholder = computed(() => props.locale === 'en-US' ? props.settings.composer_placeholder_en : props.settings.composer_placeholder_zh)
const path = () => `/api/conversations/${props.sessionId}`
const json = (body) => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const messages = {
  reference_limit: ['每輪最多四個附件（包含已選附件）。', 'Choose at most four attachments, including existing files.'],
  file_size: ['單檔須為 1 byte–20 MB。', 'Each file must be between 1 byte and 20 MB.'],
  unsupported_file: ['支援 PDF、JPG、PNG、WebP。', 'Supported formats: PDF, JPG, PNG, WebP.'],
  invalid_file: ['檔案無法讀取，請更換檔案。', 'Unable to read this file. Choose another file.'],
  encrypted_pdf: ['請先解密 PDF 再上傳。', 'Decrypt the PDF before uploading.'],
  session_quota: ['本場已達 20 個附件或 200 MB，請先刪除舊檔。', 'Session limit reached (20 files / 200 MB). Delete an earlier file.'],
  invalid_pages: ['頁碼無效，請使用例如 1-3,5。', 'Invalid pages. Use a range such as 1-3,5.'],
  page_limit: ['每輪最多 40 頁，請選擇較小的頁碼範圍。', 'Choose a smaller range (up to 40 pages per question).'],
  pixel_limit: ['圖片超過 2400 萬像素，請先縮小。', 'Resize the image to at most 24 megapixels.'],
  missing_attachment: ['附件已移除或場次已變更，請重新上傳。', 'Attachment removed or session changed. Upload it again.'],
  session_reset: ['對話已清空，請重新選取附件。', 'Conversation cleared. Select your files again.'],
  composer_disabled: ['舞台文字與附件輸入已關閉。', 'Stage text and attachment input is disabled.'],
  vision_unavailable: ['本機視覺分析尚未就緒，請稍後重試。', 'Local vision is not ready. Try again later.'],
  analysis_capacity: ['分析內容超過模型容量，請縮小頁碼範圍。', 'Analysis exceeds model capacity. Choose fewer pages.'],
  analysis_unreadable: ['未能取得可靠的頁面分析，請指定較小頁碼範圍或重試。', 'Unable to read the page reliably. Choose a smaller page range or retry.'],
  context_capacity: ['對話內容超過模型容量，請減少參考頁面、縮短問題或清空對話。', 'Context is full. Select fewer pages, shorten the question or clear the conversation.'],
  pipeline_error: ['分析或回覆失敗，已保留問題與附件，可修改後重試。', 'Analysis or reply failed. Your question and attachments are available for retry.']
}
function fail(value) { error.value = messages[value]?.[props.locale === 'en-US' ? 1 : 0] || value }
let lastLayout = ''
function layout() {
  if (!props.stage || !root.value?.parentElement) return
  const canvas = root.value.closest?.('[data-composer-canvas]') || root.value.closest?.('.stage') || root.value.parentElement
  const parent = canvas.getBoundingClientRect()
  const width = canvas.clientWidth || parent.width, height = canvas.clientHeight || parent.height
  if (!width || !height) return
  const viewport = props.preview ? null : window.visualViewport
  const bottom = viewport ? Math.min(parent.bottom, viewport.offsetTop + viewport.height) : parent.bottom
  const top = Math.max(parent.top, viewport?.offsetTop || 0)
  const options = { availableHeight: Math.max(64, bottom - top) }
  const box = composerGeometry(props.settings, width, height, options)
  box.top += Math.max(0, top - parent.top)
  placement.value = { ...composerPlacement(props.settings, width, height, options), top: `${box.top}px` }
  const next = JSON.stringify(box)
  if (next !== lastLayout) { lastLayout = next; emit('layout', box) }
}

function deadline() {
  clearTimeout(timer)
  if (props.stage && !conversationBusy && !sending.value) timer = setTimeout(() => reset(), (props.settings.idle_reset_seconds || 60) * 1000)
}
function touch() {
  if (root.value?.contains(document.activeElement)) edit(true)
  deadline()
  if (!props.connected || Date.now() - lastTouch < 500) return
  lastTouch = Date.now()
  attachmentRequest(path() + '/interaction', json({ editing: root.value?.contains(document.activeElement), has_draft: Boolean(text.value.trim() || draft.value.length) })).catch(() => {})
}
function edit(value) {
  if (editing === value) return
  editing = value; emit('editing', value)
  if (props.connected) attachmentRequest(path() + '/interaction', json({ editing: value, has_draft: Boolean(text.value.trim() || draft.value.length) })).catch(() => {})
  deadline()
}
function focusOut(event) { if (!root.value?.contains(event.relatedTarget)) edit(false) }
function add(values) {
  if (sending.value) return
  error.value = ''
  try {
    if (!ready.value) throw new Error('vision_unavailable')
    const all = [...draft.value.map(item => item.file), ...values]
    validateDraft(all, oldReferenceCount())
    for (const file of values) draft.value.push({ file, key: crypto.randomUUID(), preview: file.type.startsWith('image/') ? URL.createObjectURL(file) : '' })
    touch()
  } catch (exc) { fail(exc.message) }
}
function openPicker() { edit(true); picker.value.click() }
function pick(event) { add([...event.target.files]); event.target.value = ''; edit(false) }
function drop(event) { if (!sending.value && props.connected) add([...event.dataTransfer.files]) }
function paste(event) { const images = [...event.clipboardData.files].filter(file => file.type.startsWith('image/')); if (images.length) { event.preventDefault(); add(images) } }
function oldReferenceCount() { const pending = new Set(draft.value.map(item => item.uploadedId)); return selected.value.filter(item => !pending.has(item.id)).length }
function removeDraft(index) {
  const [item] = draft.value.splice(index, 1)
  if (item.preview) URL.revokeObjectURL(item.preview)
  if (item.uploadedId) { selected.value = selected.value.filter(file => file.id !== item.uploadedId); selectionRevision++; removeFile(item.uploadedId) }
  touch()
}
function clearDraft() { for (const item of draft.value) if (item.preview) URL.revokeObjectURL(item.preview); draft.value = [] }
async function refresh() {
  if (props.preview || !props.connected || !props.sessionId) return
  const identity = props.sessionId, generation = epoch, revision = selectionRevision
  try {
    const data = await attachmentRequest(path() + '/attachments')
    if (identity !== props.sessionId || generation !== epoch) return
    files.value = data.files; bytes.value = data.bytes; ready.value = data.vision_ready
    if (!sending.value && !selectionPending.size && !preserveSelection && revision === selectionRevision) selected.value = data.selection
  } catch (_) { /* Connection feedback is owned by the surrounding stage/console. */ }
}
async function saveSelection(next) {
  const before = selected.value, identity = props.sessionId, generation = epoch
  const revision = ++selectionRevision
  selected.value = next
  const token = Symbol('selection')
  selectionPending.add(token)
  const payload = next.map(item => ({ ...item }))
  const write = selectionWrites.catch(() => {}).then(async () => {
    if (identity !== props.sessionId || generation !== epoch) return
    await attachmentRequest(`/api/conversations/${identity}/attachments/selection`, json({ selection: payload }))
  })
  selectionWrites = write
  try { await write; if (generation === epoch && identity === props.sessionId) touch() }
  catch (exc) { if (generation === epoch && identity === props.sessionId && revision === selectionRevision) { selected.value = before; fail(exc.message) } }
  finally { selectionPending.delete(token) }
}
async function toggle(file, enabled) {
  const next = enabled ? [...selected.value, { id: file.id, pages: '' }] : selected.value.filter(item => item.id !== file.id)
  try { if (next.length + draft.value.filter(item => !item.uploadedId).length > 4) throw new Error('reference_limit'); await saveSelection(next) }
  catch (exc) { fail(exc.message) }
}
async function pages(id, value) { await saveSelection(selected.value.map(item => item.id === id ? { ...item, pages: value } : item)) }
async function removeFile(id) {
  const identity = props.sessionId, generation = epoch
  try { await attachmentRequest(path() + '/attachments/' + id, { method: 'DELETE' }); if (identity === props.sessionId && generation === epoch) { await refresh(); touch() } }
  catch (exc) { if (identity === props.sessionId && generation === epoch) fail(exc.message) }
}
function keydown(event) { if (window.matchMedia('(pointer: fine)').matches && shouldSend(event)) { event.preventDefault(); send() } }
async function send(preset) {
  if (props.preview || !props.connected) return false
  if (typeof preset === 'string') text.value = preset
  if (!text.value.trim() && !draft.value.length && !selected.value.length) return false
  const submissionOperation = ++operation
  const generation = epoch, identity = props.sessionId
  const current = () => generation === epoch && identity === props.sessionId && submissionOperation === operation
  if (sending.value) {
    const superseded = requestId
    request?.abort()
    emit('submission-finished', { requestId: superseded, error: '' })
    // Cancel by ID so a delayed old request cannot replace the new question.
    // The replacement is sent immediately, without waiting for this response.
    attachmentRequest('/interrupt_talk', json({ sessionid: identity, request_id: superseded })).catch(() => {})
  }
  const submittedText = text.value
  error.value = ''; sending.value = true; active.value = false; ownedTurnId = null
  status.value = ''
  const controller = new AbortController()
  request = controller; requestId = crypto.randomUUID(); deadline(); edit(true)
  const submissionId = requestId
  let submissionError = ''
  emit('submitting', { text: submittedText || tr('分析附件', 'Analyze attachments'), requestId: submissionId })
  try {
    await selectionWrites.catch(() => {})
    if (!current()) return
    validateDraft(draft.value.map(item => item.file), oldReferenceCount())
    if ((draft.value.length || selected.value.length) && !ready.value) throw new Error('vision_unavailable')
    const pending = draft.value.filter(item => !item.uploadedId)
    if (pending.length) {
      status.value = tr('正在上傳及檢查附件…', 'Uploading and checking attachments…')
      const body = new FormData(); for (const item of pending) body.append('files', item.file)
      const uploaded = await attachmentRequest(path() + '/attachments', { method: 'POST', body, signal: controller.signal })
      if (!current()) return
      pending.forEach((item, index) => { item.uploadedId = uploaded[index].id })
      files.value.push(...uploaded); selected.value.push(...uploaded.map(item => ({ id: item.id, pages: '' })))
      selectionRevision++; preserveSelection = true
    }
    retry = { text: submittedText, selection: selected.value.map(item => ({ ...item })) }
    const response = await attachmentRequest('/human', { ...json({ text: submittedText, type: 'chat', interrupt: true, sessionid: identity, attachments: retry.selection, request_id: submissionId }), signal: controller.signal })
    if (!current()) return
    const description = submittedText || tr('分析附件', 'Analyze attachments')
    acceptedSources = selected.value.map(item => {
      const file = files.value.find(file => file.id === item.id)
      return file ? file.name + (file.kind === 'pdf' ? ` (${tr('頁', 'pages')} ${item.pages || `1-${file.pages}`})` : '') : ''
    }).filter(Boolean)
    emit('accepted', { text: description, attachments: selected.value, turnId: response.turn_id, requestId: submissionId })
    if (text.value === submittedText) text.value = ''
    clearDraft(); preserveSelection = false
    ownedTurnId = response.turn_id; active.value = true; conversationBusy = true
    status.value = tr('正在讀取與分析…', 'Reading and analyzing…')
    return true
  } catch (exc) {
    if (current() && exc.name !== 'AbortError') { fail(exc.message); submissionError = error.value }
    return false
  }
  finally {
    emit('submission-finished', { requestId: submissionId, error: submissionError })
    if (current()) { sending.value = false; request = null; edit(false); deadline(); refresh() }
  }
}
async function cancel() {
  const identity = props.sessionId, token = requestId
  const cancellation = ++operation
  request?.abort(); const generation = ++epoch; sending.value = false
  if (token && props.connected) await attachmentRequest('/interrupt_talk', json({ sessionid: identity, request_id: token })).catch(() => {})
  if (identity !== props.sessionId || generation !== epoch || cancellation !== operation) return
  active.value = false; if (retry && !text.value) text.value = retry.text
  status.value = tr('已取消，可修改後重試。', 'Cancelled. Edit and retry.'); edit(false); deadline()
}
function reset() { epoch++; request?.abort(); request = null; requestId = null; ownedTurnId = null; conversationBusy = false; if (editing) { editing = false; emit('editing', false) } text.value = ''; clearDraft(); files.value = []; selected.value = []; lastSources.value = []; acceptedSources = []; preserveSelection = false; retry = null; active.value = false; sending.value = false; status.value = ''; error.value = ''; clearTimeout(timer) }
function receive(event) {
  if (event.type === 'conversation_reset') { reset(); refresh() }
  if (event.type === 'composer_disabled') { text.value = ''; clearDraft(); edit(false) }
  const owned = event.turn_id && event.turn_id === ownedTurnId
  if (owned && ['assistant_response_start', 'assistant_response'].includes(event.type)) lastSources.value = acceptedSources
  if (event.type === 'attachment_status') { conversationBusy = true; deadline(); if (owned || sending.value) status.value = `${tr('分析中', 'Analyzing')} ${event.index || 0}/${event.total}${event.source ? ' · ' + event.source : ''}` }
  if (event.type === 'state' && ['stt', 'retrieving', 'llm', 'tts_ready', 'avatar_speaking', 'tail_guard'].includes(event.state)) { conversationBusy = true; deadline() }
  if (event.type === 'state' && event.state === 'error') { conversationBusy = false; if (owned) { active.value = false; if (retry && !text.value) text.value = retry.text; fail(event.error || 'analysis_capacity') } deadline() }
  if (event.type === 'turn_committed' && owned) { active.value = false; if (event.reason === 'completed') { retry = null; status.value = '' } }
  if (event.type === 'state' && ['listening', 'paused'].includes(event.state) && !sending.value) { conversationBusy = false; deadline() }
  if (event.type === 'turn_cancelled' && owned) { active.value = false; conversationBusy = false; deadline() }
}
watch(() => props.modelValue, value => { if (value !== text.value) text.value = value })
watch(text, value => emit('update:modelValue', value))
watch(() => props.sessionId, (value, previous) => {
  if (value && value !== previous) {
    epoch++; request?.abort(); sending.value = false; active.value = false; conversationBusy = false
    files.value = []; selected.value = []; retry = null; requestId = null; ownedTurnId = null; preserveSelection = false
    lastSources.value = []; acceptedSources = []
    selectionWrites = Promise.resolve(); selectionPending.clear(); selectionRevision++
    for (const item of draft.value) delete item.uploadedId
    refresh(); deadline()
  }
})
watch(() => props.connected, value => {
  if (value) refresh()
  else { epoch++; request?.abort(); sending.value = false; active.value = false; conversationBusy = false; deadline() }
})
watch(() => props.enabled, value => { if (!value) { text.value = ''; clearDraft(); edit(false) } else refresh() })
watch(() => props.settings, () => nextTick(layout), { deep: true })
watch(() => props.settings.idle_reset_seconds, deadline)
onMounted(() => {
  observer = new ResizeObserver(layout)
  observer.observe(root.value)
  const canvas = root.value.closest?.('[data-composer-canvas]') || root.value.parentElement
  if (canvas) observer.observe(canvas)
  if (!props.preview) { window.visualViewport?.addEventListener('resize', layout); refresh(); poll = setInterval(refresh, 5000); deadline() }
  layout()
})
onBeforeUnmount(() => { request?.abort(); clearInterval(poll); clearTimeout(timer); observer?.disconnect(); window.visualViewport?.removeEventListener('resize', layout); clearDraft() })
defineExpose({ send, receive, reset, sending })
</script>

<style>
.conversation-composer{box-sizing:border-box;width:100%;padding:12px;border:1px solid #65738b;border-radius:14px;background:var(--bg-surface,#151d2c);color:var(--text-primary,#f5f7ff);font:inherit;line-height:1.5}
.conversation-composer.stage-composer{position:absolute;z-index:4;color:#f5f7ff;padding:var(--composer-pad,12px);display:flex;flex-direction:column;overflow:auto;box-shadow:0 6px 30px #0006}
.stage-composer .composer-body{min-height:0;flex:1;overflow:auto;display:flex;flex-direction:column}
.stage-composer .composer-body>textarea{flex:1;resize:none;max-height:none}
.stage-composer .composer-body>:not(textarea){flex-shrink:0}
.stage-composer .composer-label,.stage-composer .composer-actions{flex-shrink:0}
.composer-preview{cursor:grab;touch-action:none}.composer-preview *{pointer-events:none}
.composer-label{display:block;font-size:.8em;margin-bottom:4px}.conversation-composer textarea{box-sizing:border-box;width:100%;min-height:54px;max-height:140px;resize:vertical;background:transparent;color:inherit;border:1px solid #76859e;border-radius:8px;padding:8px;font:inherit}
.conversation-composer button{min-height:44px;min-width:44px;border:1px solid #7b8da9;border-radius:8px;background:#25334b;color:#fff;padding:6px 12px;cursor:pointer;font:inherit}
.conversation-composer button:disabled{opacity:.5;cursor:default}.conversation-composer :focus-visible{outline:2px solid #b3ceff;outline-offset:2px}.composer-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.composer-send{margin-left:auto;background:#234ba3!important}
.composer-help,.composer-status,.composer-error{font-size:max(12px,.8em);margin:6px 0 0}.composer-help{opacity:.85}.composer-error{color:#ffb9b9}.composer-files,.composer-reference-list{max-height:130px;overflow:auto}.composer-file{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:.85em;overflow-wrap:anywhere}.composer-file>span,.composer-file>label{flex:1;min-width:0}.composer-file img{width:36px;height:36px;object-fit:cover}.composer-pages{width:70px;min-height:36px;background:#182236;color:#fff;border:1px solid #7b8da9;border-radius:4px}.composer-references{margin-top:6px;font-size:.85em}.composer-references summary{cursor:pointer;min-height:32px}.composer-file input[type=checkbox]{width:20px;height:20px;vertical-align:middle}
</style>
