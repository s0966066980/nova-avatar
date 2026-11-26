<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="vt-root">
    <VtHome v-if="state.screen === 'home'" :store="store" :models="models" />

    <section v-else class="vt-card" aria-labelledby="vt-heading">
      <div class="vt-card-head">
        <div>
          <h2 id="vt-heading" tabindex="-1" class="vt-title"><i :class="icon('wave')" aria-hidden="true"></i> {{ screenTitle }}</h2>
          <p v-if="screenDesc" class="vt-subtitle">{{ screenDesc }}</p>
        </div>
        <div v-if="labelPreview" class="vt-lab-block">
          <span class="vt-hint">{{ state.screen === 'done' ? tx('usage.final') : tx('usage.estimated') }}</span>
          <VtUsageBadge :label="labelPreview" />
        </div>
      </div>

      <nav :aria-label="tx('steps.label')">
        <ol class="vt-steps">
          <li v-for="(step, index) in steps" :key="step.id" :class="{ done: index < stepIndex, cur: index === stepIndex }" :aria-current="index === stepIndex ? 'step' : undefined">
            <span class="vt-sn"><i v-if="index < stepIndex" :class="icon('check')" aria-hidden="true"></i><template v-else>{{ index + 1 }}</template></span>
            <span class="vt-sl">{{ tx('steps.' + step.labelKey) }}</span>
          </li>
        </ol>
      </nav>

      <VtSource v-if="state.screen === 'source'" :store="store" :active="active" />
      <VtEdgeConfirm v-else-if="state.screen === 'edge-confirm'" :store="store" :session-expired="sessionExpired" />
      <VtUpload v-else-if="state.screen === 'upload'" :store="store" />
      <VtText v-else-if="state.screen === 'text'" :store="store" />
      <template v-else-if="state.screen === 'review'">
        <VtEdgeTextReview v-if="state.path === 'edge'" :store="store" />
        <VtReview v-else :store="store" />
      </template>
      <VtPreflight v-else-if="state.screen === 'preflight'" :store="store" />
      <VtJob v-else-if="state.screen === 'job'" :store="store" />
      <VtDone v-else-if="state.screen === 'done'" :store="store" @open-profiles="emit('open-profiles')" />
    </section>

    <div class="vt-sr" role="status" aria-live="polite">{{ announcementText }}</div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import VtDone from './VtDone.vue'
import VtEdgeConfirm from './VtEdgeConfirm.vue'
import VtEdgeTextReview from './VtEdgeTextReview.vue'
import VtHome from './VtHome.vue'
import VtJob from './VtJob.vue'
import VtPreflight from './VtPreflight.vue'
import VtReview from './VtReview.vue'
import VtSource from './VtSource.vue'
import VtText from './VtText.vue'
import VtUpload from './VtUpload.vue'
import VtUsageBadge from './VtUsageBadge.vue'
import { adminSession } from '../../adminSession.js'
import { useRuntimeSettings } from '../../composables/useRuntimeSettings.js'
import { declarationFor, stepList, usageLabelFor } from '../../voiceTraining/flow.js'
import { SOURCE_EDGE } from '../../voiceTraining/constants.js'
import { icon } from '../../voiceTraining/icons.js'
import { createVoiceTrainingStore } from '../../voiceTraining/store.js'
import { useTrainingText } from '../../voiceTraining/useText.js'

const props = defineProps({ active: { type: Boolean, default: true } })
const emit = defineEmits(['open-profiles'])
const { tx, tf } = useTrainingText()
const { speech, loadSpeechSettings } = useRuntimeSettings()

// A finished job adds a voice model: reload the speech snapshot that lists them.
const store = createVoiceTrainingStore({
  onModelsChanged: () => { loadSpeechSettings().catch(() => {}) },
  sessionExpired: () => adminSession.status === 'anonymous'
})
const state = store.state
const sessionExpired = computed(() => adminSession.status === 'anonymous')
const models = computed(() => (Array.isArray(speech.tts.voice_models) ? speech.tts.voice_models : []))

