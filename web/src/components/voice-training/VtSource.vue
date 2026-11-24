<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <fieldset class="vt-group">
      <legend class="vt-section-title">{{ tx('source.legend') }}</legend>
      <div class="vt-opt-grid">
        <label class="vt-opt">
          <input type="radio" name="vt-path" value="edge" :checked="state.path === 'edge'" :disabled="locked" @change="store.chooseSource('edge')">
          <span class="vt-opt-t"><i :class="icon('cpu')" aria-hidden="true"></i>{{ tx('source.edge') }} <VtUsageBadge :label="USAGE_DEV" /></span>
          <span class="vt-opt-d">{{ tx('source.edgeDesc') }}</span>
        </label>
        <label class="vt-opt">
          <input type="radio" name="vt-path" value="upload" :checked="state.path === 'upload'" :disabled="locked" @change="store.chooseSource('upload')">
          <span class="vt-opt-t"><i :class="icon('mic')" aria-hidden="true"></i>{{ tx('source.upload') }}</span>
          <span class="vt-opt-d">{{ tx('source.uploadDesc') }}</span>
        </label>
      </div>
      <p v-if="locked" class="vt-hint">{{ tx('source.locked') }}</p>
    </fieldset>

    <div v-if="state.path === 'edge'" class="vt-section">
      <h3 class="vt-section-title"><i :class="icon('cpu')" aria-hidden="true"></i>{{ tx('source.edgeSettings') }}</h3>
      <div class="vt-fgrid">
        <div class="vt-field">
          <label for="vt-edge-voice">{{ tx('source.voice') }}</label>
          <select id="vt-edge-voice" v-model="state.edge.voice" class="vt-select">
            <option v-for="voice in EDGE_VOICES" :key="voice.id" :value="voice.id">{{ voice.name }}{{ voice.isDefault ? ' ' + tx('source.voiceDefault') : '' }}</option>
          </select>
          <p class="vt-hint">{{ tx('source.voiceHint') }}</p>
        </div>
        <fieldset class="vt-group">
          <legend class="vt-label">{{ tx('source.preset') }}</legend>
          <label v-for="preset in EDGE_PRESETS" :key="preset.key" class="vt-opt">
            <input v-model="state.edge.preset" type="radio" name="vt-preset" :value="preset.key">
            <span class="vt-opt-t">{{ tx('source.presets.' + preset.key) }}</span>
            <span class="vt-opt-d">{{ tf('source.presetDesc', { minutes: preset.minutes, lines: preset.lines }) }}</span>
          </label>
        </fieldset>
      </div>
      <p class="vt-hint">{{ tx('source.pace') }}</p>
    </div>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="store.go('home')">{{ tx('common.backHome') }}</button>
      <div class="vt-right">
        <VtActionButton
          primary
          :label="state.path === 'edge' ? tx('source.nextEdge') : tx('source.nextUpload')"
          :enabled="!reasons.length"
          :reasons="reasons.map(code => tx('source.reason.' + code))"
          reason-id="vt-why-source"
          @activate="next"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import VtActionButton from './VtActionButton.vue'
import VtUsageBadge from './VtUsageBadge.vue'
import { EDGE_PRESETS, EDGE_VOICES, USAGE_DEV } from '../../voiceTraining/constants.js'
import { sourceGate } from '../../voiceTraining/flow.js'
import { icon } from '../../voiceTraining/icons.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const reasons = computed(() => sourceGate(state.path))
// A corpus that already exists keeps its source.
const locked = computed(() => Boolean(state.slug))

function next() {
  if (state.path === 'edge') props.store.go(state.edge.acknowledged ? 'text' : 'edge-confirm')
  else props.store.go('upload')
}
</script>
