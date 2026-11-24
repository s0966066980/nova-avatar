<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<!-- 數位人設定檔：身分、回答模型、規則、RAG 與聲音。誰上場與交接設定在「角色組合與交接」。 -->
<template>
  <div class="role-settings" :aria-busy="busy">
    <div class="role-top">
      <div class="role-status" role="status">
        <span>{{ roleRuntime.enabled ? '即時角色交接' : '單角色模式' }} · {{ rolePhaseLabel(roleRuntime.phase) }}</span>
        <span v-if="saved">設定檔版本 {{ saved.profiles_revision }} · {{ roleRuntime.profiles_applied ? `生效版本 ${roleRuntime.active_revision}` : '尚未套用設定檔' }}</span>
        <strong v-if="dirty">有未儲存的修改</strong><strong v-else-if="pendingApply">已儲存，尚未套用</strong>
      </div>
      <div class="role-actions">
        <button type="button" :disabled="busy" @click="requestReload">重新載入</button>
        <button type="submit" form="role-library-form" :disabled="busy || !dirty">僅儲存草稿</button>
        <button type="button" class="primary" :disabled="busy || !draft" @click="run(saveAndApply)">{{ busy ? '處理中…' : '儲存並套用' }}</button>
      </div>
    </div>
    <div v-if="reloadPending" class="role-alert" role="alert">重新載入會捨棄尚未儲存的修改。<button type="button" @click="reloadPending = false; run(load)">捨棄並重新載入</button><button type="button" @click="reloadPending = false">繼續編輯</button></div>
    <p v-if="error" class="role-alert" role="alert">{{ error }}</p>
    <p v-if="notice" class="role-notice" role="status">{{ notice }}</p>
    <p v-if="roleRuntime.pending" class="role-alert" role="status">設定待套用，控制台與舞台皆斷線後才更新共用資源。</p>
    <p v-if="roleRuntime.error" class="role-alert" role="alert">{{ roleRuntime.error }}</p>
    <p v-if="!draft && busy" role="status">正在載入數位人設定檔…</p>
    <form v-if="draft" id="role-library-form" novalidate @submit.prevent="run(save)">
      <fieldset :disabled="busy">
        <div class="role-layout">
          <aside class="role-list" aria-label="選擇要編輯的數位人">
            <h3>數位人設定檔 <small>{{ draft.profiles.length }}</small></h3>
            <button v-for="p in draft.profiles" :key="p.id" type="button" class="role-choice" :aria-pressed="selected === p.id" @click="selected = p.id">
              <span class="role-choice-title">{{ p.name }}<small>{{ roleTag(p.id) }}</small></span>
              <span>{{ p.llm.model }}</span><span>{{ ragScopeLabel(p.rag) }}</span>
            </button>
            <button type="button" :disabled="!profile || draft.profiles.length >= 30" @click="cloneProfile"><i class="bi bi-plus-lg" aria-hidden="true"></i> 複製為新設定檔</button>
            <button type="button" :disabled="draft.profiles.length <= 1 || inComposition(selected)" @click="removeProfile">刪除所選設定檔</button>
            <p>設定檔是素材；在「角色組合與交接」決定誰上場。組合中的設定檔需先移出組合或更換主數位人才能刪除。</p>
          </aside>
          <section v-if="profile" class="role-card role-editor-card">
            <div class="role-editor-title"><div><h3>{{ profile.name }}</h3><p>目前編輯的數位人 · {{ profile.id }}</p></div><span v-if="roleRuntime.active_profile_id === profile.id">目前作用中</span></div>
            <AvatarProfileEditor ref="editorRef" v-model="draft.profiles[profileIndex]" :avatars="runtime.characters" :endpoints="endpoints" :initial-section="initialSection" :disabled="busy" @restore-rules="restoreRules" />
          </section>
        </div>
      </fieldset>
    </form>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, toRaw, nextTick } from 'vue'