const steps = computed(() => stepList(state.path))
const SCREEN_STEP = { source: 0, 'edge-confirm': 0, upload: 0, text: 1, review: 2, preflight: 3, job: 4, done: 5 }
const stepIndex = computed(() => SCREEN_STEP[state.screen] ?? -1)

const screenKey = computed(() => {
  if (state.screen === 'text') return state.path === 'edge' ? 'textEdge' : 'textUpload'
  if (state.screen === 'review') return state.path === 'edge' ? 'reviewEdge' : 'review'
  return state.screen
})
const screenTitle = computed(() => tx(`screens.${screenKey.value}.title`))
const screenDesc = computed(() => tx(`screens.${screenKey.value}.desc`))

// The label the finished model will carry, from what the administrator has chosen so far.
const labelPreview = computed(() => {
  if (state.screen === 'done' && state.job?.usage) return state.job.usage
  if (state.path === 'edge') return usageLabelFor(SOURCE_EDGE)
  const declaration = declarationFor(state.up.declared)
  return declaration ? usageLabelFor(declaration.source) : ''
})

const announcementText = computed(() => {
  const note = state.announcement
  if (!note) return ''
  if (note.code === 'stage') return tf('announce.stage', { stage: tx(`job.stages.${note.stage}`) })
  if (note.code === 'confirmed') return tf('announce.confirmed', { n: note.count })
  if (note.code === 'failed') return `${tx('announce.failed')} ${note.error || ''}`.trim()
  return tx(`announce.${note.code}`)
})

watch(() => state.focusToken, async () => {
  await nextTick()
  globalThis.document?.getElementById?.('vt-heading')?.focus?.()
})

let timer = null
let polling = false
async function tick() {
  if (polling || !props.active) return
  polling = true
  try {
    if (store.shouldPoll) {
      if (state.screen === 'job') await store.pollJob()
      else if (state.screen === 'home') await store.refreshHome()
    }
    if (store.transcriptionShouldPoll) await store.pollTranscription()
  } finally {
    polling = false
  }
}
onMounted(() => {
  store.refreshHome()
  timer = setInterval(tick, 2000)
})
onBeforeUnmount(() => clearInterval(timer))
watch(() => props.active, active => { if (active && state.screen === 'home') store.refreshHome() })
</script>

<style>
.vt-root { display: grid; gap: 16px; min-width: 0; --vt-pad: 22px; }
.vt-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.vt-root :focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.vt-mono { font-family: var(--font-mono); font-size: 0.92em; overflow-wrap: anywhere; }
.vt-spin { display: inline-block; animation: vt-spin 1s linear infinite; }
@keyframes vt-spin { to { transform: rotate(360deg); } }

