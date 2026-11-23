<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->
<template>
  <section class="setting-card full-span tts-training-card" aria-labelledby="ttsTrainingTitle">
    <div class="card-title-row">
      <div>
        <div class="training-eyebrow">MATCHA-TTS VOICE DISTILLATION WORKBENCH</div>
        <div id="ttsTrainingTitle" class="card-title-text">
          <i class="bi bi-soundwave" aria-hidden="true"></i> {{ t('settings.ttsTraining.title') }}
        </div>
        <div class="card-subtitle-desc">{{ t('settings.ttsTraining.desc') }}</div>
      </div>
      <div class="training-header-actions">
        <button
          type="button"
          class="btn-restore-gray"
          style="padding: 6px 14px; font-size: 12px;"
          :disabled="loadingStatus"
          @click="refreshStatus"
        >
          <i class="bi bi-arrow-clockwise" aria-hidden="true"></i> {{ t('settings.ttsTraining.refresh') }}
        </button>
        <button
          v-if="isRunning"
          type="button"
          class="btn-restore-gray danger-outline"
          style="padding: 6px 14px; font-size: 12px;"
          @click="cancelJob"
        >
          <i class="bi bi-stop-circle" aria-hidden="true"></i> {{ t('settings.ttsTraining.cancel') }}
        </button>
        <button
          v-else
          type="button"
          class="btn-apply-primary"
          style="padding: 6px 16px; font-size: 12px;"
          :disabled="!canRunTrain || submitting"
          @click="runStep('full')"
        >
          <i class="bi bi-play-fill" aria-hidden="true"></i> {{ t('settings.ttsTraining.runFull') }}
        </button>
      </div>
    </div>

    <!-- Pipeline Summary Strip -->
    <div class="training-pipeline-strip" role="list" :aria-label="t('settings.ttsTraining.pipelineLabel')">
      <div
        v-for="(item, idx) in stepOverview"
        :key="item.id"
        class="pipeline-pill"
        :class="[`state-${stepVisualState(item.id)}`]"
        role="listitem"
      >
        <span class="pill-index">{{ idx + 1 }}</span>
        <span class="pill-text">{{ item.label }}</span>
      </div>
    </div>

    <!-- Prerequisites & GPU warning -->
    <div class="prereq-row">
      <span class="prereq-badge" :class="prereq.cosy_venv_ready ? 'ok' : 'missing'">
        <i class="bi" :class="prereq.cosy_venv_ready ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'"></i>
        CUDA / ONNX 環境 ({{ prereq.cosy_venv_path }})
      </span>
      <span class="prereq-badge" :class="prereq.base_ckpt_ready ? 'ok' : 'missing'">
        <i class="bi" :class="prereq.base_ckpt_ready ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill'"></i>
        Matcha 基礎權重 ({{ prereq.base_ckpt_path }})
      </span>
      <span class="prereq-badge" :class="prereq.cosyvoice_model_ready ? 'ok' : 'warn'">
        <i class="bi" :class="prereq.cosyvoice_model_ready ? 'bi-check-circle-fill' : 'bi-info-circle'"></i>
        CosyVoice3 本機模型
      </span>
    </div>

    <div v-if="isConnected || sessionCount > 0" class="training-alert warning" role="alert">
      <div class="alert-lead">
        <i class="bi bi-gpu-card" aria-hidden="true"></i>
        <span>{{ t('settings.ttsTraining.disconnectHint') }}</span>
      </div>
      <button type="button" class="btn-restore-gray" style="padding: 5px 12px; font-size: 12px;" @click="$emit('request-disconnect')">
        {{ t('settings.ttsTraining.disconnectNow') }}
      </button>
    </div>

    <div v-if="statusError" class="training-alert error" role="alert">{{ statusError }}</div>

    <!-- Workspace & Model Identity -->
    <div class="setting-form-row">
      <div class="field-label-group">
        <label for="tts-train-slug" class="field-main-label">{{ t('settings.ttsTraining.slugLabel') }}</label>
        <span class="field-sub-hint">
          輸出至 <code>models/tts/{{ config.slug || 'zh-tw-custom' }}</code> ·
          語料 {{ workspace.corpus_lines || 0 }} 句 · QA {{ workspace.manifest_lines || 0 }} 句 ·
          {{ workspace.ckpt_ready ? `權重 ${workspace.ckpt_file}` : '尚無 checkpoint' }} ·
          {{ workspace.export_ready ? 'ONNX 已匯出' : '尚未匯出' }}
        </span>
      </div>
      <div class="field-control-area">
        <input
          id="tts-train-slug"
          v-model.trim="config.slug"
          type="text"
          class="std-input"
          placeholder="zh-tw-custom"
          :disabled="isRunning"
          @change="refreshStatus"
        >
      </div>
    </div>

    <div class="steps-stack">
      <!-- Step 1: Corpus -->
      <details class="training-step-card" open>
        <summary class="step-summary">
          <span><strong>步驟 1：</strong>{{ t('settings.ttsTraining.step1Title') }}</span>
          <span class="step-chip" :class="workspace.corpus_ready ? 'ready' : ''">
            {{ workspace.corpus_ready ? `${workspace.corpus_lines} 句 (~${workspace.corpus_hours}h)` : '未建立' }}
          </span>
        </summary>
        <div class="step-body">
          <p class="step-explain">{{ t('settings.ttsTraining.step1Explain') }}</p>
          <div class="step-grid">
            <label class="step-field">
              <span>目標語料時數 (hours)</span>
              <input v-model.number="config.corpus_hours" type="number" min="0.02" max="10" step="0.05" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-field">
              <span>隨機種子 (seed)</span>
              <input v-model.number="config.corpus_seed" type="number" min="0" step="1" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-checkbox">
              <input v-model="config.preserve_existing" type="checkbox" :disabled="isRunning">
              <span>保留現有 corpus.jsonl 並追加 (--preserve-existing)</span>
            </label>
          </div>
          <label class="step-field full-width">
            <span>自訂領域句子（選填，每行一句，會一併寫入語料庫）</span>
            <textarea
              v-model="config.extra_sentences"
              rows="2"
              class="std-textarea"
              placeholder="例如：歡迎來到智慧展廳，今天為您導覽全館特色展區。"
              :disabled="isRunning"
            ></textarea>
          </label>
          <div class="step-actions">
            <button type="button" class="btn-restore-gray" :disabled="isRunning || submitting" @click="runStep('corpus')">
              執行步驟 1：建立語料
            </button>
          </div>
        </div>
      </details>

      <!-- Step 2: Teacher synthesis & Whisper QA -->
      <details class="training-step-card" open>
        <summary class="step-summary">
          <span><strong>步驟 2：</strong>{{ t('settings.ttsTraining.step2Title') }}</span>
          <span class="step-chip" :class="workspace.manifest_ready ? 'ready' : ''">
            {{ workspace.manifest_ready ? `已通過 QA ${workspace.manifest_lines} 句 (~${workspace.manifest_hours}h)` : '未完成 QA' }}
          </span>
        </summary>
        <div class="step-body">
          <p class="step-explain">{{ t('settings.ttsTraining.step2Explain') }}</p>
          <div class="step-grid">
            <label class="step-field">
              <span>教師聲線來源</span>
              <select v-model="config.teacher" class="std-select" :disabled="isRunning">
                <option value="edgetts">Edge-TTS 蒸餾（Research / Non-commercial）</option>
                <option value="cosyvoice">CosyVoice3 本機聲音複製（需要本機模型與參考音檔）</option>
              </select>
            </label>

            <template v-if="config.teacher === 'edgetts'">
              <label class="step-field">
                <span>Edge-TTS 教師聲線</span>
                <div class="voice-preview-combo">
                  <select
                    v-if="!customEdgeVoiceMode"
                    id="tts-train-edge-voice"
                    v-model="config.edge_voice"
                    class="std-select"
                    :disabled="isRunning"
                  >
                    <option v-for="v in edgeVoices" :key="v.id" :value="v.id">
                      {{ v.label || v.id }}
                    </option>
                  </select>
                  <input
                    v-else
                    id="tts-train-edge-voice"
                    v-model.trim="config.edge_voice"
                    list="tts-train-edge-voices"
                    class="std-input"
                    placeholder="例如 zh-TW-HsiaoChenNeural"
                    :disabled="isRunning"
                  >
                  <datalist id="tts-train-edge-voices">
                    <option v-for="v in edgeVoices" :key="v.id" :value="v.id">{{ v.label }}</option>
                  </datalist>
                  <button
                    type="button"
                    class="btn-restore-gray preview-voice-btn"
                    :disabled="previewingVoice || !config.edge_voice"
                    @click="previewEdgeVoice"
                  >
                    <i
                      class="bi"
                      :class="previewingVoice ? 'bi-hourglass-split spin' : (isPlayingPreview ? 'bi-stop-fill' : 'bi-volume-up-fill')"
                      aria-hidden="true"
                    ></i>
                    {{ previewingVoice ? t('settings.ttsTraining.previewLoading') : t('settings.ttsTraining.previewVoice') }}
                  </button>
                  <button
                    type="button"
                    class="btn-restore-gray mode-toggle-btn"
                    :disabled="isRunning"
                    :title="customEdgeVoiceMode ? '切回常用清單' : '自訂其他 Edge-TTS 聲線名稱'"
                    @click="toggleCustomEdgeVoice"
                  >
                    {{ customEdgeVoiceMode ? '清單' : '自訂' }}
                  </button>
                </div>
              </label>

              <label class="step-field">
                <span>試聽短句（選填，留空使用預設問候句）</span>
                <input
                  v-model.trim="previewSampleText"
                  type="text"
                  maxlength="120"
                  class="std-input"
                  :placeholder="t('settings.ttsTraining.previewTextPlaceholder')"
                  :disabled="previewingVoice"
                >
              </label>
            </template>
            <template v-else>
              <label class="step-field">
                <span>參考音檔 Preset（data/tts/prompts）</span>
                <select v-model="selectedPromptId" class="std-select" :disabled="isRunning" @change="applyPromptPreset">
                  <option value="">自訂路徑</option>
                  <option v-for="p in prompts" :key="p.id" :value="p.id">{{ p.id }}</option>
                </select>
              </label>
              <label class="step-field">
                <span>Prompt WAV（專案內路徑）</span>
                <input v-model.trim="config.prompt_wav" type="text" class="std-input" :disabled="isRunning">
              </label>
              <label class="step-field">
                <span>Prompt TXT（逐字稿路徑）</span>
                <input v-model.trim="config.prompt_txt" type="text" class="std-input" :disabled="isRunning">
              </label>
            </template>

            <label class="step-field">
              <span>Whisper QA 相似度門檻</span>
              <input v-model.number="config.min_asr_sim" type="number" min="0" max="1" step="0.05" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-field">
              <span>Whisper QA 運算裝置</span>
              <select v-model="config.asr_device" class="std-select" :disabled="isRunning">
                <option value="cuda">CUDA（快速）</option>
                <option value="cpu">CPU（省顯存）</option>
              </select>
            </label>
            <label class="step-field">
              <span>合成句數上限（0 = 全部）</span>
              <input v-model.number="config.distill_limit" type="number" min="0" step="10" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-checkbox">
              <input v-model="config.resume_distill" type="checkbox" :disabled="isRunning">
              <span>斷點續跑 (--resume)</span>
            </label>
            <label class="step-checkbox">
              <input v-model="config.skip_asr" type="checkbox" :disabled="isRunning">
              <span>跳過 Whisper QA (--skip-asr，僅測試用)</span>
            </label>
          </div>

          <div v-if="config.teacher === 'edgetts' && (previewAudioUrl || previewError)" class="preview-player-box">
            <p v-if="previewError" class="training-alert error" role="alert">{{ previewError }}</p>
            <div v-if="previewAudioUrl" class="preview-player-row">
              <span class="preview-voice-tag">
                <i class="bi bi-music-note-beamed" aria-hidden="true"></i>
                {{ lastPreviewVoice }}
              </span>
              <audio
                ref="previewAudioRef"
                :src="previewAudioUrl"
                controls
                class="preview-audio-ctrl"
                @play="isPlayingPreview = true"
                @pause="isPlayingPreview = false"
                @ended="isPlayingPreview = false"
              ></audio>
            </div>
          </div>

          <div v-if="config.teacher === 'edgetts'" class="training-alert noncommercial" role="note">
            <div class="alert-lead">
              <i class="bi bi-shield-exclamation" aria-hidden="true"></i>
              <span>
                <strong>授權分類：Research / Non-commercial</strong> — 使用 Edge-TTS 合成音訊訓練之模型僅限研究／非商業用途，匯出時系統會自動寫入 <code>NOTICE-NON-COMMERCIAL.txt</code>。
              </span>
            </div>
          </div>

          <div class="step-actions">
            <button
              type="button"
              class="btn-restore-gray"
              :disabled="isRunning || submitting || !workspace.corpus_ready || (config.teacher === 'cosyvoice' && !prereq.cosyvoice_model_ready)"
              @click="runStep('distill')"
            >
              執行步驟 2：教師合成 + Whisper QA
            </button>
          </div>
        </div>
      </details>

      <!-- Step 3: Matcha CUDA fine-tuning -->
      <details class="training-step-card">
        <summary class="step-summary">
          <span><strong>步驟 3：</strong>{{ t('settings.ttsTraining.step3Title') }}</span>
          <span class="step-chip" :class="workspace.ckpt_ready ? 'ready' : ''">
            {{ workspace.ckpt_ready ? `已產出 ${workspace.ckpt_file}` : '未訓練' }}
          </span>
        </summary>
        <div class="step-body">
          <p class="step-explain">{{ t('settings.ttsTraining.step3Explain') }}</p>
          <div class="step-grid">
            <label class="step-field">
              <span>訓練 Epochs</span>
              <input v-model.number="config.epochs" type="number" min="1" max="200" step="1" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-field">
              <span>Batch Size</span>
              <input v-model.number="config.batch_size" type="number" min="1" max="64" step="1" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-field">
              <span>Decoder 學習率 (lr)</span>
              <input v-model.number="config.lr" type="number" min="0.000001" max="0.01" step="0.00001" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-field">
              <span>Encoder LR 倍率</span>
              <input v-model.number="config.encoder_lr_scale" type="number" min="0" max="1" step="0.05" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-field">
              <span>句末補靜音 (ms)</span>
              <input v-model.number="config.pad_silence_ms" type="number" min="0" max="500" step="10" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-field">
              <span>Encoder Anchor 正則</span>
              <input v-model.number="config.encoder_anchor" type="number" min="0" max="1" step="0.01" class="std-input" :disabled="isRunning">
            </label>
            <label class="step-checkbox">
              <input v-model="config.freeze_emb" type="checkbox" :disabled="isRunning">
              <span>凍結音素 Embedding (--freeze-emb)</span>
            </label>
            <label class="step-checkbox">
              <input v-model="config.full_seq" type="checkbox" :disabled="isRunning">
              <span>完整句長流匹配訓練 (--full-seq)</span>
            </label>
          </div>
          <div class="step-actions">
            <button
              type="button"
              class="btn-restore-gray"
              :disabled="isRunning || submitting || !canRunTrain || !workspace.manifest_ready"
              @click="runStep('train')"
            >
              執行步驟 3：開始 GPU 微調
            </button>
          </div>
        </div>
      </details>

      <!-- Step 4: ONNX Export -->
      <details class="training-step-card">
        <summary class="step-summary">
          <span><strong>步驟 4：</strong>{{ t('settings.ttsTraining.step4Title') }}</span>
          <span class="step-chip" :class="workspace.export_ready ? 'ready' : ''">
            {{ workspace.export_ready ? 'ONNX 可用' : '未匯出' }}
          </span>
        </summary>
        <div class="step-body">
          <p class="step-explain">{{ t('settings.ttsTraining.step4Explain') }}</p>
          <div class="step-grid">
            <label class="step-field">
              <span>Flow Matching ODE 步數</span>
              <input v-model.number="config.num_ode_steps" type="number" min="2" max="16" step="1" class="std-input" :disabled="isRunning">
            </label>
          </div>
          <div class="step-actions">
            <button
              type="button"
              class="btn-restore-gray"
              :disabled="isRunning || submitting || !canRunTrain || !workspace.ckpt_ready"
              @click="runStep('export')"
            >
              執行步驟 4：匯出 ONNX 並產出授權標註
            </button>
          </div>
        </div>
      </details>
    </div>

    <!-- Live Job Progress & Logs -->
    <div v-if="job" class="job-status-box" role="status" aria-live="polite">
      <div class="job-status-top">
        <div>
          <strong>{{ job.message }}</strong>
          <span class="job-meta"> · {{ job.slug }} · {{ job.progress }}%</span>
        </div>
        <span v-if="job.non_commercial" class="license-pill noncommercial">Research / Non-commercial</span>
        <span v-else class="license-pill">{{ job.license_tag }}</span>
      </div>
      <div class="progress-track" role="progressbar" :aria-valuenow="job.progress" aria-valuemin="0" aria-valuemax="100">
        <div class="progress-fill" :class="job.status" :style="{ width: `${job.progress}%` }"></div>
      </div>
      <p v-if="job.error" class="training-alert error" role="alert">{{ job.error }}</p>
      <pre v-if="job.logs && job.logs.length" ref="logBoxRef" class="job-log-tail">{{ job.logs.join('\n') }}</pre>
    </div>

    <!-- Trained Models Ready to Apply -->
    <div v-if="trainedModels.length" class="trained-models-box">
      <h4 class="trained-models-title">{{ t('settings.ttsTraining.trainedModelsTitle') }}</h4>
      <div v-for="m in trainedModels" :key="m.path" class="trained-model-row">
        <div class="trained-model-info">
          <code>{{ m.path }}</code>
          <span v-if="m.non_commercial" class="license-pill noncommercial">Research / Non-commercial</span>
          <span v-else class="license-pill">{{ m.license_tag }}</span>
          <small v-if="m.voice">{{ m.teacher }} · {{ m.voice }}</small>
        </div>
        <button
          type="button"
          class="btn-restore-gray"
          style="padding: 5px 12px; font-size: 12px;"
          @click="$emit('apply-model', m.path)"
        >
          帶入上方 Matcha 設定
        </button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from '../composables/useI18n'

