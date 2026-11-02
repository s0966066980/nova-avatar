<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<!-- 交接欄位：每位成員（含主數位人）都一樣：專長介紹、交接規則、交接說明中英。 -->
<template>
  <div class="rc-section-title"><i class="bi bi-arrow-right" aria-hidden="true"></i>交給{{ name }}<span class="rc-step">任一位 → {{ name }}</span></div>
  <div class="rc-field">
    <label :for="`${prefix}-description`">專長介紹<span class="rc-opt">選填</span></label>
    <textarea :id="`${prefix}-description`" v-model="draft.description" class="rc-input" rows="2" maxlength="2000"
      :placeholder="main ? '例：一般接待，以及其他角色都不負責的問題' : '例：負責天氣、降雨與氣溫問題。'" :aria-describedby="`${prefix}-description-hint`"></textarea>
    <span :id="`${prefix}-description-hint`" class="rc-hint">每一輪判斷時，組合中所有已啟用的角色（含主數位人）都會讀到。</span>
  </div>
  <div class="rc-field">
    <label :for="`${prefix}-rules`">何時交給它（交接規則）<span class="rc-opt">選填</span></label>
    <textarea :id="`${prefix}-rules`" v-model="draft.rules" class="rc-input" rows="3" maxlength="12000"
      :placeholder="main ? '例：問題不屬於任何其他角色的專長時交給這位。' : '例：訪客詢問天氣、降雨或氣溫時交給這位。'"></textarea>
  </div>
  <div class="rc-grid-2">
    <div class="rc-field">
      <label :for="`${prefix}-announcement`">交接說明 · 中文<span class="rc-req" aria-hidden="true">*</span></label>
      <textarea :id="`${prefix}-announcement`" v-model="draft.announcement" class="rc-input" rows="2" maxlength="2000" required
        :aria-invalid="Boolean(error)" :aria-describedby="`${prefix}-announcement-hint${error ? ` ${prefix}-announcement-error` : ''}`"></textarea>
      <span v-if="error" :id="`${prefix}-announcement-error`" class="rc-field-error"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i>{{ error }}</span>
      <span :id="`${prefix}-announcement-hint`" class="rc-hint">由目前的角色說出；不論從哪一位交給{{ name }}都用這一句。</span>
    </div>
    <div class="rc-field">
      <label :for="`${prefix}-announcement-en`">交接說明 · 英文<span class="rc-opt">選填</span></label>
      <textarea :id="`${prefix}-announcement-en`" v-model="draft.announcement_en" class="rc-input" rows="2" maxlength="2000" placeholder="空白時使用內建英文說明"></textarea>
    </div>
  </div>
</template>

<script setup>
const draft = defineModel({ type: Object, required: true })
defineProps({ name: { type: String, required: true }, prefix: { type: String, required: true }, main: Boolean, error: { type: String, default: '' } })
</script>