.vt-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: var(--vt-pad); display: flex; flex-direction: column; gap: 16px; box-shadow: var(--shadow-1); min-width: 0; }
.vt-card-head { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px 14px; border-bottom: 1px solid var(--border); padding-bottom: 12px; }
.vt-card-head > :first-child { flex: 1 1 15rem; min-width: 0; }
.vt-title { margin: 0; font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.vt-title i { color: var(--brand); font-size: 17px; }
h2.vt-title:focus { outline: none; }
.vt-subtitle { margin: 3px 0 0; font-size: 12.5px; color: var(--text-3); line-height: 1.6; max-width: 70ch; }
.vt-lab-block { display: grid; gap: 4px; justify-items: end; min-width: 0; }
.vt-body, .vt-stack, .vt-group, .vt-section { display: grid; gap: 12px; min-width: 0; }
.vt-body { gap: 16px; }
.vt-section { border-top: 1px solid var(--border); padding-top: 14px; }
.vt-section-title { margin: 0; font-size: 13.5px; font-weight: 700; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.vt-section-title i { color: var(--brand); }
.vt-group { border: 0; padding: 0; margin: 0; }
.vt-hint, .vt-footnote { margin: 0; font-size: 12.5px; color: var(--text-3); line-height: 1.6; overflow-wrap: anywhere; }
.vt-row { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; min-width: 0; }
.vt-row.spread { justify-content: space-between; }
.vt-right { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.vt-fgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }

.vt-btn { min-height: 36px; padding: 7px 16px; border-radius: var(--radius-sm); border: 1px solid var(--border-strong); background: var(--bg-surface); color: var(--text); font: inherit; font-size: 13px; font-weight: 600; display: inline-flex; align-items: center; justify-content: center; gap: 6px; text-align: left; line-height: 1.35; cursor: pointer; transition: background-color var(--anim-fast), border-color var(--anim-fast); }
.vt-btn:hover { background: var(--bg-hover); }
.vt-btn.primary { background: var(--brand); border-color: var(--brand); color: var(--on-brand); font-weight: 700; }
.vt-btn.primary:hover { background: var(--brand-hover); border-color: var(--brand-hover); }
.vt-btn.danger { border-color: var(--danger-border); color: var(--danger); }
.vt-btn.danger-solid { background: var(--danger); border-color: var(--danger); color: var(--on-danger); }
.vt-btn.small { min-height: 32px; padding: 4px 10px; font-size: 12.5px; }
.vt-btn.icon { min-width: 36px; padding: 6px; }
.vt-btn[aria-disabled="true"], .vt-btn.disabled { opacity: 0.45; cursor: not-allowed; }
.vt-btn.primary[aria-disabled="true"]:hover { background: var(--brand); }
.vt-btn[aria-pressed="true"] { background: var(--brand-surface); border-color: var(--brand); color: var(--brand-ink); }
.vt-act { display: grid; gap: 6px; justify-items: start; min-width: 0; }
.vt-why { display: flex; gap: 6px; align-items: flex-start; font-size: 12.5px; color: var(--warn); line-height: 1.5; max-width: 38ch; }
.vt-why i { margin-top: 2px; }
.vt-why-line { display: block; overflow-wrap: anywhere; }
.vt-foot { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; border-top: 1px solid var(--border); padding-top: 16px; align-items: flex-start; }

.vt-field { display: grid; gap: 6px; min-width: 0; }
.vt-field > label, .vt-label { font-size: 13px; font-weight: 600; }
.vt-input, .vt-select, .vt-textarea { min-height: 36px; background: var(--bg-input); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); padding: 8px 12px; color: var(--text); font: inherit; font-size: 13px; width: 100%; box-sizing: border-box; }
.vt-textarea { resize: vertical; line-height: 1.6; }
.vt-input:focus, .vt-select:focus, .vt-textarea:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-surface); outline: none; }
.vt-root [aria-invalid="true"] { border-color: var(--danger); box-shadow: 0 0 0 3px var(--danger-surface); }
.vt-err { margin: 0; color: var(--danger); font-size: 12.5px; display: flex; gap: 6px; align-items: flex-start; }
.vt-opt-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.vt-opt { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 12px; align-items: start; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); cursor: pointer; min-width: 0; }
.vt-opt:hover { background: var(--bg-raised); }
.vt-opt:has(input:checked) { border-color: var(--brand); background: var(--brand-surface); }
.vt-opt:has(input:focus-visible) { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.vt-opt input { margin-top: 3px; width: 16px; height: 16px; accent-color: var(--brand); }
.vt-opt-t { font-weight: 600; display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; }
.vt-opt-d { grid-column: 2; font-size: 12.5px; color: var(--text-2); line-height: 1.6; overflow-wrap: anywhere; }
.vt-check { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; align-items: start; font-size: 13.5px; line-height: 1.6; padding: 12px 14px; border: 1px solid var(--border-strong); border-radius: var(--radius-md); background: var(--bg-raised); cursor: pointer; }
.vt-check input { margin-top: 4px; width: 18px; height: 18px; accent-color: var(--brand); }

.vt-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px 3px 8px; border-radius: 999px; border: 1px solid var(--border); background: var(--bg-raised); color: var(--text-2); font-size: 12px; font-weight: 600; line-height: 1.4; }
.vt-chip.ok { color: var(--ok); border-color: var(--ok-border); background: var(--ok-surface); }
.vt-chip.danger { color: var(--danger); border-color: var(--danger-border); background: var(--danger-surface); }
.vt-chip.plain { padding-left: 10px; }
.vt-tag { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--warn-border); color: var(--warn); font-size: 12px; font-weight: 700; line-height: 1.4; overflow-wrap: anywhere; }
.vt-tag.dev { background: var(--warn-surface); border-color: var(--warn-bar); }
.vt-tag.res { background: var(--bg-raised); }
.vt-banner { display: flex; align-items: flex-start; gap: 12px; padding: 12px 16px; margin: 0; border: 1px solid var(--border); border-left-width: 4px; border-left-color: var(--brand); border-radius: var(--radius-md); background: var(--brand-surface); font-size: 13px; line-height: 1.6; min-width: 0; }
.vt-banner > i { font-size: 18px; color: var(--brand-ink); margin-top: 2px; }
.vt-banner > div, .vt-banner > span { min-width: 0; flex: 1; overflow-wrap: anywhere; }
.vt-banner.warn { border-color: var(--warn-border); border-left-color: var(--warn-bar); background: var(--warn-surface); }
.vt-banner.warn > i { color: var(--warn); }
.vt-banner.danger { border-color: var(--danger-border); border-left-color: var(--danger); background: var(--danger-surface); }
.vt-banner.danger > i { color: var(--danger); }
.vt-banner.ok { border-color: var(--ok-border); border-left-color: var(--ok); background: var(--ok-surface); }
.vt-banner.ok > i { color: var(--ok); }
.vt-b-title { font-weight: 700; margin-bottom: 2px; }
.vt-b-actions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }
.vt-problems { margin: 6px 0; padding-left: 18px; }
.vt-note { margin: 0; font-size: 12.5px; color: var(--warn); display: flex; gap: 6px; align-items: flex-start; line-height: 1.5; }
.vt-note.bad { color: var(--danger); }