const props = defineProps({
  active: { type: Boolean, default: false },
  isConnected: { type: Boolean, default: false }
})

const emit = defineEmits(['request-disconnect', 'apply-model', 'notification'])
const { t } = useI18n()

const config = reactive({
  slug: 'zh-tw-custom',
  teacher: 'edgetts',
  corpus_hours: 0.25,
  corpus_seed: 42,
  preserve_existing: true,
  extra_sentences: '',
  edge_voice: 'zh-TW-HsiaoChenNeural',
  prompt_wav: 'data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.wav',
  prompt_txt: 'data/tts/prompts/zh-TW-YunJheNeural.cosy24k.v2.txt',
  whisper_model: 'small',
  asr_device: 'cuda',
  min_asr_sim: 0.65,
  delay_seconds: 0.15,
  distill_limit: 0,
  resume_distill: true,
  skip_asr: false,
  epochs: 20,
  batch_size: 6,
  lr: 0.00003,
  encoder_lr_scale: 0.25,
  proj_lr_scale: 0.35,
  freeze_emb: true,
  freeze_encoder_body: false,
  full_seq: true,
  pad_silence_ms: 120,
  encoder_anchor: 0.05,
  dur_bounds_weight: 1.0,
  num_ode_steps: 4
})

const prereq = reactive({
  cosy_venv_ready: false,
  cosy_venv_path: '.local/cosyvoice3/venv/bin/python',
  base_ckpt_ready: false,
  base_ckpt_path: '.local/matcha-base/pytorch_model_sherpa.bin',
  cosyvoice_model_ready: false,
  matcha_src_ready: false
})
const workspace = reactive({
  slug: 'zh-tw-custom',
  corpus_ready: false,
  corpus_lines: 0,
  corpus_hours: 0,
  manifest_ready: false,
  manifest_lines: 0,
  manifest_hours: 0,
  ckpt_ready: false,
  ckpt_file: '',
  export_ready: false
})
const edgeVoices = ref([
  { id: 'zh-TW-HsiaoChenNeural', label: 'zh-TW 曉臻（女聲，預設）', lang: 'zh-TW' },
  { id: 'zh-TW-YunJheNeural', label: 'zh-TW 雲哲（男聲）', lang: 'zh-TW' },
  { id: 'zh-TW-HsiaoYuNeural', label: 'zh-TW 曉雨（女聲）', lang: 'zh-TW' },
  { id: 'en-US-JennyNeural', label: 'en-US Jenny（美式女聲）', lang: 'en-US' },
  { id: 'en-US-AriaNeural', label: 'en-US Aria（美式女聲）', lang: 'en-US' },
  { id: 'en-US-GuyNeural', label: 'en-US Guy（美式男聲）', lang: 'en-US' }
])
const prompts = ref([])
const trainedModels = ref([])
const selectedPromptId = ref('zh-TW-YunJheNeural.cosy24k.v2')
const sessionCount = ref(0)
const job = ref(null)
const loadingStatus = ref(false)
const submitting = ref(false)
const statusError = ref('')
const logBoxRef = ref(null)

