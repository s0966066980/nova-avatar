<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section class="greeting-editor" aria-labelledby="greeting-title">
    <h3 id="greeting-title">招呼內容</h3>
    <p>只有舞台的主數位人在空場時自動招呼。編輯與預覽不會影響現場；設定完成後，按本頁的「儲存並套用招呼設定」，由下一場舞台對話採用。</p>
    <fieldset :disabled="disabled || isPreparing">
      <legend>內容模式</legend>
      <div class="content-modes" role="group" aria-label="招呼來源">
        <label class="mode-choice"><input type="radio" name="greeting-mode" v-model="settings.mode" value="ai">AI 自動生成（Prompt）</label>
        <label class="mode-choice"><input type="radio" name="greeting-mode" v-model="settings.mode" value="scripts">隨機預寫文案</label>
      </div>
      <div class="range-fields">
        <label>最少字數<input id="greeting-min-chars" type="number" v-model.number="settings.min_chars" min="1" step="1" required></label>
        <label>最多字數<input id="greeting-max-chars" type="number" v-model.number="settings.max_chars" min="1" step="1" required></label>
      </div>
      <p>包含標點、忽略空白；表情符號與組合字算一個可見字元。AI 嚴格遵守範圍，預寫文案超限仍可播放。</p>
      <template v-if="settings.mode === 'scripts'">
        <div v-for="(text, index) in settings.scripts" :key="index" class="script-entry">
          <label :for="`greeting-script-${index}`">文案 {{ index + 1 }}</label>
          <textarea :id="`greeting-script-${index}`" v-model="settings.scripts[index]" rows="3" maxlength="12000"></textarea>
          <div class="script-footer"><small>{{ visibleLength(text) }} 字<span v-if="outOfRange(text)"> · 超出建議範圍，仍可播放</span></small><button type="button" @click="settings.scripts.splice(index, 1)" :aria-label="`刪除文案 ${index + 1}`">刪除</button></div>
        </div>
        <button type="button" :disabled="settings.scripts.length >= 100" @click="settings.scripts.push('')">新增文案</button>
        <h4>英文預寫招呼</h4>
        <p>英文舞台只使用以下文案；沒有英文文案時略過招呼，不自動翻譯。</p>
        <div v-for="(text, index) in settings.scripts_en || []" :key="`en-${index}`" class="script-entry">
          <label :for="`greeting-script-en-${index}`">英文文案 {{ index + 1 }}</label>
          <textarea :id="`greeting-script-en-${index}`" v-model="settings.scripts_en[index]" rows="3" maxlength="12000"></textarea>
          <button type="button" @click="settings.scripts_en.splice(index, 1)">刪除英文文案</button>
        </div>
        <button type="button" @click="settings.scripts_en ||= []; settings.scripts_en.push('')">新增英文文案</button>
      </template>
      <div v-else>
        <label for="greeting-prompt">AI 招呼 Prompt<textarea id="greeting-prompt" v-model="settings.prompt" rows="5" maxlength="12000" aria-describedby="greeting-prompt-hint" placeholder="例如：用親切自然的繁體中文，介紹你能提供的服務，再邀請訪客提問。"></textarea></label>
        <p id="greeting-prompt-hint">每次閒置到期時，AI 都會根據這段 Prompt 與主數位人的身分重新生成招呼詞，並遵守上方字數範圍。這裡設定即可，不需到其他頁面填寫。</p>
      </div>
    </fieldset>
    <p v-if="validation" class="feedback" role="status">{{ validation }}</p>
    <div class="actions">
      <button type="button" :disabled="disabled || isPreparing || Boolean(validation)" @click="prepare(false)">{{ busy === 'preview' ? '產生預覽中…' : '預覽草稿' }}</button>
      <button type="button" :disabled="disabled || isPreparing || Boolean(validation)" @click="prepare(true)">{{ busy === 'try' ? '準備試播中…' : '試播草稿' }}</button>
    </div>
    <p>試播只在控制台播放，請先在控制台建立播放連線。使用目前連線的人物，文案、身分 Prompt 與聲線採草稿；語音引擎類型須與連線一致。不影響舞台的收音或招呼。</p>
    <p v-if="error" class="feedback" role="alert">{{ error }}</p>
    <div v-if="preview" class="preview" aria-live="polite"><strong>{{ preview.length }} 字{{ preview.in_range ? '' : ' · 超出建議範圍' }}</strong><p>{{ preview.text }}</p></div>
    <p v-if="status" role="status">{{ status }}</p>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { greetingError, visibleLength } from '../greeting.js'
import { useRoles } from '../composables/useRoles.js'
const props = defineProps({ profile: { type: Object, required: true }, disabled: Boolean })
const settings = computed(() => props.profile.greeting)
const { roleRequest } = useRoles()
const busy = ref(''), error = ref(''), preview = ref(null), status = ref('')
// Boolean attributes treat an empty string as present, so never bind the
// operation label directly to disabled.
const isPreparing = computed(() => busy.value !== '')
const validation = computed(() => greetingError(settings.value))
const outOfRange = text => visibleLength(text) < settings.value.min_chars || visibleLength(text) > settings.value.max_chars
watch(() => props.profile, () => { preview.value = null; error.value = ''; status.value = '' }, { deep: true })
async function prepare(trial) {
  busy.value = trial ? 'try' : 'preview'; error.value = ''; status.value = ''
  try {
    let sessionid = 0
    if (trial) {
      sessionid = Number(document.getElementById('sessionid')?.value)
      if (!sessionid) throw new Error('請先在控制台建立播放連線。')
    }
    preview.value = await roleRequest(`/greeting/${trial ? 'try' : 'preview'}`, 'POST', { profile: props.profile, sessionid })
    if (trial) status.value = '已送出試播，請在控制台聆聽。舞台對話持續運作。'
  } catch (e) { error.value = e.message }
  finally { busy.value = '' }
}
</script>
<style scoped>
.greeting-editor{padding-top:24px}.greeting-editor h3{font-size:18px}.greeting-editor p,.greeting-editor small{font-size:13px;line-height:1.7;color:var(--text-secondary)}fieldset{border:0;padding:0;margin:0;min-width:0}legend{font-size:14px}.greeting-editor label{display:flex;flex-direction:column;gap:8px;margin:16px 0;font-size:13px}.greeting-editor input,.greeting-editor select,.greeting-editor textarea{width:100%;padding:10px 12px;border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--bg-input);color:var(--text-primary);font:inherit;box-sizing:border-box}.greeting-editor textarea{resize:vertical}.content-modes{display:flex;gap:12px;flex-wrap:wrap}.greeting-editor .mode-choice{flex-direction:row;align-items:center;padding:12px;border:1px solid var(--border-default);border-radius:var(--radius-sm);cursor:pointer}.greeting-editor .mode-choice input{width:auto}.range-fields{display:grid;grid-template-columns:1fr 1fr;gap:20px}.actions,.script-footer{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.script-footer{justify-content:space-between}.greeting-editor button{min-height:40px;padding:9px 12px;border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--bg-surface);color:var(--text-primary);cursor:pointer}.greeting-editor button:disabled{opacity:.5;cursor:default}.greeting-editor :focus-visible{outline:2px solid var(--focus-ring);outline-offset:3px}.preview{padding:16px;border:1px solid var(--border-default);border-radius:var(--radius-sm);margin-top:16px;white-space:pre-wrap}.greeting-editor .feedback{color:var(--text-primary);border-left:3px solid var(--brand-light);padding-left:12px}@media(max-width:600px){.range-fields{grid-template-columns:1fr;gap:0}}
</style>
