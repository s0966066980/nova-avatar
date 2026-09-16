<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="rag-layout">
    <section class="rag-card">
      <div class="rag-heading">
        <div>
          <h2><i class="bi bi-journal-text" aria-hidden="true"></i> 知識庫檢索</h2>
          <p>RAGFlow 負責找資料；數位人的回答仍由目前的 AI 模型產生。</p>
        </div>
        <span class="rag-status" :class="statusKind" role="status" aria-atomic="true">
          {{ statusText }}
        </span>
      </div>

      <p class="rag-scope">
        目前數位人：<strong>{{ avatarId || '尚未選擇' }}</strong>。啟用狀態與知識庫只套用於這位數位人。
      </p>
      <p v-if="!loading && !configured" class="rag-alert" role="alert">
        尚未在後端設定 RAGFlow API 金鑰。設定完成前，現有對話不受影響。
      </p>
      <p v-if="loadError" class="rag-alert" role="alert">{{ loadError }}</p>

      <div class="rag-toggle-row">
        <label class="rag-checkbox">
          <input v-model="draft.enabled" type="checkbox" :disabled="!avatarId || saving">
          <span>為這位數位人啟用檢索</span>
        </label>
        <span>儲存後從下一輪對話生效</span>
      </div>

      <div class="rag-section-heading">
        <h3>選擇知識庫</h3>
        <button type="button" class="rag-secondary" :disabled="loading || !configured" @click="refreshDatasets()">
          <i class="bi bi-arrow-clockwise" aria-hidden="true"></i> 重新整理
        </button>
      </div>
      <p class="rag-hint">先在 RAGFlow 建立知識庫、上傳文件並完成解析，再於此選取；最多 8 個。</p>
      <div v-if="loading" class="rag-placeholder" role="status">正在載入知識庫…</div>
      <div v-else-if="datasets.length" class="rag-dataset-list">
        <label v-for="dataset in datasets" :key="dataset.id" class="rag-dataset">
          <input v-model="draft.datasetIds" type="checkbox" :value="dataset.id" :disabled="saving || (!draft.datasetIds.includes(dataset.id) && draft.datasetIds.length >= 8)">
          <span class="rag-dataset-copy">
            <strong>{{ dataset.name }}</strong>
            <small>{{ dataset.document_count }} 份文件 · {{ dataset.embedding_model || '嵌入模型未指定' }}</small>
          </span>
        </label>
      </div>
      <p v-else class="rag-placeholder">目前沒有可選的知識庫。請先在 RAGFlow 完成文件解析。</p>
      <p v-if="serviceReady && missingDatasetIds.length" class="rag-alert" role="alert">
        已儲存的知識庫不在目前清單中：{{ missingDatasetIds.join('、') }}。請檢查 RAGFlow 帳號或重新選擇。
      </p>

      <div class="rag-actions">
        <a :href="managementUrl" target="_blank" rel="noopener noreferrer" class="rag-secondary">
          <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i> 開啟本機 RAGFlow
        </a>
        <button type="button" class="rag-primary" :disabled="!avatarId || saving || !dirty" @click="save">
          {{ saving ? '儲存中…' : '儲存檢索設定' }}
        </button>
      </div>
      <p v-if="saveNotice" class="rag-notice" role="status" aria-atomic="true">{{ saveNotice }}</p>
      <p v-if="saveError" class="rag-alert" role="alert">{{ saveError }}</p>
    </section>

    <section class="rag-card">
      <h3><i class="bi bi-search" aria-hidden="true"></i> 測試檢索</h3>
      <p class="rag-hint">只顯示找到的文件片段，不會呼叫回答模型，也不會加入對話歷史。</p>
      <label class="rag-test-label" for="rag-test-question">測試問題</label>
      <textarea id="rag-test-question" v-model.trim="testQuestion" rows="3" maxlength="2000" placeholder="輸入文件能回答的問題"></textarea>
      <div class="rag-actions">
        <span v-if="dirty" class="rag-hint">先儲存知識庫選擇，再執行測試。</span>
        <button type="button" class="rag-primary" :disabled="testing || dirty || !serviceReady || !saved.datasetIds.length || !testQuestion.trim()" @click="runTest">
          {{ testing ? '檢索中…' : '測試檢索' }}
        </button>
      </div>
      <p v-if="testError" class="rag-alert" role="alert">{{ testError }}</p>
      <div v-if="testResult" role="status" aria-atomic="true">
        <p class="rag-result-summary">{{ testResult.status === 'matched' ? `找到 ${testResult.sources.length} 段檢索參考` : '知識庫沒有找到相關資料' }}</p>
        <ol v-if="testResult.sources.length" class="rag-results">
          <li v-for="(source, index) in testResult.sources" :key="`${source.document_id}-${index}`">
            <strong>{{ source.document_name || '未命名文件' }}</strong>
            <p>{{ source.content }}</p>
          </li>
        </ol>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  avatarId: { type: String, default: '' },
  active: { type: Boolean, default: false }
})