// Edge-TTS teacher audition state
const customEdgeVoiceMode = ref(false)
const previewSampleText = ref('')
const previewingVoice = ref(false)
const previewAudioUrl = ref('')
const previewError = ref('')
const lastPreviewVoice = ref('')
const isPlayingPreview = ref(false)
const previewAudioRef = ref(null)

let pollTimer = null
let lastFinishedJobId = ''

const stepOverview = [
  { id: 'corpus', label: '1. 建立語料' },
  { id: 'distill', label: '2. 教師合成 + QA' },
  { id: 'train', label: '3. Matcha CUDA 微調' },
  { id: 'export', label: '4. ONNX 匯出' }
]

const isRunning = computed(() => Boolean(job.value && ['queued', 'running'].includes(job.value.status)))
const canRunTrain = computed(() => Boolean(prereq.cosy_venv_ready && prereq.base_ckpt_ready))

function stepVisualState(stepId) {
  if (job.value && job.value.slug === config.slug && job.value.step_states?.[stepId]) {
    const s = job.value.step_states[stepId]
    if (s !== 'pending' && s !== 'skipped') return s
  }
  if (stepId === 'corpus' && workspace.corpus_ready) return 'done'
  if (stepId === 'distill' && workspace.manifest_ready) return 'done'
  if (stepId === 'train' && workspace.ckpt_ready) return 'done'
  if (stepId === 'export' && workspace.export_ready) return 'done'
  return 'pending'
}

