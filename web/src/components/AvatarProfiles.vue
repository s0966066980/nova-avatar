<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="role-settings" :aria-busy="busy">
    <header class="role-top">
      <div><h2>數位人、AI 與知識設定</h2><p>先選數位人，再設定身分、回答模型、回覆規則與 RAG 文本；角色交接在同一處管理。</p></div>
      <div class="role-actions">
        <button type="button" :disabled="busy" @click="requestReload">重新載入</button>
        <button type="submit" form="role-library-form" :disabled="busy || !dirty">僅儲存草稿</button>
        <button type="button" class="primary" :disabled="busy || !draft" @click="run(saveAndApply)">{{ busy ? '處理中…' : '儲存並套用' }}</button>
      </div>
    </header>
    <div v-if="reloadPending" class="role-alert" role="alert">重新載入會捨棄尚未儲存的修改。<button type="button" @click="reloadPending = false; run(load)">捨棄並重新載入</button><button type="button" @click="reloadPending = false">繼續編輯</button></div>
    <p v-if="error" class="role-alert" role="alert">{{ error }}</p>
    <p v-if="notice" class="role-notice" role="status">{{ notice }}</p>
    <div class="role-status" role="status">
      <span>{{ roleRuntime.enabled ? '即時角色交接' : '單角色模式' }} · {{ rolePhaseLabel(roleRuntime.phase) }}</span>
      <span v-if="draft">草稿版本 {{ draft.revision }} · {{ roleRuntime.profiles_applied ? `生效版本 ${roleRuntime.active_revision}` : '尚未套用設定檔' }}</span>
      <strong v-if="dirty">有未儲存的修改</strong><strong v-else-if="pendingApply">已儲存，尚未套用</strong>
    </div>
    <p v-if="roleRuntime.pending" class="role-alert" role="status">設定待套用，控制台與舞台皆斷線後才更新共用資源。</p>
    <p v-if="roleRuntime.error" class="role-alert" role="alert">{{ roleRuntime.error }}</p>
    <p v-if="!draft && busy" role="status">正在載入數位人設定檔…</p>
    <form v-if="draft" id="role-library-form" novalidate @submit.prevent="run(save)">
      <fieldset :disabled="busy">
        <nav class="role-workspaces" aria-label="設定範圍">
          <button type="button" :aria-pressed="workspace === 'profiles'" @click="workspace = 'profiles'">數位人設定檔</button>
          <button type="button" :aria-pressed="workspace === 'handoff'" @click="workspace = 'handoff'">角色組合、交接與轉場</button>
        </nav>
        <div v-show="workspace === 'profiles'" class="role-layout">
          <aside class="role-list" aria-label="選擇要編輯的數位人">
            <h3>數位人設定檔 <small>{{ draft.profiles.length }}</small></h3>
            <button v-for="p in draft.profiles" :key="p.id" type="button" class="role-choice" :aria-pressed="selected === p.id" @click="selected = p.id">
              <span class="role-choice-title">{{ p.name }}<small v-if="p.id === draft.pair.main">主數位人</small><small v-else-if="p.id === draft.pair.specialist">專門數位人</small></span>
              <span>{{ p.llm.model }}</span><span>{{ ragScopeLabel(p.rag) }}</span>
            </button>
            <button type="button" :disabled="!profile || draft.profiles.length >= 30" @click="cloneProfile"><i class="bi bi-plus-lg" aria-hidden="true"></i> 複製為新設定檔</button>
            <button type="button" :disabled="draft.profiles.length <= 2 || inPair(selected)" @click="removeProfile">刪除所選設定檔</button>
            <p>主數位人與專門數位人需保留。刪除前可先在角色組合中改選。</p>
          </aside>
          <section v-if="profile" class="role-card role-editor-card">
            <div class="role-editor-title"><div><h3>{{ profile.name }}</h3><p>目前編輯的數位人 · {{ profile.id }}</p></div><span v-if="roleRuntime.active_profile_id === profile.id">目前作用中</span></div>
            <AvatarProfileEditor ref="editorRef" v-model="draft.profiles[profileIndex]" :avatars="runtime.characters" :endpoints="endpoints" :initial-section="initialSection" :disabled="busy" @restore-rules="restoreRules" />
          </section>
        </div>
        <div v-show="workspace === 'handoff'" class="role-handoff">
          <section class="role-card">
            <h3>當次角色組合</h3>
            <label class="check"><input type="checkbox" v-model="draft.enabled">啟用即時角色交接</label>
            <div class="role-grid"><label>主數位人<select v-model="draft.pair.main"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label><label>專門數位人<select v-model="draft.pair.specialist"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label></div>
            <p>關閉交接時使用主數位人的完整設定檔。啟用時，兩位角色共用 MuseTalk、同一模型服務與語音合成引擎，各自保留 Prompt、RAG 文本、聲線、規則與訪客記憶。</p>
            <p v-if="pairError" class="role-alert" role="alert">{{ pairError }}</p>
          </section>
          <section class="role-card"><h3>雙向角色交接規則</h3>
            <p>專長內問題交給專門數位人，非專長問題自動交回主數位人；混合主題會先確認優先順序。兩個方向都會先播說明，再轉場並接續回答原問題。</p>
            <label>專門角色的專長介紹<textarea v-model="draft.handoff.description" rows="3" maxlength="2000"></textarea></label>
            <label>何時交接<textarea v-model="draft.handoff.rules" rows="4" maxlength="12000"></textarea></label>
            <h4>主數位人交給專門數位人</h4>
            <label>中文交接說明（播完後才轉場）<textarea v-model="draft.handoff.announcement" rows="3" maxlength="2000"></textarea></label>
            <label>英文交接說明（空白使用內建說明）<textarea v-model="draft.handoff.announcement_en" rows="3" maxlength="2000"></textarea></label>
            <h4>專門數位人交回主數位人</h4>
            <label>中文返回交接說明（空白使用內建說明）<textarea v-model="draft.handoff.return_announcement" rows="3" maxlength="2000"></textarea></label>
            <label>英文返回交接說明（空白使用內建說明）<textarea v-model="draft.handoff.return_announcement_en" rows="3" maxlength="2000"></textarea></label>
            <h4>場域預設查詢地點</h4><p>留白時會向訪客確認縣市與鄉鎮。{{ roleRuntime.weather_configured ? 'CWA 已設定授權碼。' : 'CWA 尚未設定授權碼。' }}</p>
            <div class="role-grid"><label>縣市<input v-model="draft.weather.county" placeholder="臺北市"></label><label>鄉鎮市區<input v-model="draft.weather.town" placeholder="中正區"></label></div>
            <p>氣象資料來源：<a href="https://opendata.cwa.gov.tw/" target="_blank" rel="noopener">交通部中央氣象署</a>。授權碼僅在服務端設定。</p>
          </section>
          <section class="role-card"><h3>指定方向的角色轉場</h3><p>去程與回程各自設定。自訂影片會移除音軌，空白處沿用舞台背景。</p>
            <div class="role-grid"><label>來源<select v-model="edgeSource"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label><label>目的<select v-model="edgeTarget"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label></div>
            <template v-if="edge">
              <label>轉場類型<select v-model="edge.kind"><option value="effect">內建特效</option><option value="video">自訂影片</option></select></label>
              <div v-if="edge.kind === 'effect'" class="role-grid"><label>特效<select v-model="edge.effect"><option value="fade">淡入淡出</option><option value="slide_left">向左滑動</option><option value="slide_right">向右滑動</option><option value="zoom">縮放</option></select></label><label>時長（秒）<input type="number" v-model.number="edge.duration" min="0.2" max="2" step="0.1"></label></div>
              <template v-else><label>轉場影片<select v-model="edge.asset_id"><option value="">請選擇影片</option><option v-for="m in media" :key="m.id" :value="m.id">{{ m.name }} · {{ m.duration.toFixed(2) }} 秒</option></select></label><video v-if="edge.asset_id" :src="`/api/profiles/media/${edge.asset_id}`" controls muted playsinline class="role-video"></video></template>
            </template>
            <p v-else>請選擇不同的來源與目的角色。</p>
            <label>上傳轉場影片（MP4／MOV／WebM，100 MiB、30 秒內）<input type="file" accept=".mp4,.mov,.webm" :disabled="!edge" @change="upload"></label>
            <details><summary>管理轉場影片（{{ media.length }}）</summary><div v-for="m in media" :key="m.id" class="role-actions"><span>{{ m.name }}</span><button type="button" @click="deleteMedia(m.id)">刪除影片</button></div></details>
          </section>
        </div>
      </fieldset>
    </form>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, toRaw } from 'vue'
