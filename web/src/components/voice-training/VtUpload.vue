<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-body">
    <p v-if="state.error" class="vt-banner danger" role="alert"><i :class="icon('x-circle')" aria-hidden="true"></i><span>{{ state.error }}</span></p>

    <fieldset class="vt-group">
      <legend class="vt-section-title">1. {{ tx('upload.declareLegend') }}</legend>
      <p class="vt-hint">{{ tx('upload.declareHint') }}</p>
      <label v-for="item in DECLARATIONS" :key="item.key" class="vt-opt">
        <input type="radio" name="vt-decl" :value="item.key" :checked="state.up.declared === item.key" :disabled="state.up.locked" @change="store.selectDeclaration(item.key)">
        <span class="vt-opt-t">{{ tx('upload.decl.' + item.key + '.title') }} <VtUsageBadge :label="item.usage" /></span>
        <span class="vt-opt-d">{{ tx('upload.decl.' + item.key + '.desc') }}</span>
      </label>
      <p v-if="state.up.locked" class="vt-hint">{{ tx('upload.locked') }}</p>
    </fieldset>

    <label v-if="declaration && declaration.needsConsent" class="vt-check" for="vt-consent">
      <input id="vt-consent" v-model="state.up.consent" type="checkbox" :disabled="state.up.locked">
      <span>{{ tx('upload.decl.' + declaration.key + '.consent') }}</span>
    </label>
    <p v-else-if="declaration" class="vt-banner warn">
      <i :class="icon('alert')" aria-hidden="true"></i><span>{{ tx('upload.decl.' + declaration.key + '.consent') }}</span>
    </p>

    <div class="vt-section">
      <h3 class="vt-section-title">2. {{ tx('upload.filesTitle') }}</h3>
      <div class="vt-drop">
        <div class="vt-row"><i :class="icon('upload')" aria-hidden="true"></i><strong>{{ tx('upload.pick') }}</strong></div>
        <p class="vt-hint">{{ tf('upload.accept', { mb: MAX_UPLOAD_MB }) }}</p>
        <label class="vt-btn" :class="{ disabled: !canPick }" for="vt-audio-files" :aria-disabled="canPick ? undefined : 'true'">
          <i :class="icon('upload')" aria-hidden="true"></i>{{ tx('upload.choose') }}
        </label>
        <input id="vt-audio-files" ref="fileInput" class="vt-sr" type="file" multiple :accept="UPLOAD_ACCEPT" :disabled="!canPick" @change="onFiles">
        <p v-if="!canPick" class="vt-hint" role="status">{{ tx('upload.pickFirst') }}</p>
      </div>
      <p v-if="state.up.uploading" class="vt-hint" role="status"><i :class="icon('spin')" aria-hidden="true"></i> {{ tx('upload.uploading') }}</p>
      <dl v-if="state.up.files.length" class="vt-kv">
        <div><dt>{{ tx('upload.accepted') }}</dt><dd>{{ accepted.length }}</dd></div>
        <div v-if="rejected.length"><dt>{{ tx('upload.rejected') }}</dt><dd>{{ rejected.length }}</dd></div>
      </dl>
      <div v-if="rejected.length" class="vt-banner danger" role="alert">
        <i :class="icon('x-circle')" aria-hidden="true"></i>
        <div><div class="vt-b-title">{{ tf('upload.rejectedTitle', { n: rejected.length }) }}</div>{{ tx('upload.rejectedBody') }}</div>
      </div>
      <ul v-if="rejected.length" class="vt-flist">
        <li v-for="(file, index) in rejected" :key="file.name + index" class="vt-frow rej">
          <span class="vt-fname"><i :class="icon('x-circle')" aria-hidden="true"></i> {{ file.name }}</span>
          <span class="vt-freason"><i :class="icon('info')" aria-hidden="true"></i>{{ rejectReason(file) }}</span>
        </li>
      </ul>
      <ul v-if="accepted.length" class="vt-flist">
        <li v-for="file in accepted.slice(0, 8)" :key="file.name" class="vt-frow">
          <span class="vt-fname"><i :class="icon('check-circle')" aria-hidden="true"></i> <span class="vt-mono">{{ file.name }}</span></span>
          <span v-if="file.duration" class="vt-hint">{{ tf('common.seconds', { n: Number(file.duration).toFixed(1) }) }}</span>
        </li>
        <li v-if="accepted.length > 8" class="vt-hint">{{ tf('upload.more', { n: accepted.length - 8 }) }}</li>
      </ul>
    </div>

    <div class="vt-foot">
      <button type="button" class="vt-btn" @click="store.go('source')">{{ tx('common.back') }}</button>
      <div class="vt-right">
        <VtActionButton
          primary
          :label="tf('common.nextTo', { step: tx('steps.transcripts') })"
          :enabled="!reasons.length"
          :reasons="reasons.map(code => tx('upload.reason.' + code))"
          reason-id="vt-why-upload"
          @activate="store.go('text')"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import VtActionButton from './VtActionButton.vue'
import VtUsageBadge from './VtUsageBadge.vue'
import { DECLARATIONS, MAX_UPLOAD_MB, UPLOAD_ACCEPT } from '../../voiceTraining/constants.js'
import { declarationFor } from '../../voiceTraining/flow.js'
import { icon } from '../../voiceTraining/icons.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ store: { type: Object, required: true } })
const { tx, tf } = useTrainingText()
const state = props.store.state
const fileInput = ref(null)
const declaration = computed(() => declarationFor(state.up.declared))
const canPick = computed(() => Boolean(declaration.value) && (!declaration.value.needsConsent || state.up.consent) && !state.up.uploading)
const accepted = computed(() => state.up.files.filter(file => file.status === 'accepted'))
const rejected = computed(() => state.up.files.filter(file => file.status === 'rejected'))
const reasons = computed(() => props.store.uploadReasons)

function rejectReason(file) {
  if (file.code === 'server') return file.reason
  if (file.code === 'size') return tf('upload.rejectSize', { mb: file.detail })
  if (file.code === 'duplicate') return tf('upload.rejectDuplicate', { name: file.detail })
  return tf('upload.rejectFormat', { ext: file.detail || '?' })
}

async function onFiles(event) {
  const files = [...(event.target.files || [])]
  await props.store.addUploadFiles(files)
  if (fileInput.value) fileInput.value.value = ''
}
</script>
