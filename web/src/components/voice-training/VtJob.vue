<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>

    <div v-if="!job" class="vt-banner warn" role="status">
      <i :class="icon('alert')" aria-hidden="true"></i>
      <div><div class="vt-b-title">{{ tx('job.noneTitle') }}</div>{{ tx('job.noneBody') }}</div>
    </div>
    <template v-else>
      <div v-if="job.status === 'failed'" class="vt-banner danger" role="alert">
        <i :class="icon('x-circle')" aria-hidden="true"></i>
        <div><div class="vt-b-title">{{ tx('job.failedTitle') }}</div>{{ job.error || job.message }}<div>{{ tx('job.failedNext') }}</div>
          <div class="vt-b-actions"><button type="button" class="vt-btn small" @click="store.go('preflight')">{{ tx('job.toPreflight') }}</button></div></div>
      </div>
      <div v-if="job.status === 'cancelled'" class="vt-banner warn" role="status">
        <i :class="icon('alert')" aria-hidden="true"></i>
        <div><div class="vt-b-title">{{ tx('job.cancelledTitle') }}</div>{{ tx('job.cancelledBody') }}
          <div class="vt-b-actions"><button type="button" class="vt-btn small" @click="store.go('preflight')">{{ tx('job.toPreflight') }}</button></div></div>
      </div>
      <div v-if="job.status === 'done'" class="vt-banner ok" role="status">
        <i :class="icon('check-circle')" aria-hidden="true"></i>
        <div><div class="vt-b-title">{{ tx('job.doneTitle') }}</div>{{ tx('job.doneBody') }}
          <div class="vt-b-actions"><button type="button" class="vt-btn small primary" @click="store.go('done')">{{ tx('job.viewResult') }}</button></div></div>
      </div>
      <div v-if="job.status === 'cancelling'" class="vt-banner info" role="status">
        <i :class="icon('spin')" aria-hidden="true"></i><div><div class="vt-b-title">{{ tx('job.cancellingTitle') }}</div>{{ tx('job.cancellingBody') }}</div>
      </div>

      <div class="vt-stack">
        <div class="vt-row spread"><strong>{{ tf('job.overall', { n: percent }) }}</strong><span v-if="job.message" class="vt-hint">{{ job.message }}</span></div>
        <div :class="['vt-bar', { ok: job.status === 'done', bad: job.status === 'failed' }]" role="progressbar" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="percent" :aria-label="tx('job.overallLabel')"><i :style="{ width: percent + '%' }"></i></div>
      </div>

      <ol class="vt-stages" :aria-label="tx('job.stagesLabel')">
        <li v-for="stage in stages" :key="stage.id" :class="['vt-stage', stage.tone]">
          <i :class="icon(stage.icon)" aria-hidden="true"></i>
          <span class="vt-stage-name">{{ tx('job.stages.' + stage.id) === 'settings.voiceTraining.job.stages.' + stage.id ? stage.label : tx('job.stages.' + stage.id) }}</span>
          <span class="vt-stage-st">{{ tx('job.stageStatus.' + stage.status) }}</span>
          <span v-if="stage.detail" class="vt-stage-dt">{{ stage.detail }}</span>
        </li>
      </ol>
    </template>

    <div class="vt-section">
      <div class="vt-row spread">
        <h3 class="vt-section-title">{{ tx('job.log') }}</h3>
        <button type="button" class="vt-btn small" @click="copyLog"><i :class="icon('copy')" aria-hidden="true"></i>{{ copied ? tx('job.copied') : tx('job.copyLog') }}</button>
      </div>
      <div ref="logBox" class="vt-log" role="log" tabindex="0" :aria-label="tx('job.logLabel')" @scroll="onScroll">
        <div v-for="(row, index) in state.log.lines" :key="index" :class="logTone(row)">{{ row }}</div>
        <div v-if="!state.log.lines.length" class="vt-hint">{{ tx('job.logEmpty') }}</div>
      </div>
      <p v-if="state.log.gap" class="vt-hint">{{ tx('job.logGap') }}</p>
      <p class="vt-hint">{{ tx('job.leaveHint') }}</p>
    </div>

    <div v-if="state.confirmCancel" class="vt-confirm-cancel" role="group" aria-labelledby="vt-cc-t" aria-describedby="vt-cc-d" @keydown.esc="store.keepTraining()">
      <strong id="vt-cc-t">{{ tx('job.cancelAsk') }}</strong>
      <p id="vt-cc-d" class="vt-hint">{{ tx('job.cancelConsequence') }}</p>
      <div class="vt-row">
        <button type="button" class="vt-btn danger-solid" @click="store.confirmCancelJob()">{{ tx('job.cancelConfirm') }}</button>
        <button ref="keepButton" type="button" class="vt-btn" @click="store.keepTraining()">{{ tx('job.keepGoing') }}</button>
      </div>
    </div>
    <div v-else class="vt-foot">
      <button v-if="active" type="button" class="vt-btn danger" @click="store.askCancel()"><i :class="icon('stop')" aria-hidden="true"></i>{{ tx('job.cancelJob') }}</button>
      <button v-else type="button" class="vt-btn" @click="store.go('home')">{{ tx('common.backHome') }}</button>
      <span v-if="active" class="vt-hint">{{ tx('job.cancelHint') }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { icon } from '../../voiceTraining/icons.js'
import { isActive, jobPercent, logTone, stageRows } from '../../voiceTraining/jobView.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const logBox = ref(null)
const keepButton = ref(null)
const copied = ref(false)
let following = true

const job = computed(() => state.job)
const active = computed(() => isActive(state.job))
const percent = computed(() => jobPercent(state.job))
const stages = computed(() => stageRows(state.job))

function onScroll() {
  const box = logBox.value
  following = !box || box.scrollHeight - box.scrollTop - box.clientHeight < 24
}
watch(() => state.log.lines.length, async () => {
  if (!following) return
  await nextTick()
  const box = logBox.value
  if (box) box.scrollTop = box.scrollHeight
})
// The confirmation opens with focus on the safe choice.
watch(() => state.confirmCancel, async open => {
  if (!open) return
  await nextTick()
  keepButton.value?.focus?.()
})

async function copyLog() {
  try {
    await globalThis.navigator?.clipboard?.writeText(state.log.lines.join('\n'))
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    copied.value = false
  }
}
</script>