.vt-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 4px; }
.vt-steps li { display: flex; align-items: center; gap: 8px; padding: 4px 12px 4px 4px; border-radius: 999px; color: var(--text-3); font-size: 12.5px; font-weight: 600; min-width: 0; }
.vt-sn { width: 24px; height: 24px; border-radius: 50%; border: 1.5px solid var(--border-strong); display: grid; place-items: center; font-size: 12px; flex: none; font-variant-numeric: tabular-nums; }
.vt-steps li.done { color: var(--text-2); }
.vt-steps li.done .vt-sn { background: var(--ok-surface); border-color: var(--ok-border); color: var(--ok); }
.vt-steps li.cur { background: var(--brand-surface); color: var(--brand-ink); }
.vt-steps li.cur .vt-sn { background: var(--brand); border-color: var(--brand); color: var(--on-brand); }

.vt-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px 14px; align-items: center; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-raised); list-style: none; }
.vt-stack { padding: 0; margin: 0; list-style: none; }
.vt-item-main { display: grid; gap: 4px; min-width: 0; }
.vt-item-main strong { overflow-wrap: anywhere; }
.vt-meta { font-size: 12.5px; color: var(--text-3); display: flex; flex-wrap: wrap; gap: 4px 12px; }
.vt-item-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.vt-empty { border: 1px dashed var(--border-strong); border-radius: var(--radius-md); padding: 22px 18px; display: grid; gap: 10px; justify-items: start; background: var(--bg-raised); }
.vt-empty h4 { margin: 0; font-size: 14px; }
.vt-msa { margin: 0; border: 1px solid var(--warn-border); border-left: 4px solid var(--warn-bar); border-radius: var(--radius-md); background: var(--bg-raised); padding: 14px 16px; display: grid; gap: 8px; }
.vt-msa-src { font-size: 12px; color: var(--text-3); font-weight: 600; letter-spacing: 0.03em; }
.vt-msa blockquote { margin: 0; font-size: 15px; line-height: 1.7; font-weight: 600; overflow-wrap: anywhere; }
.vt-rules { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; font-size: 13px; line-height: 1.6; }
.vt-rules li { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px; }
.vt-rules i { color: var(--warn); margin-top: 3px; }