function applyPromptPreset() {
  const matched = prompts.value.find((item) => item.id === selectedPromptId.value)
  if (!matched) return
  config.prompt_wav = matched.wav
  config.prompt_txt = matched.txt
}

function toggleCustomEdgeVoice() {
  customEdgeVoiceMode.value = !customEdgeVoiceMode.value
  if (!customEdgeVoiceMode.value && edgeVoices.value.length) {
    const exists = edgeVoices.value.some((v) => v.id === config.edge_voice)
    if (!exists) {
      config.edge_voice = edgeVoices.value[0].id
    }
  }
}

function stopPreviewAudio() {
  if (previewAudioRef.value) {
    try {
      previewAudioRef.value.pause()
      previewAudioRef.value.currentTime = 0
    } catch (_) {}
  }
  isPlayingPreview.value = false
}

async function previewEdgeVoice() {
  const voice = String(config.edge_voice || '').trim()
  if (!voice) return
  if (isPlayingPreview.value && lastPreviewVoice.value === voice && !previewSampleText.value) {
    stopPreviewAudio()
    return
  }
  stopPreviewAudio()
  previewingVoice.value = true
  previewError.value = ''
  try {
    const resp = await fetch('/api/tts/training/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        voice,
        text: previewSampleText.value
      })
    })
    const payload = await resp.json()
    if (!resp.ok || payload.code !== 0) {
      throw new Error(payload.msg || `HTTP ${resp.status}`)
    }
    previewAudioUrl.value = payload.data?.preview_audio || ''
    lastPreviewVoice.value = payload.data?.voice || voice
    await nextTick()
    if (previewAudioRef.value && previewAudioUrl.value) {
      try {
        await previewAudioRef.value.play()
      } catch (_) {}
    }
  } catch (err) {
    previewError.value = err.message
  } finally {
    previewingVoice.value = false
  }
}

