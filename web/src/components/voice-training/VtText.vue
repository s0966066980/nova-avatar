<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>

    <template v-if="edge">
      <fieldset class="vt-group">
        <legend class="vt-section-title">{{ tx('text.edgeLegend') }}</legend>
        <label class="vt-opt">
          <input v-model="state.edge.textSrc" type="radio" name="vt-tsrc" value="builtin">
          <span class="vt-opt-t">{{ tx('text.builtin') }}</span>
          <span class="vt-opt-d">{{ tf('text.builtinDesc', { preset: tx('source.presets.' + state.edge.preset), lines: presetLines }) }}</span>
        </label>
        <label class="vt-opt">
          <input v-model="state.edge.textSrc" type="radio" name="vt-tsrc" value="file">
          <span class="vt-opt-t">{{ tx('text.fileSrc') }}</span>
          <span class="vt-opt-d">{{ tx('text.fileSrcDesc') }}</span>
        </label>
      </fieldset>
      <div v-if="state.edge.textSrc === 'file'" class="vt-section">
        <div v-if="!state.edge.sentences.length" class="vt-drop">
          <div class="vt-row"><i :class="icon('file')" aria-hidden="true"></i><strong>{{ tx('text.pickTxt') }}</strong></div>
          <p class="vt-hint">{{ tx('text.pickTxtHint') }}</p>
          <label class="vt-btn" for="vt-edge-txt"><i :class="icon('upload')" aria-hidden="true"></i>{{ tx('text.chooseTxt') }}</label>
          <input id="vt-edge-txt" class="vt-sr" type="file" :accept="EDGE_TEXT_ACCEPT" @change="onEdgeFile">
        </div>
        <div v-else class="vt-banner ok" role="status">
          <i :class="icon('check-circle')" aria-hidden="true"></i>
          <div>
            <div class="vt-b-title">{{ tf('text.txtLoaded', { n: state.edge.sentences.length }) }}</div>
            {{ tx('text.txtLoadedBody') }}
            <div class="vt-b-actions"><button type="button" class="vt-btn small" @click="store.clearEdgeText()">{{ tx('common.reselect') }}</button></div>
          </div>
        </div>
      </div>
    </template>

    <template v-else>
      <fieldset class="vt-group">
        <legend class="vt-section-title">{{ tx('text.trLegend') }}</legend>
        <label class="vt-opt">
          <input v-model="state.tr.src" type="radio" name="vt-trs" value="file">
          <span class="vt-opt-t">{{ tx('text.trFile') }}</span>
          <span class="vt-opt-d">{{ tx('text.trFileDesc') }}</span>
        </label>
        <label class="vt-opt">
          <input v-model="state.tr.src" type="radio" name="vt-trs" value="whisper">
          <span class="vt-opt-t">{{ tx('text.trAuto') }}</span>
          <span class="vt-opt-d">{{ tx('text.trAutoDesc') }}</span>
        </label>
      </fieldset>

      <div v-if="state.tr.src === 'file'" class="vt-section">
        <div class="vt-drop">
          <div class="vt-row"><i :class="icon('file')" aria-hidden="true"></i><strong>{{ tx('text.pickTranscript') }}</strong></div>
          <p class="vt-hint">{{ tx('text.pickTranscriptHint') }}</p>
          <label class="vt-btn" for="vt-transcript-files"><i :class="icon('upload')" aria-hidden="true"></i>{{ tx('text.chooseTranscript') }}</label>
          <input id="vt-transcript-files" class="vt-sr" type="file" multiple :accept="TRANSCRIPT_ACCEPT" @change="onTranscripts">
        </div>
        <p v-if="state.tr.busy" class="vt-hint" role="status"><i :class="icon('spin')" aria-hidden="true"></i> {{ tx('common.loading') }}</p>
        <div v-if="state.tr.problems.length" class="vt-banner danger" role="alert">
          <i :class="icon('x-circle')" aria-hidden="true"></i>
          <div>
            <div class="vt-b-title">{{ tx('text.importFailed') }}</div>
            <ul class="vt-problems"><li v-for="problem in state.tr.problems" :key="problem">{{ problem }}</li></ul>
            <p>{{ tx('text.importNothingApplied') }}</p>
          </div>
        </div>
        <div v-if="state.tr.imported" class="vt-banner ok" role="status">
          <i :class="icon('check-circle')" aria-hidden="true"></i>
          <div><div class="vt-b-title">{{ tf('text.imported', { n: state.tr.imported.applied }) }}</div></div>
        </div>
        <div v-if="state.tr.imported && state.tr.imported.without.length" class="vt-banner warn" role="status">
          <i :class="icon('alert')" aria-hidden="true"></i>
          <div>
            <div class="vt-b-title">{{ tf('text.withoutText', { n: state.tr.imported.without.length }) }}</div>
            {{ tx('text.withoutTextBody') }}
          </div>
        </div>
      </div>

      <div v-else class="vt-section">
        <template v-if="!auto.running">
          <div class="vt-field">
            <label for="vt-whisper-model">{{ tx('text.model') }}</label>
            <select id="vt-whisper-model" v-model="state.tr.model" class="vt-select">
              <option v-for="model in WHISPER_MODELS" :key="model" :value="model">{{ tx('text.models.' + model) }}</option>
            </select>
            <p class="vt-hint">{{ tx('text.modelHint') }}</p>
          </div>
          <div v-if="auto.state === 'failed'" class="vt-banner danger" role="alert">
            <i :class="icon('x-circle')" aria-hidden="true"></i>
            <div><div class="vt-b-title">{{ tx('text.autoFailed') }}</div>{{ auto.message }}</div>
          </div>
          <div v-if="auto.state === 'cancelled'" class="vt-banner warn" role="status">
            <i :class="icon('alert')" aria-hidden="true"></i><div>{{ tx('text.autoCancelled') }}</div>
          </div>
          <div v-if="auto.state === 'done'" class="vt-banner ok" role="status">
            <i :class="icon('check-circle')" aria-hidden="true"></i>
            <div>
              <div class="vt-b-title">{{ tf('text.autoDone', { n: auto.done }) }}</div>
              {{ tx('text.autoDoneBody') }}
              <div v-if="auto.failed.length">{{ tf('text.autoSomeFailed', { n: auto.failed.length }) }}</div>
            </div>
          </div>
          <div class="vt-row">
            <button type="button" class="vt-btn primary" @click="store.startAutoTranscription()"><i :class="icon('wave')" aria-hidden="true"></i>{{ auto.state === 'done' ? tx('text.autoAgain') : tx('text.autoStart') }}</button>
          </div>
        </template>
        <div v-else class="vt-stack" role="group" :aria-label="tx('text.autoProgress')">
          <div class="vt-row"><i :class="icon('spin')" aria-hidden="true"></i><strong>{{ tf('text.autoRunning', { done: auto.done, total: auto.total }) }}</strong></div>
          <div class="vt-bar" role="progressbar" aria-valuemin="0" :aria-valuemax="auto.total || 100" :aria-valuenow="auto.done" :aria-label="tx('text.autoProgress')"><i :style="{ width: auto.percent + '%' }"></i></div>
          <div class="vt-device" role="status">
            <p v-if="auto.device"><i :class="icon(auto.device === 'cpu' ? 'cpu' : 'wave')" aria-hidden="true"></i>
              {{ auto.device === 'cpu' ? tx('text.deviceCpu') : tx('text.deviceCuda') }}</p>
            <p v-if="auto.fallbackReason" class="vt-hint"><strong>{{ tx('text.fallbackWhy') }}</strong> {{ auto.fallbackReason }}</p>
            <p v-if="auto.slowNote" class="vt-hint">{{ tf('text.cpuEstimate', { minutes: cpuMinutes }) }}</p>
          </div>
          <div><button type="button" class="vt-btn small danger" :aria-disabled="auto.cancelling ? 'true' : undefined" @click="cancelAuto"><i :class="icon('stop')" aria-hidden="true"></i>{{ auto.cancelling ? tx('text.cancelling') : tx('common.cancel') }}</button></div>
        </div>
      </div>
    </template>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="store.go(edge && state.edge.acknowledged ? 'source' : edge ? 'edge-confirm' : 'upload')">{{ tx('common.back') }}</button>
      <div class="vt-right">
        <VtActionButton
          primary
          :label="edge && state.edge.textSrc === 'builtin' ? tx('text.toPreflight') : tx('text.toReview')"
          :enabled="!reasons.length"
          :reasons="reasons.map(code => tx('text.reason.' + code))"
          reason-id="vt-why-text"
          @activate="store.go(edge && state.edge.textSrc === 'builtin' ? 'preflight' : 'review')"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import VtActionButton from './VtActionButton.vue'
