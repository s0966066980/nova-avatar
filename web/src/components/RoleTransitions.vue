<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<!-- 角色轉場：所有角色交接共用一份預設，任一方向可另外指定；與成員設定分開儲存。 -->
<template>
  <article class="rc-card rc-trans-card" aria-labelledby="rc-trans-title">
    <div class="rc-card-head">
      <div><h3 id="rc-trans-title"><i class="bi bi-film" aria-hidden="true"></i>角色轉場</h3><p>所有角色交接共用預設；個別方向可另外指定。</p></div>
    </div>
    <div class="rc-card-body">
      <div class="rc-block-head">
        <span class="rc-save-state" :class="stateClass" role="status"><i :class="stateIcon" aria-hidden="true"></i>{{ stateText }}</span>
        <span class="rc-acts">
          <button type="button" class="rc-btn sm ghost" :disabled="!dirty || busy" @click="$emit('revert')"><i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>還原</button>
          <button type="button" class="rc-btn sm primary" :disabled="!dirty || busy" @click="$emit('save')"><i class="bi bi-check-lg" aria-hidden="true"></i>儲存轉場</button>
        </span>
      </div>
      <div v-if="scope.status === 'error'" class="rc-banner danger" role="alert">
        <i class="bi bi-exclamation-octagon" aria-hidden="true"></i>
        <div><b>{{ scope.conflict ? '儲存失敗：角色轉場已被另一個控制台更新' : '儲存失敗' }}</b><div class="rc-detail">{{ scope.error }}{{ scope.conflict ? ' 你的草稿仍保留。' : '' }}</div></div>
        <span v-if="scope.conflict?.current" class="rc-acts"><button type="button" class="rc-btn sm" @click="$emit('use-latest')">載入最新版本</button><button type="button" class="rc-btn sm" @click="$emit('overwrite')">以草稿覆寫</button></span>
      </div>
      <span class="rc-sub-title">預設轉場</span>
      <div class="rc-trans">
        <div class="rc-dir">任一位<i class="bi bi-arrow-right" aria-hidden="true"></i>另一位</div>
        <div :class="scope.draft.default.kind === 'effect' ? 'rc-row-effect' : 'rc-row-video'">
          <select v-model="scope.draft.default.kind" class="rc-input" aria-label="預設轉場類型" @change="kindChanged(scope.draft.default)"><option value="effect">內建特效</option><option value="video">自訂影片</option></select>
          <template v-if="scope.draft.default.kind === 'effect'">
            <select v-model="scope.draft.default.effect" class="rc-input" aria-label="預設轉場特效"><option v-for="(label, id) in EFFECTS" :key="id" :value="id">{{ label }}</option></select>
            <input v-model.number="scope.draft.default.duration" class="rc-input num" type="number" min="0.2" max="2" step="0.1" aria-label="預設轉場時長（秒，0.2–2）" title="時長（秒）" @change="clampDuration(scope.draft.default)">
          </template>
          <select v-else v-model="scope.draft.default.asset_id" class="rc-input" aria-label="預設轉場影片"><option value="" disabled>請選擇影片</option><option v-for="m in media" :key="m.id" :value="m.id">{{ mediaLabel(m) }}</option></select>
        </div>
      </div>
      <details class="rc-adv" :open="scope.draft.overrides.length > 0 || Boolean(addError)">
        <summary><i class="bi bi-chevron-right rc-chev" aria-hidden="true"></i>進階：個別方向<span class="rc-pill">{{ scope.draft.overrides.length }}</span></summary>
        <div class="rc-adv-body">
          <div v-for="(edge, index) in scope.draft.overrides" :key="`${edge.source}-${edge.target}`" class="rc-trans">
            <div class="rc-dir">{{ nameOf(edge.source) }}<i class="bi bi-arrow-right" aria-hidden="true"></i>{{ nameOf(edge.target) }}
              <span v-if="!live.includes(edge.source) || !live.includes(edge.target)" class="rc-tag-off">（含未啟用者，暫不使用）</span>
              <button type="button" class="rc-btn sm ghost rc-rm" :aria-label="`刪除 ${nameOf(edge.source)} 到 ${nameOf(edge.target)} 的個別轉場`" @click="scope.draft.overrides.splice(index, 1)"><i class="bi bi-x-lg" aria-hidden="true"></i></button>
            </div>
            <div :class="edge.kind === 'effect' ? 'rc-row-effect' : 'rc-row-video'">
              <select v-model="edge.kind" class="rc-input" :aria-label="`${nameOf(edge.source)}到${nameOf(edge.target)}的轉場類型`" @change="kindChanged(edge)"><option value="effect">內建特效</option><option value="video">自訂影片</option></select>
              <template v-if="edge.kind === 'effect'">
                <select v-model="edge.effect" class="rc-input" aria-label="特效"><option v-for="(label, id) in EFFECTS" :key="id" :value="id">{{ label }}</option></select>
                <input v-model.number="edge.duration" class="rc-input num" type="number" min="0.2" max="2" step="0.1" aria-label="時長（秒，0.2–2）" title="時長（秒）" @change="clampDuration(edge)">
              </template>
              <select v-else v-model="edge.asset_id" class="rc-input" aria-label="轉場影片"><option value="" disabled>請選擇影片</option><option v-for="m in media" :key="m.id" :value="m.id">{{ mediaLabel(m) }}</option></select>
            </div>
          </div>
          <p v-if="!scope.draft.overrides.length" class="rc-hint">尚無個別方向，全部使用預設轉場。</p>
          <div class="rc-add-row">
            <select v-model="addSource" class="rc-input" aria-label="來源角色"><option value="">來源</option><option v-for="m in members" :key="m.id" :value="m.id">{{ m.name }}{{ m.main ? '（主）' : '' }}</option></select>
            <i class="bi bi-arrow-right" aria-hidden="true"></i>
            <select v-model="addTarget" class="rc-input" aria-label="目的角色"><option value="">目的</option><option v-for="m in members" :key="m.id" :value="m.id">{{ m.name }}{{ m.main ? '（主）' : '' }}</option></select>
            <button type="button" class="rc-btn sm" @click="addOverride"><i class="bi bi-plus-lg" aria-hidden="true"></i>新增</button>
          </div>
          <span v-if="addError" class="rc-field-error" role="alert"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i>{{ addError }}</span>
          <span v-else class="rc-hint">任兩位之間（含主數位人）都可指定；每個方向各自一份，反方向需另外新增。</span>
        </div>
      </details>
      <details class="rc-adv">
        <summary><i class="bi bi-chevron-right rc-chev" aria-hidden="true"></i>轉場影片<span class="rc-pill">{{ media.length }}</span></summary>
        <div class="rc-adv-body">
          <label class="rc-hint" for="rc-trans-upload">上傳轉場影片（MP4／MOV／WebM，100 MiB、30 秒內）；影片會移除音軌。</label>
          <input id="rc-trans-upload" type="file" accept=".mp4,.mov,.webm" :disabled="uploading" @change="upload">
          <p v-if="mediaError" class="rc-field-error" role="alert">{{ mediaError }}</p>
          <div v-for="m in media" :key="m.id" class="rc-media-row"><span>{{ mediaLabel(m) }}</span><button type="button" class="rc-btn sm ghost" @click="removeMedia(m.id)">刪除影片</button></div>
        </div>
      </details>
    </div>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import { EFFECTS, isDirty } from '../roles/roleComposition.js'