import { useRoles } from '../composables/useRoles.js'
import { useRuntimeSettings } from '../composables/useRuntimeSettings.js'
import { rolePhaseLabel } from '../roleState.js'
import { ragScopeLabel } from '../ragScope.js'
import { ttsVoiceProblem } from '../voiceSelection.js'
import AvatarProfileEditor from './AvatarProfileEditor.vue'
const props = defineProps({ initialSection: { type: String, default: 'identity' } })
const { libraryRuntime: roleRuntime, roleRequest, roleLibrary } = useRoles()
const { runtime, speech, ttsVoiceOptions, refreshTtsVoices } = useRuntimeSettings()
// draft holds only the profile list; the composition is saved on its own page.
const draft = ref(null), saved = ref(null), selected = ref(''), endpoints = ref([]), defaults = ref(null)
const busy = ref(false), error = ref(''), notice = ref(''), savedText = ref('')
const editorRef = ref(null), reloadPending = ref(false)
const dirty = computed(() => Boolean(draft.value && JSON.stringify(draft.value.profiles) !== savedText.value))
const pendingApply = computed(() => saved.value && (!roleRuntime.profiles_applied || saved.value.revision !== roleRuntime.active_revision))
const profileIndex = computed(() => draft.value?.profiles.findIndex(p => p.id === selected.value) ?? -1)
const profile = computed(() => draft.value?.profiles[profileIndex.value])
const composition = computed(() => saved.value?.composition)
const inComposition = id => id === composition.value?.main.profile_id || Boolean(composition.value?.members.some(m => m.profile_id === id))
function roleTag(id) {
  if (!composition.value) return ''
  if (id === composition.value.main.profile_id) return '主數位人'
  const index = composition.value.members.findIndex(m => m.profile_id === id)
  if (index < 0) return '未加入組合'
  return `專門 #${index + 1}${composition.value.members[index].enabled ? '' : ' · 未啟用'}`
}
async function run(action) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (e) { error.value = e.message } finally { busy.value = false }
}
function adopt(library) {
  saved.value = { revision: library.revision, profiles_revision: library.profiles_revision, composition: structuredClone(library.composition) }
  draft.value = { profiles: structuredClone(library.profiles) }
  selected.value = draft.value.profiles.some(p => p.id === selected.value) ? selected.value : library.composition.main.profile_id
  savedText.value = JSON.stringify(draft.value.profiles)
}
async function load() {
  adopt((await roleRequest()).library)
  // Model discovery is optional; a manual model name remains editable offline.
  try { const r = await fetch('/api/llm/models'); const j = await r.json(); endpoints.value = j.data?.endpoints || [] } catch { /* Keep manual entry available. */ }
  try { const r = await fetch('/api/llm/rules'); const j = await r.json(); defaults.value = j.data?.defaults || null } catch { /* The editor retains existing rules. */ }
  // Reference audio choices are checked before saving; the server checks again.
  try { await refreshTtsVoices() } catch { /* The voice editor shows its own load error. */ }
}
// Open the first profile whose voice cannot be saved and explain why.
function requireVoices() {
  for (const p of draft.value.profiles) {
    const problem = ttsVoiceProblem(p.tts, ttsVoiceOptions.value, speech.tts.voice_models)
    if (!problem) continue
    selected.value = p.id; editorRef.value?.openSection('voice')
    throw Error(`「${p.name}」${problem}`)
  }
}
function requestReload() { if (dirty.value) reloadPending.value = true; else run(load) }
async function save() {
  requireVoices()
  adopt((await roleRequest('', 'PUT', { profiles: draft.value.profiles, expected_profiles_revision: saved.value.profiles_revision })).library)
  notice.value = '草稿已儲存；套用後由下一場對話採用。'
}
async function saveAndApply() {
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
  draft.value.profiles = draft.value.profiles.filter(p => p.id !== selected.value)
  selected.value = composition.value.main.profile_id
}
async function restoreRules() {
  if (!defaults.value) { error.value = '無法取得預設規則，請重新載入後再試。'; return }
  for (const key of ['activation','speech','board']) profile.value.reply_rules[key] = defaults.value[key]
}
// Opened from 角色組合與交接 (e.g. to fix a voice).
function openProfile(id, section) {
  if (draft.value?.profiles.some(p => p.id === id)) selected.value = id
  if (section) nextTick(() => editorRef.value?.openSection(section))
}
// The shared library is reactive; structuredClone only accepts the raw object.
watch(roleLibrary, value => {
  if (!value?.composition || busy.value) return
  if (!dirty.value) adopt(toRaw(value))
  else saved.value = { ...saved.value, revision: value.revision, composition: structuredClone(toRaw(value.composition)) }
})
watch(() => props.initialSection, value => editorRef.value?.openSection(value))
onMounted(() => run(load))
defineExpose({ dirty, pendingApply, busy, saveAndApply: saveAndApplyFromParent, openProfile })
</script>

