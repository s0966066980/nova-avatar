<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="input-group">
    <slot />
    <slot name="actions" />
    <button
      v-if="pickerState.available"
      type="button"
      class="btn btn-outline-secondary"
      @click="$emit('pick')"
    >
      {{ buttonLabel }}
    </button>
  </div>
  <span v-if="!pickerState.available" class="field-sub-hint">{{ pickerState.hint }}</span>
</template>

<script setup>
defineProps({
  pickerState: { type: Object, required: true },
  buttonLabel: { type: String, required: true }
})
defineEmits(['pick'])
</script>