.vt-drop { border: 1.5px dashed var(--border-strong); border-radius: var(--radius-md); padding: 22px 16px; display: grid; gap: 8px; justify-items: start; background: var(--bg-raised); }
.vt-flist { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; font-size: 13px; }
.vt-frow { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); align-items: center; background: var(--bg-surface); }
.vt-frow.rej { border-color: var(--danger-border); background: var(--danger-surface); }
.vt-fname { overflow-wrap: anywhere; }
.vt-freason { grid-column: 1 / -1; color: var(--danger); font-size: 12.5px; display: flex; gap: 6px; }
.vt-kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 0; }
.vt-kv > div { padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-raised); min-width: 0; }
.vt-kv dt { font-size: 12px; color: var(--text-3); }
.vt-kv dd { margin: 2px 0 0; font-weight: 600; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }

.vt-sumbar, .vt-filters { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; }
.vt-rt { display: grid; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.vt-rt-head, .vt-rt-row { display: grid; grid-template-columns: 34px 52px minmax(0, 1fr) 118px minmax(150px, auto); gap: 12px; padding: 10px 14px; align-items: start; }
.vt-rt-head { background: var(--bg-sunken); font-size: 12px; font-weight: 700; color: var(--text-3); }
.vt-rt-row { border-top: 1px solid var(--border); background: var(--bg-surface); }
.vt-rt-row.is-excluded { background: var(--bg-sunken); color: var(--text-3); }
.vt-rt-row.is-excluded .vt-txt { text-decoration: line-through; }
.vt-rt-row.is-unresolved { background: var(--danger-surface); }
.vt-rt-row.is-edit { background: var(--brand-surface); }
.vt-c-n { color: var(--text-3); font-variant-numeric: tabular-nums; padding-top: 6px; }
.vt-c-t { display: grid; gap: 6px; min-width: 0; }
.vt-c-a { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; margin-left: 0; }
.vt-fid { font-size: 11.5px; color: var(--text-3); }
.vt-txt { font-size: 14px; line-height: 1.7; overflow-wrap: anywhere; }
.vt-exp { font-size: 12.5px; line-height: 1.7; color: var(--text-2); border-left: 3px solid var(--border-strong); padding-left: 10px; overflow-wrap: anywhere; }
.vt-ex { background: var(--brand-surface); color: var(--brand-ink); border-radius: 3px; padding: 0 2px; text-decoration: underline; text-decoration-style: dotted; }
.vt-bad { background: var(--danger-surface); color: var(--danger); border-radius: 3px; padding: 0 2px; font-weight: 700; text-decoration: underline wavy; }
.vt-pager { display: flex; gap: 10px; align-items: center; justify-content: space-between; flex-wrap: wrap; }

.vt-checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.vt-ck { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 12px; align-items: start; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); }
.vt-ck.bad { border-color: var(--danger-border); background: var(--danger-surface); }
.vt-ck.warn { border-color: var(--warn-border); background: var(--warn-surface); }
.vt-ck > i { font-size: 18px; margin-top: 2px; }
.vt-ck.ok > i, .vt-ck.ok .vt-ck-st { color: var(--ok); }
.vt-ck.bad > i, .vt-ck.bad .vt-ck-st { color: var(--danger); }
.vt-ck.warn > i, .vt-ck.warn .vt-ck-st { color: var(--warn); }
.vt-ck-k { font-weight: 600; }
.vt-ck-v { font-size: 12.5px; color: var(--text-2); line-height: 1.6; overflow-wrap: anywhere; }
.vt-ck-st { font-size: 12px; font-weight: 700; }
.vt-gauge { position: relative; height: 10px; border-radius: 999px; background: var(--bg-sunken); border: 1px solid var(--border); margin-top: 8px; }
.vt-gauge i { position: absolute; inset: 0 auto 0 0; border-radius: 999px; background: var(--ok); }
.vt-gauge.low i { background: var(--danger); }
.vt-gauge b { position: absolute; top: -4px; bottom: -4px; width: 2px; background: var(--text); }
.vt-gauge-l { display: flex; justify-content: space-between; gap: 8px; font-size: 11.5px; color: var(--text-3); margin-top: 4px; flex-wrap: wrap; }
.vt-label-box { border: 1px solid var(--warn-border); background: var(--warn-surface); border-radius: var(--radius-md); padding: 14px 16px; display: grid; gap: 8px; }
.vt-label-box ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; font-size: 12.5px; color: var(--text-2); line-height: 1.6; }
.vt-big { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 16px; font-weight: 700; }