watch(
  () => config.edge_voice,
  (nextVoice) => {
    if (lastPreviewVoice.value && nextVoice !== lastPreviewVoice.value) {
      stopPreviewAudio()
    }
  }
)

async function refreshStatus() {
  loadingStatus.value = true
  statusError.value = ''
  try {
    const slug = encodeURIComponent(config.slug || 'zh-tw-custom')
    const resp = await fetch(`/api/tts/training?slug=${slug}`)
    const payload = await resp.json()
    if (!resp.ok || payload.code !== 0) {
      throw new Error(payload.msg || `HTTP ${resp.status}`)
    }
    const data = payload.data || {}
    Object.assign(prereq, data.prerequisites || {})
    Object.assign(workspace, data.workspace || {})
    if (Array.isArray(data.edge_voices) && data.edge_voices.length) {
      edgeVoices.value = data.edge_voices
    }
    prompts.value = data.prompts || []
    trainedModels.value = data.trained_models || []
    sessionCount.value = Number(data.session_count || 0)
    job.value = data.job || null

    if (job.value?.status === 'done' && job.value.id !== lastFinishedJobId) {
      lastFinishedJobId = job.value.id
      if (job.value.current_step === 'export' || job.value.mode === 'full') {
        emit('notification', t('settings.ttsTraining.exportDoneNotice'), 'success')
      }
    }

    await nextTick()
    if (logBoxRef.value) {
      logBoxRef.value.scrollTop = logBoxRef.value.scrollHeight
    }
  } catch (err) {
    statusError.value = err.message
  } finally {
    loadingStatus.value = false
  }
}

