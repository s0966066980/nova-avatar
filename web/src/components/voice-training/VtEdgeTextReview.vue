<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>

    <template v-if="builtin">
      <div class="vt-banner ok">
        <i :class="icon('check-circle')" aria-hidden="true"></i>
        <div><div class="vt-b-title">{{ tx('edgeReview.builtinTitle') }}</div>{{ tf('edgeReview.builtinBody', { preset: tx('source.presets.' + state.edge.preset), lines: presetLines }) }}</div>
      </div>
    </template>

    <template v-else>
      <div class="vt-banner info">
        <i :class="icon('info')" aria-hidden="true"></i>
        <div><div class="vt-b-title">{{ tx('edgeReview.beforeTitle') }}</div>{{ tx('edgeReview.beforeBody') }}</div>
      </div>
      <div class="vt-sumbar" role="group" :aria-label="tx('review.progress')">
        <span class="vt-chip ok"><i :class="icon('check-circle')" aria-hidden="true"></i>{{ tx('edgeReview.usable') }} {{ review.counts.confirmed }}</span>
        <span class="vt-chip danger"><i :class="icon('alert')" aria-hidden="true"></i>{{ tx('review.state.unresolved') }} {{ review.counts.unresolved }}</span>
        <span class="vt-hint">{{ tf('review.total', { n: review.counts.total }) }}</span>
        <span v-if="minutes" class="vt-hint">{{ tf('edgeReview.estimate', { minutes }) }}</span>
        <span v-if="state.edge.previewing" class="vt-hint" role="status"><i :class="icon('spin')" aria-hidden="true"></i> {{ tx('edgeReview.checking') }}</span>
      </div>
      <p class="vt-hint"><i :class="icon('info')" aria-hidden="true"></i> {{ tx('edgeReview.noAudio') }}</p>

      <div v-if="!page.items.length" class="vt-empty"><h4>{{ tx('edgeReview.emptyTitle') }}</h4><p class="vt-hint">{{ tx('edgeReview.emptyBody') }}</p></div>
      <div v-else class="vt-rt vt-rt-edge" role="table" :aria-label="tx('edgeReview.tableLabel')">
        <div class="vt-rt-head" role="row">
          <span role="columnheader">#</span>
          <span role="columnheader">{{ tx('common.play') }}</span>
          <span role="columnheader">{{ tx('edgeReview.colText') }}</span>
          <span role="columnheader">{{ tx('review.colState') }}</span>
          <span role="columnheader" class="vt-right">{{ tx('review.colActions') }}</span>
        </div>
        <div v-for="row in page.items" :key="row.position + row.text" :data-row="row.position" role="row" :class="['vt-rt-row', row.state === 'unresolved' ? 'is-unresolved' : 'is-confirmed', { 'is-edit': editing === row.position }]">
          <span class="vt-c-n" role="cell">{{ row.position + 1 }}</span>
          <div class="vt-c-p" role="cell">
            <button type="button" class="vt-btn icon small" aria-disabled="true" :title="tx('edgeReview.noAudioShort')" :aria-label="tf('edgeReview.playDisabled', { n: row.position + 1 })"><i :class="icon('play')" aria-hidden="true"></i></button>
          </div>
          <div class="vt-c-t" role="cell">
            <template v-if="editing === row.position">
              <label class="vt-sr" :for="'vt-edge-ed-' + row.position">{{ tf('edgeReview.editLabel', { n: row.position + 1 }) }}</label>
              <textarea :id="'vt-edge-ed-' + row.position" v-model="draft" class="vt-textarea" rows="2"></textarea>
              <p class="vt-hint">{{ tx('edgeReview.editHint') }}</p>
            </template>
            <template v-else>
              <div class="vt-txt"><span v-for="(part, i) in textSegments(row.text, row.unresolved)" :key="i" :class="{ 'vt-bad': part.bad }">{{ part.text }}</span></div>
              <div v-if="row.spoken !== row.text" class="vt-exp">
                {{ tx('review.spokenAs') }}
                <span v-for="(part, i) in expansionSegments(row.text, row.spoken)" :key="i" :class="{ 'vt-ex': part.expanded }">{{ part.text }}</span>
              </div>
              <p v-if="row.unresolved.length" class="vt-note bad"><i :class="icon('alert')" aria-hidden="true"></i><span>{{ tf('edgeReview.unresolvedNote', { n: row.position + 1, parts: row.unresolved.map(part => '「' + part.text + '」').join('') }) }}</span></p>
            </template>
          </div>
          <div class="vt-c-s" role="cell">
            <span :class="['vt-chip', row.state === 'unresolved' ? 'danger' : 'ok']"><i :class="icon(row.state === 'unresolved' ? 'alert' : 'check-circle')" aria-hidden="true"></i>{{ row.state === 'unresolved' ? tx('review.state.unresolved') : tx('edgeReview.usable') }}</span>
          </div>
          <div class="vt-c-a vt-right" role="cell">
            <template v-if="editing === row.position">
              <button type="button" class="vt-btn small primary" data-row-target @click="save(row)">{{ tx('common.save') }}</button>
              <button type="button" class="vt-btn small" @click="editing = null">{{ tx('common.cancel') }}</button>
            </template>
            <template v-else>
              <button type="button" class="vt-btn small" data-row-target :aria-label="tf('edgeReview.editBtnLabel', { n: row.position + 1 })" @click="edit(row)"><i :class="icon('pencil')" aria-hidden="true"></i>{{ tx('common.edit') }}</button>
              <button type="button" class="vt-btn small" :aria-label="tf('edgeReview.removeLabel', { n: row.position + 1 })" @click="remove(row)"><i :class="icon('ban')" aria-hidden="true"></i>{{ tx('edgeReview.remove') }}</button>
            </template>
          </div>
        </div>
      </div>
      <div v-if="page.items.length" class="vt-pager">
        <span class="vt-hint">{{ tf('review.pager', { page: page.page + 1, pages: page.pages, per: PER_PAGE }) }}</span>
        <div class="vt-row">
          <button type="button" class="vt-btn small" :aria-disabled="page.page === 0 ? 'true' : undefined" @click="turn(-1)"><i :class="icon('prev')" aria-hidden="true"></i>{{ tx('common.prevPage') }}</button>
          <button type="button" class="vt-btn small" :aria-disabled="page.page >= page.pages - 1 ? 'true' : undefined" @click="turn(1)">{{ tx('common.nextPage') }}<i :class="icon('next')" aria-hidden="true"></i></button>
        </div>
      </div>
    </template>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="store.go('text')">{{ tx('common.back') }}</button>
      <div class="vt-right">
        <VtActionButton
          primary
          :label="tx('review.toPreflight')"
          :enabled="!reasons.length"
          :reasons="reasons.map(code => tf('edgeReview.reason.' + code, { n: review.counts.unresolved }))"
          reason-id="vt-why-edge-review"
          @activate="store.go('preflight')"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import VtActionButton from './VtActionButton.vue'
