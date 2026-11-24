<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <div v-if="job && job.status === 'done'" class="vt-banner ok">
      <i :class="icon('check-circle')" aria-hidden="true"></i>
      <div><div class="vt-b-title">{{ tf('done.created', { name: job.name }) }}</div>{{ tx('done.createdBody') }}</div>
    </div>
    <div v-else class="vt-banner warn" role="status">
      <i :class="icon('alert')" aria-hidden="true"></i>
      <div><div class="vt-b-title">{{ tx('done.notDoneTitle') }}</div>{{ tx('done.notDoneBody') }}
        <div class="vt-b-actions"><button type="button" class="vt-btn small" @click="store.go('job')">{{ tx('done.toJob') }}</button></div></div>
    </div>

    <template v-if="job && job.status === 'done'">
      <dl class="vt-kv">
        <div><dt>{{ tx('done.name') }}</dt><dd>{{ job.name }}</dd></div>
        <div><dt>{{ tx('done.id') }}</dt><dd class="vt-mono">{{ job.voice_id }}</dd></div>
        <div><dt>{{ tx('done.label') }}</dt><dd><VtUsageBadge :label="job.usage" /></dd></div>
        <div><dt>{{ tx('done.languages') }}</dt><dd>{{ tx('done.languagesValue') }}</dd></div>
        <div v-if="job.source"><dt>{{ tx('done.source') }}</dt><dd>{{ sourceText }}</dd></div>
        <div v-if="steps"><dt>{{ tx('done.steps') }}</dt><dd>{{ steps }}</dd></div>
      </dl>

      <div class="vt-label-box">
        <div class="vt-big"><VtUsageBadge :label="job.usage" /></div>
        <ul>
          <li v-if="job.usage === USAGE_DEV"><i :class="icon('next')" aria-hidden="true"></i> {{ tx('done.devNote') }}</li>
          <li v-if="isEdge"><i :class="icon('next')" aria-hidden="true"></i> <strong>{{ tx('preflight.noExport') }}</strong></li>
          <li><i :class="icon('next')" aria-hidden="true"></i> {{ tx('usage.notLicense') }}</li>
        </ul>
      </div>

      <div class="vt-player">
        <h3 class="vt-section-title">{{ tx('done.previewTitle') }}</h3>
        <p class="vt-hint">{{ tx('done.previewHint') }}</p>
        <ul class="vt-stack">
          <li v-for="item in PREVIEW_SENTENCES" :key="item.key" class="vt-item">
            <div class="vt-item-main">
              <strong>{{ tx('done.sentences.' + item.key) }}</strong>
              <div class="vt-txt" :lang="item.key === 'en' ? 'en' : undefined">{{ item.text }}</div>
              <p v-if="!store.previewAvailable(item.key)" :id="'vt-pv-why-' + item.key" class="vt-hint">{{ tx('done.previewUnavailable') }}</p>
            </div>
            <button
              type="button" class="vt-btn small" :aria-pressed="state.preview.key === item.key && Boolean(state.preview.audio)"
              :aria-disabled="store.previewAvailable(item.key) ? undefined : 'true'"
              :aria-describedby="store.previewAvailable(item.key) ? undefined : 'vt-pv-why-' + item.key"
              @click="store.previewVoice(item.key)"
            >
              <i :class="icon(state.preview.loading && state.preview.key === item.key ? 'spin' : 'play')" aria-hidden="true"></i>{{ tx('common.play') }}
            </button>
          </li>
        </ul>
        <p v-if="state.preview.error" class="vt-err" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i>{{ state.preview.error }}</p>
        <audio v-if="state.preview.audio" :src="state.preview.audio" controls controlsList="nodownload" autoplay :aria-label="tx('done.playerLabel')"></audio>
      </div>
    </template>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="store.go('home')">{{ tx('common.backHome') }}</button>
      <div class="vt-right">
        <button type="button" class="vt-btn primary" @click="emit('open-profiles')"><i :class="icon('next')" aria-hidden="true"></i>{{ tx('done.toProfile') }}</button>
      </div>
    </div>
    <p class="vt-hint">{{ tx('done.profileHint') }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import VtUsageBadge from './VtUsageBadge.vue'
import { PREVIEW_SENTENCES, SOURCE_EDGE, USAGE_DEV } from '../../voiceTraining/constants.js'
import { icon } from '../../voiceTraining/icons.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true } })
const emit = defineEmits(['open-profiles'])
const { tx, tf } = useTrainingText()
const state = props.store.state
const job = computed(() => state.job)
const isEdge = computed(() => job.value?.source === SOURCE_EDGE || state.path === 'edge')
const sourceText = computed(() => {
  const key = `source.kind.${job.value?.source}`
  const text = tx(key)
  return text === `settings.voiceTraining.${key}` ? String(job.value?.source) : text
})
const steps = computed(() => {
  const metrics = job.value?.metrics
  if (!metrics?.total_steps) return ''
  const minutes = metrics.training_seconds ? Math.max(1, Math.round(metrics.training_seconds / 60)) : 0
  return tf('done.stepsValue', { step: metrics.step ?? metrics.total_steps, total: metrics.total_steps, minutes })
})
</script>
