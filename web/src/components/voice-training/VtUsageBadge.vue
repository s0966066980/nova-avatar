<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <!-- The usage label is always the original English string plus an icon, never translated or colour-only. -->
  <span :class="['vt-tag', development ? 'dev' : 'res']">
    <i :class="icon(development ? 'alert' : 'info')" aria-hidden="true"></i>{{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { USAGE_DEV } from '../../voiceTraining/constants.js'
import { icon } from '../../voiceTraining/icons.js'

const props = defineProps({ label: { type: String, required: true } })
const development = computed(() => props.label === USAGE_DEV)
</script>
