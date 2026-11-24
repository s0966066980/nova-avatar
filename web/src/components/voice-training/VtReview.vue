<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>
    <div class="vt-banner info">
      <i :class="icon('info')" aria-hidden="true"></i>
      <div><div class="vt-b-title">{{ tx('review.digitsTitle') }}</div>{{ tx('review.digitsBody') }}</div>
    </div>

    <div class="vt-sumbar" role="group" :aria-label="tx('review.progress')">
      <span class="vt-chip ok"><i :class="icon('check-circle')" aria-hidden="true"></i>{{ tx('review.state.confirmed') }} {{ counts.confirmed }}</span>
      <span class="vt-chip"><i :class="icon('dot')" aria-hidden="true"></i>{{ tx('review.state.pending') }} {{ counts.pending }}</span>
      <span class="vt-chip danger"><i :class="icon('alert')" aria-hidden="true"></i>{{ tx('review.state.unresolved') }} {{ counts.unresolved }}</span>
      <span class="vt-chip plain"><i :class="icon('ban')" aria-hidden="true"></i>{{ tx('review.state.excluded') }} {{ counts.excluded }}</span>
      <span class="vt-hint">{{ tf('review.total', { n: counts.total }) }}</span>
    </div>

    <div class="vt-row spread">
      <div class="vt-filters" role="group" :aria-label="tx('review.filters')">
        <button v-for="name in FILTERS" :key="name" type="button" class="vt-btn small" :aria-pressed="state.review.filter === name" @click="setFilter(name)">{{ tx('review.filter.' + name) }}</button>
      </div>
      <button type="button" class="vt-btn small" :aria-disabled="confirmable ? undefined : 'true'" @click="confirmAll">
        <i :class="icon('check-circle')" aria-hidden="true"></i>{{ tf('review.confirmAll', { n: confirmable }) }}
      </button>
    </div>
    <p class="vt-hint">{{ tx('review.confirmAllHint') }}</p>

    <div v-if="!page.items.length" class="vt-empty">
      <h4>{{ tx('review.noneTitle') }}</h4>
      <p class="vt-hint">{{ tx('review.noneBody') }}</p>
      <button type="button" class="vt-btn small" @click="setFilter('all')">{{ tx('review.showAll') }}</button>
    </div>
    <div v-else class="vt-rt" role="table" :aria-label="tx('review.tableLabel')">
      <div class="vt-rt-head" role="row">
        <span role="columnheader">#</span>
        <span role="columnheader">{{ tx('common.play') }}</span>
        <span role="columnheader">{{ tx('review.colText') }}</span>
        <span role="columnheader">{{ tx('review.colState') }}</span>
        <span role="columnheader" class="vt-right">{{ tx('review.colActions') }}</span>
      </div>
      <div v-for="line in page.items" :key="line.id" :data-row="line.id" role="row" :class="['vt-rt-row', 'is-' + rowState(line), { 'is-edit': state.review.editingId === line.id }]">
        <span class="vt-c-n" role="cell">{{ numberOf(line) }}</span>
        <div class="vt-c-p" role="cell">
          <button type="button" class="vt-btn icon small" :aria-pressed="state.review.playingId === line.id" :aria-label="tf(state.review.playingId === line.id ? 'review.stopLabel' : 'review.playLabel', { name: line.original_name })" @click="store.togglePlay(line.id)">
            <i :class="icon(state.review.playingId === line.id ? 'pause' : 'play')" aria-hidden="true"></i>
          </button>
        </div>
        <div class="vt-c-t" role="cell">
          <div class="vt-fid"><span class="vt-mono">{{ line.original_name }}</span></div>
          <template v-if="state.review.editingId === line.id">
            <label class="vt-sr" :for="'vt-ed-' + line.id">{{ tf('review.editLabel', { name: line.original_name }) }}</label>
            <textarea :id="'vt-ed-' + line.id" v-model="draft" class="vt-textarea" rows="2" :aria-invalid="state.review.editError ? 'true' : undefined" :aria-describedby="state.review.editError ? 'vt-ed-err' : undefined"></textarea>
            <p v-if="state.review.editError" id="vt-ed-err" class="vt-err"><i :class="icon('x-circle')" aria-hidden="true"></i>{{ tx('review.editEmpty') }}</p>
            <p class="vt-hint">{{ tx('review.editHint') }}</p>
          </template>
          <template v-else>
            <div class="vt-txt">
              <template v-if="!line.text">{{ tx('review.noText') }}</template>
              <template v-else><span v-for="(part, i) in textSegments(line.text, line.unresolved)" :key="i" :class="{ 'vt-bad': part.bad }">{{ part.text }}</span></template>
            </div>
            <div v-if="line.text && line.normalized_text && line.normalized_text !== line.text" class="vt-exp">
              {{ tx('review.spokenAs') }}
              <span v-for="(part, i) in expansionSegments(line.text, line.normalized_text)" :key="i" :class="{ 'vt-ex': part.expanded }">{{ part.text }}</span>
            </div>
            <p v-if="line.unresolved && line.unresolved.length && rowState(line) !== 'excluded'" class="vt-note bad"><i :class="icon('alert')" aria-hidden="true"></i><span>{{ tf('review.unresolvedNote', { parts: line.unresolved.map(part => '「' + part.text + '」').join('') }) }}</span></p>
          </template>
        </div>
        <div class="vt-c-s" role="cell">
          <span :class="['vt-chip', chipTone(line)]"><i :class="icon(chipIcon(line))" aria-hidden="true"></i>{{ tx('review.state.' + rowState(line)) }}</span>
        </div>
        <div class="vt-c-a vt-right" role="cell">
          <template v-if="state.review.editingId === line.id">
            <button type="button" class="vt-btn small primary" data-row-target @click="save(line)">{{ tx('common.save') }}</button>
            <button type="button" class="vt-btn small" @click="cancelEdit(line)">{{ tx('common.cancel') }}</button>
          </template>
          <template v-else-if="rowState(line) === 'excluded'">
            <button type="button" class="vt-btn small" data-row-target :aria-label="tf('review.restoreLabel', { name: line.original_name })" @click="act(line, 'restoreRow')">{{ tx('common.restore') }}</button>
          </template>
          <template v-else>
            <button v-if="rowState(line) === 'pending' && line.text" type="button" class="vt-btn small" data-row-target :aria-label="tf('review.confirmLabel', { name: line.original_name })" @click="act(line, 'confirmRow')"><i :class="icon('check')" aria-hidden="true"></i>{{ tx('common.confirm') }}</button>
            <button type="button" class="vt-btn small" :data-row-target="rowState(line) === 'pending' && line.text ? undefined : ''" :aria-label="tf('review.editBtnLabel', { name: line.original_name })" @click="edit(line)"><i :class="icon('pencil')" aria-hidden="true"></i>{{ tx('common.edit') }}</button>
            <button type="button" class="vt-btn small" :aria-label="tf('review.excludeLabel', { name: line.original_name })" @click="act(line, 'excludeRow')"><i :class="icon('ban')" aria-hidden="true"></i>{{ tx('common.exclude') }}</button>
          </template>
        </div>
      </div>
    </div>
    <audio ref="audio" preload="none" @ended="state.review.playingId = null"></audio>

    <div v-if="page.items.length" class="vt-pager">
      <span class="vt-hint">{{ tf('review.pager', { page: page.page + 1, pages: page.pages, per: PER_PAGE }) }}</span>
      <div class="vt-row">
        <button type="button" class="vt-btn small" :aria-disabled="page.page === 0 ? 'true' : undefined" @click="turn(-1)"><i :class="icon('prev')" aria-hidden="true"></i>{{ tx('common.prevPage') }}</button>
        <button type="button" class="vt-btn small" :aria-disabled="page.page >= page.pages - 1 ? 'true' : undefined" @click="turn(1)">{{ tx('common.nextPage') }}<i :class="icon('next')" aria-hidden="true"></i></button>
      </div>
    </div>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="store.go('text')">{{ tx('common.back') }}</button>
      <div class="vt-right">
        <VtActionButton
          primary
          :label="tx('review.toPreflight')"
          :enabled="!gate.length"
          :reasons="gate.map(reason => tf('review.reason.' + reason.code, { n: reason.count }))"
          reason-id="vt-why-review"
          @activate="store.go('preflight')"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import VtActionButton from './VtActionButton.vue'