import { EDGE_PRESETS, EDGE_TEXT_ACCEPT, TRANSCRIPT_ACCEPT, WHISPER_MODELS } from '../../voiceTraining/constants.js'
import { icon } from '../../voiceTraining/icons.js'
import { roundMinutes } from '../../voiceTraining/format.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const edge = computed(() => state.path === 'edge')
const auto = computed(() => props.store.transcription)
const presetLines = computed(() => EDGE_PRESETS.find(item => item.key === state.edge.preset)?.lines ?? 0)
// Ticket 06 measured about one second per sentence on CPU with the small model; larger models are slower.
const cpuMinutes = computed(() => roundMinutes(Math.max(0, auto.value.total - auto.value.done) * (state.tr.model === 'small' ? 1 : 3)))

const linesWithText = computed(() => (state.corpus?.lines || []).filter(line => String(line.text || '').trim()).length)
const reasons = computed(() => {
  if (edge.value) return state.edge.textSrc === 'file' && !state.edge.sentences.length ? ['pick_txt'] : []
  if (auto.value.running) return ['running']
  return linesWithText.value ? [] : ['none']
})

onMounted(() => { if (!edge.value) props.store.loadCorpus() })

const onEdgeFile = async event => {
  const file = event.target.files?.[0]
  if (file) await props.store.loadEdgeTextFile(file)
  event.target.value = ''
}
const onTranscripts = async event => {
  const files = [...(event.target.files || [])]
  if (files.length) await props.store.importTranscripts(files)
  event.target.value = ''
}
const cancelAuto = () => { if (!auto.value.cancelling) props.store.cancelAutoTranscription() }
</script>