import { useRoles } from '../composables/useRoles.js'

const scope = defineModel('scope', { type: Object, required: true })
const media = defineModel('media', { type: Array, required: true })
// members: [{ id, name, main }] in the composition; live: ids taking part in handoffs.
const props = defineProps({ members: { type: Array, required: true }, live: { type: Array, required: true }, names: { type: Object, required: true } })
defineEmits(['save', 'revert', 'use-latest', 'overwrite'])
const { roleRequest } = useRoles()
const addSource = ref(''), addTarget = ref(''), addError = ref(''), uploading = ref(false), mediaError = ref('')
const dirty = computed(() => isDirty(scope.value))
const busy = computed(() => scope.value.status === 'saving')
const nameOf = id => props.names[id] || id
const mediaLabel = m => `${m.name} · ${Number(m.duration || 0).toFixed(2)} 秒`
const stateClass = computed(() => busy.value ? 'busy' : scope.value.status === 'error' ? 'err' : dirty.value ? 'dirty' : '')
const stateIcon = computed(() => busy.value ? 'bi bi-arrow-repeat spin' : scope.value.status === 'error' ? 'bi bi-exclamation-octagon' : dirty.value ? 'bi bi-exclamation-triangle' : 'bi bi-check-circle')
const stateText = computed(() => busy.value ? '儲存中…' : scope.value.status === 'error' ? '儲存失敗，草稿仍保留' : dirty.value ? '有未儲存的變更'
  : `已儲存${scope.value.savedAt ? ` · ${scope.value.savedAt}` : ` · 第 ${scope.value.base.revision} 版`}`)
function kindChanged(edge) {
  if (edge.kind === 'video' && !edge.asset_id && media.value.length) edge.asset_id = media.value[0].id
}
function clampDuration(edge) {
  edge.duration = Math.min(2, Math.max(0.2, Number(edge.duration) || 0.6))
}
function addOverride() {
  const [source, target] = [addSource.value, addTarget.value]
  addError.value = !source || !target ? '請選擇來源與目的。' : source === target ? '來源與目的不能是同一位。'
    : scope.value.draft.overrides.some(e => e.source === source && e.target === target) ? `「${nameOf(source)} → ${nameOf(target)}」已有個別設定，請直接修改上方那一列。` : ''
  if (addError.value) return
  scope.value.draft.overrides.push({ source, target, ...scope.value.draft.default })
  addSource.value = addTarget.value = ''
}
async function upload(event) {
  const file = event.target.files[0]
  if (!file) return
  mediaError.value = ''
  if (file.size > 100 * 1024 * 1024) { mediaError.value = '影片不可超過 100 MiB'; event.target.value = ''; return }
  uploading.value = true
  try {
    const body = new FormData(); body.append('file', file)
    media.value = (await roleRequest('/media', 'POST', body)).media
  } catch (e) { mediaError.value = e.message } finally { uploading.value = false; event.target.value = '' }
}
async function removeMedia(id) {
  mediaError.value = ''
  try { media.value = (await roleRequest('/media/' + id, 'DELETE')).media } catch (e) { mediaError.value = e.message }
}
</script>
