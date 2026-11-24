<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section class="setting-card" aria-labelledby="voice-model-catalog-title">
    <div class="card-title-row">
      <div>
        <div id="voice-model-catalog-title" class="card-title-text"><i class="bi bi-music-note-beamed" aria-hidden="true"></i> {{ t('settings.voiceModels.title') }}</div>
        <div class="card-subtitle-desc">{{ t('settings.voiceModels.desc') }}</div>
      </div>
    </div>
    <ul v-if="models.length" class="voice-model-list">
      <li v-for="model in models" :key="model.id">
        <strong>{{ voiceModelLabel(model) }}</strong>
        <span class="voice-model-meta"><span class="mono">{{ model.id }}</span> · {{ model.languages.join(' / ') }}</span>
        <span v-if="voiceModelMeasurement(t, model.id)" class="voice-model-meta">{{ voiceModelMeasurement(t, model.id) }}</span>
      </li>
    </ul>
    <p v-else class="voice-model-empty" role="status">{{ t('settings.voiceModels.empty') }}</p>
    <p class="voice-model-note">{{ t('settings.voiceModels.cpu') }}</p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from '../composables/useI18n.js'
import { useRuntimeSettings } from '../composables/useRuntimeSettings.js'
import { voiceModelLabel, voiceModelMeasurement } from '../voiceSelection.js'

const { t } = useI18n()
const { speech } = useRuntimeSettings()
// The server lists only complete voice models that carry a usage label.
const models = computed(() => (Array.isArray(speech.tts.voice_models) ? speech.tts.voice_models : []))
</script>

<style scoped>
.voice-model-list{list-style:none;margin:12px 0;padding:0;display:grid;gap:10px}
.voice-model-list li{display:grid;gap:4px;padding:12px;border:1px solid var(--border-default);border-radius:var(--radius-md);background:var(--bg-surface);min-width:0}
.voice-model-meta,.voice-model-note,.voice-model-empty{font-size:13px;line-height:1.7;color:var(--text-secondary);overflow-wrap:anywhere}
.voice-model-note,.voice-model-empty{margin:10px 0 0}
</style>