async function runStep(step) {
  submitting.value = true
  statusError.value = ''
  try {
    const resp = await fetch('/api/tts/training/step', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step, ...config })
    })
    const payload = await resp.json()
    if (!resp.ok || payload.code !== 0) {
      if (resp.status === 409 && payload.need_disconnect) {
        emit('request-disconnect')
      }
      throw new Error(payload.msg || `HTTP ${resp.status}`)
    }
    job.value = payload.data
    startPolling()
  } catch (err) {
    statusError.value = err.message
    emit('notification', err.message, 'error')
  } finally {
    submitting.value = false
  }
}

async function cancelJob() {
  try {
    const resp = await fetch('/api/tts/training/cancel', { method: 'POST' })
    const payload = await resp.json()
    if (payload.code === 0 && payload.data) {
      job.value = payload.data
    }
  } catch (err) {
    statusError.value = err.message
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    await refreshStatus()
    if (!isRunning.value) {
      stopPolling()
    }
  }, 1500)
}

watch(
  () => props.active,
  (active) => {
    if (active) {
      refreshStatus().then(() => {
        if (isRunning.value) startPolling()
      })
    } else {
      stopPreviewAudio()
      stopPolling()
    }
  }
)

onMounted(() => {
  if (props.active) {
    refreshStatus().then(() => {
      if (isRunning.value) startPolling()
    })
  }
})