import { useRoles } from '../composables/useRoles.js'
import { useRuntimeSettings } from '../composables/useRuntimeSettings.js'
import { directedTransition, rolePhaseLabel } from '../roleState.js'
import { ragScopeLabel } from '../ragScope.js'
import { referenceAudioProblem } from '../voiceSelection.js'
import AvatarProfileEditor from './AvatarProfileEditor.vue'
const props = defineProps({ initialSection: { type: String, default: 'identity' } })
const { libraryRuntime: roleRuntime, roleRequest, roleLibrary } = useRoles()
const { runtime, ttsVoiceOptions, refreshTtsVoices } = useRuntimeSettings()
const draft = ref(null), selected = ref(''), media = ref([]), endpoints = ref([]), defaults = ref(null)
const busy = ref(false), error = ref(''), notice = ref(''), savedText = ref(''), edgeSource = ref(''), edgeTarget = ref('')
const workspace = ref('profiles'), editorRef = ref(null), reloadPending = ref(false)
let adopting = false
const dirty = computed(() => Boolean(draft.value && JSON.stringify(draft.value) !== savedText.value))
const pendingApply = computed(() => draft.value && (!roleRuntime.profiles_applied || draft.value.revision !== roleRuntime.active_revision))
const profileIndex = computed(() => draft.value?.profiles.findIndex(p => p.id === selected.value) ?? -1)
const profile = computed(() => draft.value?.profiles[profileIndex.value])
const edge = computed(() => draft.value?.transitions.find(e => e.source === edgeSource.value && e.target === edgeTarget.value))
const inPair = id => Object.values(draft.value.pair).includes(id)
const pairError = computed(() => {
  if (!draft.value?.enabled) return ''
  const main = draft.value.profiles.find(p => p.id === draft.value.pair.main)
  const specialist = draft.value.profiles.find(p => p.id === draft.value.pair.specialist)
  if (!main || !specialist || main.id === specialist.id) return '主角色與專門角色需選擇不同設定檔。'
  if ([main, specialist].some(p => p.engine !== 'musetalk')) return '即時角色組合需要兩位 MuseTalk 數位人。'
  if (['endpoint','model'].some(key => main.llm[key] !== specialist.llm[key])) return '兩位角色的 LLM 端點與模型名稱需一致。請分別在 AI 模型與規則中調整。'
  if (main.tts.type !== specialist.tts.type) return '兩位角色需使用同一語音合成引擎，聲線可各自設定。'
  return ''
})
async function run(action) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (e) { error.value = e.message } finally { busy.value = false }
}
function adopt(data) {
  adopting = true
  draft.value = structuredClone(data.library)
  selected.value = draft.value.profiles.some(p => p.id === selected.value) ? selected.value : draft.value.pair.main
  edgeSource.value = draft.value.pair.main; edgeTarget.value = draft.value.pair.specialist
  savedText.value = JSON.stringify(draft.value)
  if (data.media) media.value = data.media
  adopting = false
}
async function load() {
  adopt(await roleRequest())
  // Model discovery is optional; a manual model name remains editable offline.
  try { const r = await fetch('/api/llm/models'); const j = await r.json(); endpoints.value = j.data?.endpoints || [] } catch { /* Keep manual entry available. */ }
  try { const r = await fetch('/api/llm/rules'); const j = await r.json(); defaults.value = j.data?.defaults || null } catch { /* The editor retains existing rules. */ }
  // Reference audio choices are checked before saving; the server checks again.
  try { await refreshTtsVoices() } catch { /* The voice editor shows its own load error. */ }
}
// Open the first profile whose voice cannot be saved and explain why.
function requireVoices() {
  for (const p of draft.value.profiles) {
    const problem = referenceAudioProblem(p.tts, ttsVoiceOptions.value)
    if (!problem) continue
    workspace.value = 'profiles'; selected.value = p.id; editorRef.value?.openSection('voice')
    throw Error(`「${p.name}」${problem}`)
  }
}
function requestReload() { if (dirty.value) reloadPending.value = true; else run(load) }
async function save() {
  if (draft.value.pair.main === draft.value.pair.specialist) throw Error('主角色與專門角色需選擇不同設定檔')
  requireVoices()
  adopt(await roleRequest('', 'PUT', { library: draft.value, expected_revision: draft.value.revision }))
  notice.value = '草稿已儲存；套用後由下一場對話採用。'
}
async function saveAndApply() {
  if (pairError.value) throw Error(pairError.value)
  requireVoices()
  if (dirty.value) await save()
  await roleRequest('/apply', 'POST')
  notice.value = roleRuntime.pending ? '設定已儲存，待兩端斷線後套用。' : '設定已儲存，下一場對話採用；目前對話繼續使用原設定。'
}
async function saveAndApplyFromParent() {
  busy.value = true; error.value = ''; notice.value = ''
  try { await saveAndApply() } catch (e) { error.value = e.message; throw e } finally { busy.value = false }
}
function cloneProfile() {
  const p = structuredClone(toRaw(profile.value))
  p.id = 'role_' + crypto.randomUUID().replaceAll('-', '').slice(0,12); p.name += ' 副本'
  draft.value.profiles.push(p); selected.value = p.id
}
function removeProfile() {
  draft.value.transitions = draft.value.transitions.filter(e => e.source !== selected.value && e.target !== selected.value)
  draft.value.profiles = draft.value.profiles.filter(p => p.id !== selected.value); selected.value = draft.value.pair.main
}
async function restoreRules() {
  if (!defaults.value) { error.value = '無法取得預設規則，請重新載入後再試。'; return }
  for (const key of ['activation','speech','board']) profile.value.reply_rules[key] = defaults.value[key]
}
const upload = event => run(async () => {
  const f = event.target.files[0]; if (!f) return
  if (f.size > 100 * 1024 * 1024) throw Error('影片不可超過 100 MiB')
  const body = new FormData(); body.append('file', f)
  const data = await roleRequest('/media', 'POST', body); media.value = data.media
  if (edge.value) { edge.value.kind = 'video'; edge.value.asset_id = data.asset.id }
  event.target.value = ''; notice.value = '影片已驗證並轉為無聲轉場，請儲存設定。'
})
const deleteMedia = id => run(async () => { media.value = (await roleRequest('/media/' + id, 'DELETE')).media })
watch([workspace, edgeSource, edgeTarget], ([view, source, target]) => {
  if (!adopting && view === 'handoff' && draft.value && source && target && source !== target) directedTransition(draft.value, source, target)
}, { flush: 'sync' })
watch(() => props.initialSection, value => { workspace.value = 'profiles'; editorRef.value?.openSection(value) })
// The shared library is reactive; structuredClone only accepts the raw object.
watch(roleLibrary, value => { if (value && !busy.value && !dirty.value) adopt({ library: toRaw(value) }) })
onMounted(() => run(load))
defineExpose({ dirty, pendingApply, busy, saveAndApply: saveAndApplyFromParent })
</script>