const draft = reactive({ enabled: false, datasetIds: [] })
const saved = reactive({ enabled: false, datasetIds: [] })
const configured = ref(false)
const managementUrl = ref('http://127.0.0.1:8088')
const datasets = ref([])
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const saveError = ref('')
const saveNotice = ref('')
const testing = ref(false)
const testQuestion = ref('')
const testError = ref('')
const testResult = ref(null)
const serviceReady = ref(false)
let loadGeneration = 0

const dirty = computed(() => draft.enabled !== saved.enabled ||
  JSON.stringify([...draft.datasetIds].sort()) !== JSON.stringify([...saved.datasetIds].sort()))
const missingDatasetIds = computed(() => saved.datasetIds.filter(id => !datasets.value.some(item => item.id === id)))
const statusKind = computed(() => loading.value ? 'loading' : !configured.value ? 'unconfigured' : serviceReady.value ? 'ready' : 'unavailable')
const statusText = computed(() => loading.value ? '連線檢查中…' : !configured.value ? '尚未設定金鑰' : serviceReady.value ? 'RAGFlow 已連線' : 'RAGFlow 未連線')

async function readJson(response) {
  const body = await response.json()
  if (!response.ok || body.code !== 0) throw new Error(body.msg || 'RAGFlow 請求失敗')
  return body.data
}

async function load() {
  const generation = ++loadGeneration
  if (!props.active || !props.avatarId) return
  const avatarId = props.avatarId
  loading.value = true
  saving.value = false
  testing.value = false
  serviceReady.value = false
  loadError.value = ''
  saveNotice.value = ''
  testResult.value = null
  try {
    const data = await readJson(await fetch(`/api/ragflow/settings?avatar_id=${encodeURIComponent(avatarId)}`))
    if (generation !== loadGeneration) return
    saved.enabled = Boolean(data.enabled)
    saved.datasetIds = [...(data.dataset_ids || [])]
    draft.enabled = saved.enabled
    draft.datasetIds = [...saved.datasetIds]
    configured.value = Boolean(data.configured)
    managementUrl.value = data.management_url || managementUrl.value
    await refreshDatasets(generation)
  } catch (error) {
    if (generation === loadGeneration) loadError.value = error.message
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function refreshDatasets(generation = loadGeneration) {
  if (!configured.value) {
    serviceReady.value = false
    datasets.value = []
    return
  }
  try {
    const data = await readJson(await fetch('/api/ragflow/datasets'))
    if (generation !== loadGeneration) return
    datasets.value = data.datasets || []
    serviceReady.value = true
    loadError.value = ''
  } catch (error) {
    if (generation !== loadGeneration) return
    serviceReady.value = false
    datasets.value = []
    loadError.value = error.message
  }
}

async function save() {
  const generation = loadGeneration
  const avatarId = props.avatarId
  saveError.value = ''
  saveNotice.value = ''
  if (draft.enabled && !draft.datasetIds.length) {
    saveError.value = '請先選擇至少一個知識庫。'
    return
  }
  saving.value = true
  try {
    const data = await readJson(await fetch('/api/ragflow/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar_id: avatarId, enabled: draft.enabled, dataset_ids: draft.datasetIds })
    }))
    if (generation !== loadGeneration) return
    saved.enabled = Boolean(data.enabled)
    saved.datasetIds = [...data.dataset_ids]
    saveNotice.value = '已儲存，從下一輪對話生效。'
  } catch (error) {
    if (generation === loadGeneration) saveError.value = error.message
  } finally {
    if (generation === loadGeneration) saving.value = false
  }
}

async function runTest() {
  const generation = loadGeneration
  const avatarId = props.avatarId
  testing.value = true
  testError.value = ''
  testResult.value = null
  try {
    const result = await readJson(await fetch('/api/ragflow/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ avatar_id: avatarId, question: testQuestion.value.trim() })
    }))
    if (generation === loadGeneration) testResult.value = result
  } catch (error) {
    if (generation === loadGeneration) testError.value = error.message
  } finally {
    if (generation === loadGeneration) testing.value = false
  }
}