onBeforeUnmount(() => {
  stopPreviewAudio()
  stopPolling()
})
</script>

<style scoped>
.tts-training-card {
  width: 100%;
}

.training-eyebrow {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
  margin-bottom: 3px;
}

.training-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.danger-outline {
  border-color: rgba(239, 68, 68, 0.5);
  color: #fca5a5;
}

.training-pipeline-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 780px) {
  .training-pipeline-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.pipeline-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: var(--bg-input);
  font-size: 12.5px;
  color: var(--text-secondary);
}

.pipeline-pill.state-done {
  border-color: rgba(46, 204, 113, 0.45);
  background: rgba(46, 204, 113, 0.1);
  color: var(--text-primary);
}

.pipeline-pill.state-running {
  border-color: rgba(56, 189, 248, 0.6);
  background: rgba(56, 189, 248, 0.14);
  color: var(--text-primary);
}

.pipeline-pill.state-failed {
  border-color: rgba(239, 68, 68, 0.55);
  background: rgba(239, 68, 68, 0.12);
  color: #fca5a5;
}

.pill-index {
  width: 20px;
  height: 20px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.12);
  flex-shrink: 0;
}

.prereq-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.prereq-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
}

.prereq-badge.ok {
  color: #34d399;
}

.prereq-badge.missing {
  color: #f87171;
}