<style scoped>
.role-settings{color:var(--text-primary);width:100%;min-width:0;margin:auto}.role-top,.role-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:space-between}.role-top h2{font-size:22px;margin:0}.role-top p,.role-card p,.role-list p{font-size:13px;color:var(--text-secondary);line-height:1.7}.role-top>div:first-child{max-width:630px}.role-status{display:flex;flex-wrap:wrap;gap:12px 24px;padding:14px 0;margin:12px 0;color:var(--text-secondary);font-size:12px}.role-status strong{color:var(--warning)}.role-card{padding:24px;border:1px solid var(--border-default);border-radius:var(--radius-lg);background:var(--bg-surface);margin:0 0 20px;min-width:0}.role-card h3,.role-list h3{font-size:16px;margin:0 0 14px}.role-card h4{font-size:14px;margin:20px 0 12px}.role-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px}.role-handoff label{display:flex;flex-direction:column;gap:8px;font-size:13px;margin:14px 0}.role-handoff .check{flex-direction:row;align-items:center}.role-handoff input,.role-handoff select,.role-handoff textarea{background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-default);padding:10px 12px;border-radius:var(--radius-sm);width:100%;font:inherit}.role-handoff .check input{width:auto}.role-handoff textarea{resize:vertical;min-height:70px}.role-settings button{padding:10px 14px;border:1px solid var(--border-default);border-radius:var(--radius-sm);color:var(--text-primary);background:var(--bg-surface);font-size:13px;cursor:pointer}.role-settings button.primary{background:var(--brand);border-color:var(--brand);color:var(--on-brand);font-weight:700}.role-settings button:hover:not(:disabled):not(.primary){background:var(--bg-hover)}.role-settings button.primary:hover:not(:disabled){background:var(--brand-hover)}.role-settings button:disabled{opacity:.45;cursor:not-allowed}.role-settings :focus-visible{outline:2px solid var(--focus-ring);outline-offset:3px}.role-settings fieldset{border:0;padding:0;min-width:0}.role-alert{color:var(--text-primary);border:1px solid var(--warn-border);border-left:4px solid var(--warn-bar);background:var(--warn-surface);padding:12px;border-radius:var(--radius-sm);font-size:13px;line-height:1.7;overflow-wrap:anywhere}.role-alert[role=alert]{border-color:var(--danger-border);border-left-color:var(--danger);background:var(--danger-surface)}.role-alert button{margin:4px}.role-notice{color:var(--success);font-size:13px}.role-video{max-width:100%;height:220px;background:#111;margin-top:12px}.role-settings summary{cursor:pointer;padding:10px 0}.role-workspaces{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}.role-workspaces button[aria-pressed=true]{border-color:var(--brand-light);color:var(--brand-light)}.role-layout{display:grid;grid-template-columns:minmax(12rem,16rem) minmax(0,1fr);gap:22px;align-items:start}.role-list{display:grid;gap:10px;padding-top:4px;min-width:0}.role-list h3 small{color:var(--text-secondary);margin-left:8px}.role-list .role-choice{display:grid;text-align:left;gap:7px;padding:16px;font-size:12px;overflow-wrap:anywhere}.role-list .role-choice[aria-pressed=true]{border-color:var(--brand-light);background:var(--bg-surface-elevated)}.role-choice>span{color:var(--text-secondary)}.role-choice .role-choice-title{color:var(--text-primary);font-size:14px;font-weight:600;display:flex;gap:8px;flex-wrap:wrap;align-items:center}.role-choice small,.role-editor-title>span{font-size:11px;color:var(--brand-light);font-weight:500}.role-editor-title{display:flex;justify-content:space-between;align-items:start;gap:12px;flex-wrap:wrap;padding-bottom:16px}.role-editor-title h3{font-size:20px;margin:0}.role-editor-title p{margin:8px 0 0}.role-handoff{min-width:0}.role-handoff a{color:var(--brand-light)}@media(min-width:1280px) and (min-height:640px){.role-settings{display:flex;flex-direction:column;min-height:0}.role-settings>form,.role-settings fieldset{flex:1 1 0;min-height:0;display:flex;flex-direction:column}.role-workspaces{flex:none}.role-layout,.role-handoff{flex:1 1 0;min-height:0}.role-layout{grid-template-rows:minmax(0,1fr);align-items:stretch}.role-list,.role-editor-card,.role-handoff>.role-card{min-height:0;overflow-y:auto;overscroll-behavior:contain}.role-list{align-content:start}.role-editor-card{margin:0}.role-handoff{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-rows:minmax(0,auto) minmax(0,1fr);gap:20px}.role-handoff>.role-card{margin:0}.role-handoff>.role-card:nth-child(2){grid-column:2;grid-row:1/span 2}.role-handoff>.role-card:nth-child(3){grid-column:1;grid-row:2}}
@media(max-width:1100px){.role-layout{grid-template-columns:1fr}.role-list{grid-template-columns:repeat(2,minmax(0,1fr))}.role-list h3,.role-list p{grid-column:1/-1}}@media(max-width:700px){.role-grid,.role-list{grid-template-columns:1fr}.role-card{padding:16px}.role-top h2{font-size:20px}}
</style>