import { EDGE_PRESETS } from '../../voiceTraining/constants.js'
import { roundMinutes } from '../../voiceTraining/format.js'
import { icon } from '../../voiceTraining/icons.js'
import { expansionSegments, paginate, textSegments } from '../../voiceTraining/reviewTable.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const PER_PAGE = 10
const props = defineProps({ store: { type: Object, required: true } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const editing = ref(null)
const draft = ref('')
const page_ = ref(0)

const builtin = computed(() => state.edge.textSrc === 'builtin')
const presetLines = computed(() => EDGE_PRESETS.find(item => item.key === state.edge.preset)?.lines ?? 0)
const review = computed(() => props.store.edgeReview)
const page = computed(() => paginate(review.value.rows, page_.value, PER_PAGE))
const minutes = computed(() => roundMinutes(state.edge.preview?.estimatedSeconds))
const reasons = computed(() => {
  if (builtin.value || review.value.canContinue) return []
  if (state.edge.previewing) return ['checking']
  return review.value.counts.total ? ['unresolved'] : ['empty']
})

function turn(step) { page_.value = Math.min(Math.max(0, page.value.page + step), page.value.pages - 1) }
function edit(row) { draft.value = row.text; editing.value = row.position }
async function focusRow(position) {
  await nextTick()
  globalThis.document?.querySelector?.(`[data-row="${position}"] [data-row-target]`)?.focus?.()
}
async function save(row) {
  const position = row.position
  editing.value = null
  await props.store.editEdgeSentence(position, draft.value)
  focusRow(position)
}
async function remove(row) {
  const position = row.position
  await props.store.removeEdgeSentence(position)
  focusRow(Math.min(position, review.value.rows.length - 1))
}
</script>