import { icon } from '../../voiceTraining/icons.js'
import {
  confirmableIds, countRows, expansionSegments, filterRows, paginate, reviewGate, rowState, textSegments
} from '../../voiceTraining/reviewTable.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const FILTERS = ['all', 'pending', 'attention', 'excluded']
const PER_PAGE = 10
const props = defineProps({ store: { type: Object, required: true } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const audio = ref(null)
const draft = ref('')

const lines = computed(() => state.corpus?.lines || [])
const counts = computed(() => countRows(lines.value))
const confirmable = computed(() => confirmableIds(lines.value).length)
const filtered = computed(() => filterRows(lines.value, state.review.filter))
const page = computed(() => paginate(filtered.value, state.review.page, PER_PAGE))
const gate = computed(() => reviewGate(lines.value))
const numberOf = line => lines.value.indexOf(line) + 1
const chipTone = line => ({ confirmed: 'ok', pending: '', excluded: 'plain', unresolved: 'danger' })[rowState(line)]
const chipIcon = line => ({ confirmed: 'check-circle', pending: 'dot', excluded: 'ban', unresolved: 'alert' })[rowState(line)]

onMounted(() => props.store.loadCorpus())

function setFilter(name) { state.review.filter = name; state.review.page = 0 }
function turn(step) { state.review.page = Math.min(Math.max(0, page.value.page + step), page.value.pages - 1) }

// After a row changes its buttons may be replaced: put focus back on the row's first action.
async function focusRow(id) {
  await nextTick()
  globalThis.document?.querySelector?.(`[data-row="${id}"] [data-row-target]`)?.focus?.()
}
async function act(line, action) {
  await props.store[action](line.id)
  focusRow(line.id)
}
function edit(line) { draft.value = line.text || ''; props.store.startEdit(line.id) }
async function save(line) {
  await props.store.saveEdit(line.id, draft.value)
  focusRow(line.id)
}
function cancelEdit(line) { props.store.cancelEdit(); focusRow(line.id) }
async function confirmAll() {
  if (confirmable.value) await props.store.confirmAllPending()
}

// One player for the whole table: the pressed row's audio plays, pressing again stops it.
watch(() => state.review.playingId, id => {
  const player = audio.value
  if (!player) return
  if (!id) { player.pause?.(); return }
  player.src = props.store.audioUrl(id)
  const started = player.play?.()
  if (started?.catch) started.catch(() => { state.review.playingId = null })
})
</script>
