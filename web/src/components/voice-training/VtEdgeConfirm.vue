<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <div v-if="expired" class="vt-banner danger" role="alert">
      <i :class="icon('x-circle')" aria-hidden="true"></i>
      <div><div class="vt-b-title">{{ tx('edgeConfirm.expiredTitle') }}</div>{{ tx('edgeConfirm.expiredBody') }}</div>
    </div>
    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>
    <div class="vt-banner warn">
      <i :class="icon('alert')" aria-hidden="true"></i>
      <div><div class="vt-b-title">{{ tx('edgeConfirm.readTitle') }}</div>{{ tx('edgeConfirm.readBody') }}</div>
    </div>

    <figure class="vt-msa">
      <div class="vt-msa-src">{{ MSA_CLAUSE.reference }}</div>
      <blockquote lang="en">&ldquo;{{ MSA_CLAUSE.text }}&rdquo;</blockquote>
      <figcaption class="vt-hint">{{ tx('edgeConfirm.summary') }}</figcaption>
    </figure>

    <div class="vt-stack">
      <h3 class="vt-section-title"><i :class="icon('lock')" aria-hidden="true"></i>{{ tx('edgeConfirm.limitsTitle') }}</h3>
      <ul class="vt-rules">
        <li><i :class="icon('alert')" aria-hidden="true"></i><span>{{ tx('edgeConfirm.ruleLabel') }} <strong>{{ USAGE_DEV }}</strong></span></li>
        <li><i :class="icon('alert')" aria-hidden="true"></i><span>{{ tx('edgeConfirm.ruleNoExport') }}</span></li>
        <li><i :class="icon('alert')" aria-hidden="true"></i><span>{{ tx('edgeConfirm.ruleSource') }}</span></li>
        <li><i :class="icon('info')" aria-hidden="true"></i><span>{{ tx('usage.notLicense') }}</span></li>
      </ul>
    </div>

    <label class="vt-check" for="vt-msa-ok">
      <input id="vt-msa-ok" v-model="state.edge.checked" type="checkbox" :disabled="expired">
      <span>{{ tx('edgeConfirm.check') }}</span>
    </label>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="useUpload"><i :class="icon('mic')" aria-hidden="true"></i>{{ tx('edgeConfirm.useUpload') }}</button>
      <div class="vt-right">
        <button type="button" class="vt-btn" @click="store.go('source')">{{ tx('common.back') }}</button>
        <VtActionButton
          primary
          :label="tx('edgeConfirm.next')"
          :enabled="!reasons.length"
          :reasons="reasons.map(code => tx('edgeConfirm.reason.' + code))"
          reason-id="vt-why-edge"
          @activate="store.confirmEdge()"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import VtActionButton from './VtActionButton.vue'
import { MSA_CLAUSE, USAGE_DEV } from '../../voiceTraining/constants.js'
import { edgeConfirmGate } from '../../voiceTraining/flow.js'
import { icon } from '../../voiceTraining/icons.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true }, sessionExpired: { type: Boolean, default: false } })
const { tx } = useTrainingText()
const state = props.store.state
const expired = computed(() => props.sessionExpired)
const reasons = computed(() => edgeConfirmGate({ checked: state.edge.checked, sessionExpired: expired.value }))

function useUpload() {
  props.store.chooseSource('upload')
  props.store.go(state.slug ? 'source' : 'upload')
}
</script>