<style scoped>
.role-settings{color:var(--text-primary);width:100%;min-width:0;margin:auto}.role-top,.role-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:space-between}.role-card p,.role-list p{font-size:13px;color:var(--text-secondary);line-height:1.7}.role-status{display:flex;flex-wrap:wrap;gap:6px 24px;color:var(--text-secondary);font-size:12px}.role-top{margin-bottom:14px}.role-status strong{color:var(--warning)}.role-card{padding:24px;border:1px solid var(--border-default);border-radius:var(--radius-lg);background:var(--bg-surface);margin:0 0 20px;min-width:0}.role-card h3,.role-list h3{font-size:16px;margin:0 0 14px}.role-settings button{padding:10px 14px;border:1px solid var(--border-default);border-radius:var(--radius-sm);color:var(--text-primary);background:var(--bg-surface);font-size:13px;cursor:pointer}.role-settings button.primary{background:var(--brand);border-color:var(--brand);color:var(--on-brand);font-weight:700}.role-settings button:hover:not(:disabled):not(.primary){background:var(--bg-hover)}.role-settings button.primary:hover:not(:disabled){background:var(--brand-hover)}.role-settings button:disabled{opacity:.45;cursor:not-allowed}.role-settings :focus-visible{outline:2px solid var(--focus-ring);outline-offset:3px}.role-settings fieldset{border:0;padding:0;min-width:0}.role-alert{color:var(--text-primary);border:1px solid var(--warn-border);border-left:4px solid var(--warn-bar);background:var(--warn-surface);padding:12px;border-radius:var(--radius-sm);font-size:13px;line-height:1.7;overflow-wrap:anywhere;margin:0 0 12px}.role-alert[role=alert]{border-color:var(--danger-border);border-left-color:var(--danger);background:var(--danger-surface)}.role-alert button{margin:4px}.role-notice{color:var(--success);font-size:13px;margin:0 0 12px}.role-layout{display:grid;grid-template-columns:minmax(12rem,16rem) minmax(0,1fr);gap:22px;align-items:start}.role-list{display:grid;gap:10px;padding-top:4px;min-width:0}.role-list h3 small{color:var(--text-secondary);margin-left:8px}.role-list .role-choice{display:grid;text-align:left;gap:7px;padding:16px;font-size:12px;overflow-wrap:anywhere}.role-list .role-choice[aria-pressed=true]{border-color:var(--brand-light);background:var(--bg-surface-elevated)}.role-choice>span{color:var(--text-secondary)}.role-choice .role-choice-title{color:var(--text-primary);font-size:14px;font-weight:600;display:flex;gap:8px;flex-wrap:wrap;align-items:center}.role-choice small,.role-editor-title>span{font-size:11px;color:var(--brand-light);font-weight:500}.role-editor-title{display:flex;justify-content:space-between;align-items:start;gap:12px;flex-wrap:wrap;padding-bottom:16px}.role-editor-title h3{font-size:20px;margin:0}.role-editor-title p{margin:8px 0 0}@media(min-width:1280px) and (min-height:640px){.role-settings{display:flex;flex-direction:column;min-height:0}.role-settings>form,.role-settings fieldset{flex:1 1 0;min-height:0;display:flex;flex-direction:column}.role-top{flex:none}.role-layout{flex:1 1 0;min-height:0}.role-layout{grid-template-rows:minmax(0,1fr);align-items:stretch}.role-list,.role-editor-card{min-height:0;overflow-y:auto;overscroll-behavior:contain}.role-list{align-content:start}.role-editor-card{margin:0}}
@media(max-width:1100px){.role-layout{grid-template-columns:1fr}.role-list{grid-template-columns:repeat(2,minmax(0,1fr))}.role-list h3,.role-list p{grid-column:1/-1}}@media(max-width:700px){.role-list{grid-template-columns:1fr}.role-card{padding:16px}}
</style>