.vt-bar { height: 12px; border-radius: 999px; background: var(--bg-sunken); border: 1px solid var(--border); overflow: hidden; }
.vt-bar i { display: block; height: 100%; background: var(--brand); transition: width 400ms linear; }
.vt-bar.ok i { background: var(--ok); }
.vt-bar.bad i { background: var(--danger); }
.vt-stages { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.vt-stage { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 12px; align-items: start; padding: 10px 14px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-surface); }
.vt-stage > i { margin-top: 2px; color: var(--text-3); }
.vt-stage.run { border-color: var(--brand); background: var(--brand-surface); }
.vt-stage.run > i { color: var(--brand); }
.vt-stage.ok > i { color: var(--ok); }
.vt-stage.bad { border-color: var(--danger-border); background: var(--danger-surface); }
.vt-stage.bad > i { color: var(--danger); }
.vt-stage-name { font-weight: 600; }
.vt-stage-st { font-size: 12px; font-weight: 700; color: var(--text-3); }
.vt-stage-dt { grid-column: 2; font-size: 12.5px; color: var(--text-2); line-height: 1.6; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.vt-log { background: var(--bg-sunken); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; max-height: 260px; overflow: auto; font-family: var(--font-mono); font-size: 12px; line-height: 1.7; }
.vt-log div { overflow-wrap: anywhere; }
.vt-log .warn { color: var(--warn); }
.vt-log .error { color: var(--danger); }
.vt-confirm-cancel { border: 1px solid var(--danger-border); background: var(--danger-surface); border-radius: var(--radius-md); padding: 14px 16px; display: grid; gap: 10px; }
.vt-player { display: grid; gap: 10px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px 16px; background: var(--bg-raised); }
.vt-player audio { width: 100%; }
.vt-device p { margin: 0 0 4px; }

/* 16:9 one-screen layout of the settings page: the card scrolls inside its cell, not the page. */
@media (min-width: 1280px) and (min-height: 640px) {
  .vt-root { grid-template-rows: minmax(0, 1fr); }
  .vt-card { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
}

@media (max-width: 760px) {
  .vt-root { --vt-pad: 16px; }
  .vt-lab-block { justify-items: start; }
  .vt-btn, .vt-btn.small { min-height: 44px; }
  .vt-btn.icon { min-width: 44px; }
  .vt-input, .vt-select, .vt-textarea { min-height: 44px; font-size: 16px; }
  .vt-steps li:not(.cur) .vt-sl { display: none; }
  .vt-steps li:not(.cur) { padding-right: 4px; }
  .vt-rt-head { display: none; }
  .vt-rt-row { grid-template-columns: auto minmax(0, 1fr) auto; grid-template-areas: "n p s" "t t t" "a a a"; gap: 8px 10px; }
  .vt-c-n { grid-area: n; align-self: center; padding: 0; }
  .vt-c-p { grid-area: p; }
  .vt-c-s { grid-area: s; justify-self: end; }
  .vt-c-t { grid-area: t; }
  .vt-c-a { grid-area: a; justify-content: flex-start; }
  .vt-ck { grid-template-columns: auto minmax(0, 1fr); }
  .vt-ck-st { grid-column: 2; }
  .vt-item { grid-template-columns: minmax(0, 1fr); }
  .vt-item-actions { justify-content: flex-start; }
  .vt-right { margin-left: 0; justify-content: flex-start; }
  .vt-stage { grid-template-columns: auto minmax(0, 1fr); }
  .vt-stage-st { grid-column: 2; }
}
@media (prefers-reduced-motion: reduce) {
  .vt-root *, .vt-root *::before { transition: none !important; animation: none !important; }
}
</style>