.prereq-badge.warn {
  color: #fbbf24;
}

.training-alert {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  font-size: 12.5px;
}

.alert-lead {
  display: flex;
  align-items: center;
  gap: 8px;
}

.training-alert.warning,
.training-alert.noncommercial {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.38);
  color: #fcd34d;
}

.training-alert.error {
  background: rgba(239, 68, 68, 0.14);
  border: 1px solid rgba(239, 68, 68, 0.45);
  color: #fca5a5;
}

.steps-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.training-step-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  background: var(--bg-input);
}

.step-summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  gap: 8px;
  font-size: 13.5px;
  color: var(--text-primary);
}

.step-chip {
  font-size: 11.5px;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}

.step-chip.ready {
  background: rgba(46, 204, 113, 0.16);
  border-color: rgba(46, 204, 113, 0.4);
  color: #6ee7b7;
}

.step-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.step-explain {
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
  margin: 0;
}

.step-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.step-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: var(--text-secondary);
}

.step-field.full-width {
  width: 100%;
}

.voice-preview-combo {
  display: flex;
  align-items: center;
  gap: 6px;
}

.voice-preview-combo .std-select,
.voice-preview-combo .std-input {
  flex: 1;
  min-width: 0;
}

.preview-voice-btn,
.mode-toggle-btn {
  flex-shrink: 0;
  padding: 7px 12px;
  font-size: 12px;
  white-space: nowrap;
}

.preview-player-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.preview-player-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  flex-wrap: wrap;
}

.preview-voice-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-light);
}

.preview-audio-ctrl {
  flex: 1;
  min-width: 200px;
  height: 32px;
}

.step-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-secondary);
  padding-top: 20px;
}

.step-actions {
  display: flex;
  justify-content: flex-end;
}

.job-status-box {
  padding: 14px 16px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(56, 189, 248, 0.35);
  background: var(--bg-input);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.job-status-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.job-meta {
  font-size: 12px;
  color: var(--text-tertiary);
}

.progress-track {
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.1);
}

.progress-fill {
  height: 100%;
  background: #38bdf8;
  transition: width 0.25s ease;
}

.progress-fill.done {
  background: #34d399;
}

.progress-fill.failed {
  background: #f87171;
}

.job-log-tail {
  margin: 0;
  padding: 10px 12px;
  max-height: 220px;
  overflow-y: auto;
  border-radius: var(--radius-sm);
  background: rgba(0, 0, 0, 0.45);
  font-size: 11.5px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.trained-models-box {
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.trained-models-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.trained-model-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  flex-wrap: wrap;
}

.trained-model-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
}

.license-pill {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(59, 130, 246, 0.16);
  color: #93c5fd;
}

.license-pill.noncommercial {
  background: rgba(245, 158, 11, 0.18);
  color: #fcd34d;
  border: 1px solid rgba(245, 158, 11, 0.45);
}
</style>
