<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section class="vt-card" aria-labelledby="vt-heading">
    <div class="vt-card-head">
      <div>
        <h2 id="vt-heading" tabindex="-1" class="vt-title"><i :class="icon('wave')" aria-hidden="true"></i> {{ tx('home.title') }}</h2>
        <p class="vt-subtitle">{{ tx('home.subtitle') }}</p>
      </div>
      <button type="button" class="vt-btn primary" @click="store.newCorpus()"><i :class="icon('upload')" aria-hidden="true"></i>{{ tx('home.newCorpus') }}</button>
    </div>

    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>

    <div v-if="active" class="vt-banner info" role="status">
      <i :class="icon('spin')" aria-hidden="true"></i>
      <div>
        <div class="vt-b-title">{{ tx('home.jobRunning') }}</div>
        <div>{{ tf('home.jobRunningBody', { stage: stageLabel, percent: percent }) }}</div>
        <div class="vt-b-actions"><button type="button" class="vt-btn small" @click="openJob">{{ tx('home.viewJob') }}</button></div>
      </div>
    </div>
    <div v-else-if="state.job" class="vt-banner" role="status">
      <i :class="icon('info')" aria-hidden="true"></i>
      <div>
        <div>{{ tf('home.lastJob', { name: state.job.name || state.job.id, status: tx('job.status.' + state.job.status) }) }}</div>
        <div class="vt-b-actions"><button type="button" class="vt-btn small" @click="openJob">{{ tx('home.viewJob') }}</button></div>
      </div>
    </div>

    <div class="vt-section">
      <h3 class="vt-section-title">{{ tx('home.corpora') }}</h3>
      <p v-if="state.loadingHome && !state.corpora.length" class="vt-hint" role="status">{{ tx('common.loading') }}</p>
      <div v-else-if="!state.corpora.length" class="vt-empty">
        <h4>{{ tx('home.emptyTitle') }}</h4>
        <p class="vt-hint">{{ tx('home.emptyBody') }}</p>
        <div class="vt-row">
          <button type="button" class="vt-btn primary" @click="start('edge')"><i :class="icon('cpu')" aria-hidden="true"></i>{{ tx('home.startEdge') }}</button>
          <button type="button" class="vt-btn" @click="start('upload')"><i :class="icon('mic')" aria-hidden="true"></i>{{ tx('home.startUpload') }}</button>
        </div>
      </div>
      <ul v-else class="vt-stack">
        <li v-for="corpus in state.corpora" :key="corpus.slug" class="vt-item">
          <div class="vt-item-main">
            <strong class="vt-mono">{{ corpus.slug }}</strong>
            <div class="vt-meta">
              <span>{{ tx('source.kind.' + corpus.source) }}</span>
              <span v-if="corpus.counts">{{ tf('home.counts', { confirmed: corpus.counts.confirmed, pending: corpus.counts.pending, total: corpus.counts.total }) }}</span>
            </div>
            <div class="vt-row"><VtUsageBadge :label="usageLabelFor(corpus.source)" /></div>
          </div>
          <div class="vt-item-actions">
            <button type="button" class="vt-btn small" :aria-label="tf('home.continueLabel', { name: corpus.slug })" @click="store.openCorpus(corpus.slug)">{{ tx('home.continue') }}</button>
          </div>
        </li>
      </ul>
    </div>

    <div class="vt-section">
      <h3 class="vt-section-title">{{ tx('home.models') }}</h3>
      <p v-if="!models.length" class="vt-hint">{{ tx('home.modelsEmpty') }}</p>
      <ul v-else class="vt-stack">
        <li v-for="model in models" :key="model.id" class="vt-item">
          <div class="vt-item-main">
            <strong>{{ model.name }}</strong>
            <div class="vt-meta"><span class="vt-mono">{{ model.id }}</span><span>{{ (model.languages || []).join(' / ') }}</span></div>
          </div>
          <VtUsageBadge :label="model.usage" />
        </li>
      </ul>
    </div>
    <p class="vt-footnote">{{ tx('usage.notLicense') }}</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import VtUsageBadge from './VtUsageBadge.vue'
import { usageLabelFor } from '../../voiceTraining/flow.js'
import { icon } from '../../voiceTraining/icons.js'
import { isActive, jobPercent } from '../../voiceTraining/jobView.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true }, models: { type: Array, default: () => [] } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const active = computed(() => isActive(state.job))
const percent = computed(() => jobPercent(state.job))
const stageLabel = computed(() => (state.job?.stages || []).find(stage => stage.id === state.job?.stage)?.label || '')

function start(path) {
  props.store.newCorpus()
  props.store.chooseSource(path)
}
async function openJob() {
  props.store.go('job')
  await props.store.pollJob()
}
</script>
