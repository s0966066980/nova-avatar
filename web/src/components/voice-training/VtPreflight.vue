<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>

    <dl class="vt-kv">
      <div><dt>{{ tx('preflight.source') }}</dt><dd>{{ tx('source.kind.' + source) }}<template v-if="state.path === 'edge'"> · {{ voiceName }}</template></dd></div>
      <div><dt>{{ tx('preflight.lines') }}</dt><dd>{{ tf('preflight.linesValue', { n: lineCount }) }}</dd></div>
      <div><dt>{{ tx('preflight.estimate') }}</dt><dd>{{ tx('preflight.estimateValue') }}</dd></div>
    </dl>

    <div class="vt-label-box">
      <h3 class="vt-section-title">{{ tx('preflight.labelTitle') }}</h3>
      <div class="vt-big"><VtUsageBadge :label="derivation.result" /></div>
      <ul>
        <li><i :class="icon('next')" aria-hidden="true"></i> {{ tf('preflight.derivCorpus', { label: derivation.corpus }) }}</li>
        <li><i :class="icon('next')" aria-hidden="true"></i> {{ tf('preflight.derivBase', { label: derivation.base }) }}</li>
        <li><i :class="icon('next')" aria-hidden="true"></i> {{ tf('preflight.derivResult', { label: derivation.result }) }}</li>
        <li v-if="derivation.noExport"><i :class="icon('next')" aria-hidden="true"></i> <strong>{{ tx('preflight.noExport') }}</strong></li>
      </ul>
      <p class="vt-footnote">{{ tx('usage.notLicense') }} {{ tx('preflight.sourceUnchanged') }}</p>
    </div>

    <div class="vt-field">
      <label for="vt-name">{{ tx('preflight.nameLabel') }}</label>
      <input
        id="vt-name" v-model="state.name" class="vt-input" maxlength="48" :placeholder="tx('preflight.namePlaceholder')"
        :aria-invalid="nameIssue && state.name ? 'true' : undefined" aria-describedby="vt-name-hint" @input="scheduleCheck"
      >
      <p id="vt-name-hint" :class="nameIssue && state.name ? 'vt-err' : 'vt-hint'">
        <template v-if="nameIssue && state.name"><i :class="icon('x-circle')" aria-hidden="true"></i>{{ tx('preflight.nameReason.' + nameIssue) }}</template>
        <template v-else>{{ tx('preflight.nameHint') }}</template>
      </p>
    </div>

    <div class="vt-section">
      <h3 class="vt-section-title">{{ tx('preflight.checksTitle') }}</h3>
      <p v-if="!state.preflight" class="vt-hint" role="status"><i :class="icon('spin')" aria-hidden="true"></i> {{ tx('preflight.checking') }}</p>
      <ul v-else class="vt-checks">
        <li v-for="check in checks" :key="check.id" :class="['vt-ck', check.tone]">
          <i :class="icon(check.icon)" aria-hidden="true"></i>
          <div class="vt-ck-main">
            <div class="vt-ck-k">{{ checkName(check) }}</div>
            <div class="vt-ck-v">{{ check.reason }}
              <button v-if="check.id === 'edge_acknowledgement'" type="button" class="vt-btn small" @click="store.go('edge-confirm')">{{ check.status === 'pass' ? tx('preflight.reread') : tx('preflight.goConfirm') }}</button>
            </div>
            <template v-if="gaugeOf(check)">
              <div class="vt-gauge" :class="{ low: check.status === 'fail' }" role="img" :aria-label="tf('preflight.gaugeLabel', { free: gaugeOf(check).free, threshold: gaugeOf(check).threshold })">
                <i :style="{ width: gaugeOf(check).freePct + '%' }"></i><b :style="{ left: gaugeOf(check).thresholdPct + '%' }"></b>
              </div>
              <div class="vt-gauge-l"><span>0</span><span>{{ tf('preflight.gaugeThreshold', { n: gaugeOf(check).threshold }) }}</span></div>
            </template>
          </div>
          <span class="vt-ck-st">{{ tx('preflight.status.' + check.status) }}</span>
        </li>
      </ul>
    </div>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="store.go(backTarget)">{{ tx('common.back') }}</button>
      <div class="vt-right">
        <button type="button" class="vt-btn" :aria-disabled="state.checking ? 'true' : undefined" @click="recheck">
          <i :class="icon(state.checking ? 'spin' : 'refresh')" aria-hidden="true"></i>{{ state.checking ? tx('preflight.checkingShort') : tx('preflight.recheck') }}
        </button>
        <VtActionButton
          primary
          icon-name="play"
          :label="tx('preflight.start')"
          :enabled="gate.canStart"
          :reasons="reasonLines"
          reason-id="vt-why-start"
          @activate="store.startTraining()"
        />
      </div>
    </div>
    <p v-if="gate.canStart" class="vt-hint">{{ tx('preflight.startHint') }}</p>
    <p v-for="warning in gate.warnings" :key="warning.id" class="vt-note"><i :class="icon('alert')" aria-hidden="true"></i><span>{{ checkNameById(warning.id) }}: {{ warning.text }}</span></p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import VtActionButton from './VtActionButton.vue'
import VtUsageBadge from './VtUsageBadge.vue'
import { EDGE_PRESETS, EDGE_VOICES, SOURCE_EDGE } from '../../voiceTraining/constants.js'
import { labelDerivation, nameProblem } from '../../voiceTraining/flow.js'
import { icon } from '../../voiceTraining/icons.js'
import { checkView, vramGauge } from '../../voiceTraining/preflight.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const gate = computed(() => props.store.gate)
const nameIssue = computed(() => nameProblem(state.name))
const source = computed(() => (state.path === 'edge' ? SOURCE_EDGE : state.corpus?.source || 'development-unlicensed'))
const derivation = computed(() => labelDerivation(source.value))
const voiceName = computed(() => EDGE_VOICES.find(voice => voice.id === state.edge.voice)?.name || state.edge.voice)
const lineCount = computed(() => {
  if (state.path !== 'edge') return state.corpus?.counts?.confirmed ?? 0
  return state.edge.textSrc === 'file' ? state.edge.sentences.length : EDGE_PRESETS.find(item => item.key === state.edge.preset)?.lines ?? 0
})
const backTarget = computed(() => (state.path === 'edge' && state.edge.textSrc === 'builtin' ? 'text' : 'review'))
const checks = computed(() => (state.preflight?.checks || []).map(check => ({ ...checkView(check), label: check.label })))

// Check names are translated by id; an id this version does not know falls back to the server's label.
function checkNameById(id, fallback = id) {
  const key = `checks.${id}`
  const text = tx(key)
  return text === `settings.voiceTraining.${key}` ? fallback : text
}
const checkName = check => checkNameById(check.id, check.label)
const gaugeOf = check => vramGauge(check)

const reasonLines = computed(() => gate.value.reasons.map(reason => {
  if (reason.id === 'unchecked') return tx('preflight.reasonUnchecked')
  if (reason.code) return `${checkNameById(reason.id)}: ${tx('preflight.nameReason.' + reason.code)}`
  return `${checkNameById(reason.id)}: ${reason.text}`
}))

let timer = null
const recheck = () => { if (!state.checking) props.store.loadPreflight() }
function scheduleCheck() {
  clearTimeout(timer)
  timer = setTimeout(() => props.store.loadPreflight(), 400)
}
onMounted(() => props.store.loadPreflight())
onBeforeUnmount(() => clearTimeout(timer))
</script>