watch(() => [props.active, props.avatarId], load, { immediate: true })
</script>

<style scoped>
.rag-layout { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(300px, 1fr); gap: 18px; align-items: start; }
.rag-card { padding: 24px; border: 1px solid var(--border-default); border-radius: var(--radius-lg); background: var(--bg-surface); color: var(--text-primary); }
.rag-heading, .rag-section-heading, .rag-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.rag-heading { align-items: flex-start; }
h2, h3 { margin: 0; font-size: 19px; font-weight: 700; }
h3 { font-size: 16px; }
h2 i, h3 i { color: var(--brand-light); margin-right: 8px; }
.rag-heading p, .rag-hint, .rag-scope, .rag-placeholder { color: var(--text-secondary); font-size: 13px; line-height: 1.55; }
.rag-scope { margin: 20px 0; }
.rag-status { white-space: nowrap; border: 1px solid var(--border-default); border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 700; }
.rag-status.ready { color: var(--success); }
.rag-status.unavailable, .rag-status.unconfigured { color: var(--warning); }
.rag-alert { margin: 12px 0; padding: 10px 12px; border: 1px solid var(--warning); border-radius: var(--radius-sm); color: var(--text-primary); font-size: 13px; line-height: 1.5; }
.rag-toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 0; border-block: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 12px; }
.rag-checkbox, .rag-dataset { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.rag-checkbox { color: var(--text-primary); font-size: 14px; font-weight: 700; }
input[type='checkbox'] { width: 18px; height: 18px; accent-color: var(--brand-light); flex: none; }
.rag-section-heading { margin-top: 22px; }
.rag-dataset-list { display: grid; gap: 8px; margin: 14px 0; max-height: 320px; overflow-y: auto; }
.rag-dataset { padding: 11px 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: var(--bg-surface-elevated); }
.rag-dataset:focus-within { outline: 2px solid var(--brand-light); outline-offset: 2px; }
.rag-dataset-copy { display: grid; gap: 3px; min-width: 0; }
.rag-dataset-copy strong { overflow-wrap: anywhere; font-size: 13px; }
.rag-dataset-copy small { color: var(--text-secondary); }
.rag-actions { margin-top: 18px; justify-content: flex-end; flex-wrap: wrap; }
.rag-primary, .rag-secondary { min-height: 40px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 8px 14px; border-radius: var(--radius-sm); font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; text-decoration: none; }
.rag-primary { border: 1px solid var(--brand-light); background: var(--brand-light); color: #111827; }
.rag-secondary { border: 1px solid var(--border-default); background: var(--bg-surface-elevated); color: var(--text-primary); }
button:disabled { opacity: 0.55; cursor: not-allowed; }
.rag-notice { color: var(--success); font-size: 13px; }
.rag-test-label { display: block; margin-top: 18px; margin-bottom: 7px; font-size: 13px; font-weight: 700; }
textarea { width: 100%; min-height: 90px; box-sizing: border-box; resize: vertical; padding: 10px 12px; border: 1px solid var(--border-default); border-radius: var(--radius-sm); color: var(--text-primary); background: var(--bg-surface-elevated); font: inherit; }
textarea:focus-visible, button:focus-visible, a:focus-visible { outline: 2px solid var(--brand-light); outline-offset: 2px; }
.rag-result-summary { margin: 18px 0 8px; font-weight: 700; }
.rag-results { padding-left: 22px; display: grid; gap: 12px; }
.rag-results li { padding: 10px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); overflow-wrap: anywhere; }
.rag-results p { white-space: pre-wrap; color: var(--text-secondary); font-size: 13px; line-height: 1.5; }
@media (max-width: 900px) { .rag-layout { grid-template-columns: 1fr; } }
@media (max-width: 540px) { .rag-card { padding: 16px; } .rag-heading, .rag-toggle-row { align-items: flex-start; flex-direction: column; } }
</style>
