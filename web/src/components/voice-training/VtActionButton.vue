<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-act">
    <!-- A disabled action stays focusable (aria-disabled) and names its reasons through aria-describedby. -->
    <button
      type="button"
      :class="['vt-btn', { primary }]"
      :aria-disabled="enabled ? undefined : 'true'"
      :aria-describedby="!enabled && reasons.length ? reasonId : undefined"
      @click="onClick"
    >
      <i v-if="iconName" :class="icon(iconName)" aria-hidden="true"></i>{{ label }}
    </button>
    <div v-if="!enabled && reasons.length" :id="reasonId" class="vt-why">
      <i :class="icon('info')" aria-hidden="true"></i>
      <span><span v-for="reason in reasons" :key="reason" class="vt-why-line">{{ reason }}</span></span>
    </div>
  </div>
</template>

<script setup>
import { icon } from '../../voiceTraining/icons.js'

const props = defineProps({
  label: { type: String, required: true },
  enabled: { type: Boolean, default: true },
  reasons: { type: Array, default: () => [] },
  reasonId: { type: String, required: true },
  primary: { type: Boolean, default: false },
  iconName: { type: String, default: '' }
})
const emit = defineEmits(['activate'])
const onClick = () => { if (props.enabled) emit('activate') }
</script>
