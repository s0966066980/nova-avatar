<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="rag-editor">
    <div class="rag-heading">
      <div><h3>RAG 知識庫與文本</h3><p>設定「{{ profileName }}」可以參考的資料。{{ ragScopeLabel(selection) }}</p></div>
      <button type="button" :disabled="loading || disabled" @click="refresh">{{ loading ? '連線檢查中…' : '重新整理知識庫' }}</button>
    </div>
    <p class="rag-hint">選擇會隨這份數位人設定檔儲存；即使共用人物素材，也各自使用自己的文本。</p>
    <p v-if="loadError" class="rag-alert" role="alert">{{ loadError }}</p>
    <p v-else-if="!loading && !configured" class="rag-alert" role="status">後端尚未設定 RAGFlow API 金鑰，設定完成後可讀取文件。</p>
    <p v-else-if="ready" class="rag-connected" role="status">RAGFlow 已連線</p>
    <label class="rag-check"><input type="checkbox" :checked="selection.enabled" :disabled="disabled" @change="update({ enabled: $event.target.checked })">為「{{ profileName }}」啟用知識庫檢索</label>
    <div class="rag-columns">
      <section aria-label="選擇知識庫">
        <h4>1. 選擇知識庫 <small>{{ selection.dataset_ids.length }} / 8</small></h4>
        <div class="rag-list">
          <label v-for="dataset in datasets" :key="dataset.id" class="rag-item">
            <input type="checkbox" :checked="selection.dataset_ids.includes(dataset.id)" :disabled="disabled || (!selection.dataset_ids.includes(dataset.id) && selection.dataset_ids.length >= 8)" @change="chooseDataset(dataset.id, $event.target.checked)">
            <span><strong>{{ dataset.name }}</strong><small>{{ dataset.document_count }} 份文件 · {{ dataset.embedding_model || '未指定嵌入模型' }}</small></span>
          </label>
        </div>
        <p v-if="!loading && ready && !datasets.length" class="rag-hint">目前沒有知識庫，請先在 RAGFlow 上傳並解析文件。</p>
        <div v-for="id in missingDatasets" :key="id" class="rag-alert">
          已選知識庫暫時無法讀取：<code>{{ id }}</code>
          <button type="button" :disabled="disabled" @click="chooseDataset(id, false)">移除選擇</button>
        </div>
        <p class="rag-hint">移除知識庫會清除指定文件選擇，請重新勾選所需文本。</p>
        <a :href="managementUrl" target="_blank" rel="noopener noreferrer">在 RAGFlow 上傳與管理文件 <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i></a>
      </section>
      <section aria-label="選擇文本">
        <h4>2. 設定文本範圍</h4>
        <label class="rag-check"><input type="radio" :name="`rag-scope-${profileId}`" value="all" :checked="selection.document_scope === 'all'" :disabled="disabled" @change="update({ document_scope: 'all', document_ids: [] })">使用所選知識庫的全部文件</label>
        <label class="rag-check"><input type="radio" :name="`rag-scope-${profileId}`" value="selected" :checked="selection.document_scope === 'selected'" :disabled="disabled" @change="update({ document_scope: 'selected', document_ids: [] })">只使用指定文本（最多 200 份）</label>
        <p class="rag-hint">全部文件會包含之後新增的文件；指定文本只檢索勾選的文件。</p>
        <p v-if="!selection.dataset_ids.length" class="rag-hint">先選擇知識庫，再查看文件名稱與解析狀態。</p>
        <div v-for="id in selection.dataset_ids" :key="id" class="rag-document-group">
          <h5>{{ datasetName(id) }}</h5>
          <p v-if="documentLists[id]?.loading" class="rag-hint" role="status">正在讀取文件…</p>
          <p v-if="documentLists[id]?.error" class="rag-alert" role="alert">{{ documentLists[id].error }} <button type="button" @click="loadDocuments(id)">重試</button></p>
          <div class="rag-list">
            <label v-for="doc in documentLists[id]?.documents || []" :key="doc.id" class="rag-item">
              <input type="checkbox" :checked="selection.document_scope === 'all' || selection.document_ids.includes(doc.id)" :disabled="disabled || selection.document_scope === 'all' || (!selection.document_ids.includes(doc.id) && selection.document_ids.length >= 200)" @change="chooseDocument(doc.id, $event.target.checked)">
              <span><strong>{{ doc.name }}</strong><small>{{ documentStatus(doc) }}</small></span>
            </label>
          </div>
          <p v-if="documentLists[id] && !documentLists[id].loading && !documentLists[id].error && !documentLists[id].documents.length" class="rag-hint">這個知識庫尚無文件。</p>
          <button v-if="documentLists[id]?.has_more" type="button" :disabled="documentLists[id].loading" @click="loadDocuments(id, documentLists[id].page + 1)">載入更多文件</button>
        </div>
        <div v-for="id in missingDocuments" :key="id" class="rag-alert">已指定文件尚未在清單中載入，或已移除：<code>{{ id }}</code><button type="button" :disabled="disabled" @click="chooseDocument(id, false)">移除選擇</button></div>
        <p v-if="selection.enabled && scopeError" class="rag-alert" role="alert">{{ scopeError }}</p>
      </section>
    </div>
    <section class="rag-test">
      <h4>3. 測試此角色的檢索範圍</h4>
      <p class="rag-hint">使用目前草稿的知識庫與文本選擇，只顯示檢索片段。儲存並套用設定後，正式對話才會使用這個範圍。</p>
      <label :for="`rag-question-${profileId}`">測試問題</label>
      <textarea :id="`rag-question-${profileId}`" v-model="testQuestion" rows="3" maxlength="2000" placeholder="輸入這些文本應該能回答的問題"></textarea>
      <button type="button" :disabled="disabled || testing || !ready || Boolean(scopeError) || !testQuestion.trim()" @click="runTest">{{ testing ? '檢索中…' : '測試目前草稿' }}</button>
      <p v-if="testError" class="rag-alert" role="alert">{{ testError }}</p>
      <div v-if="testResult" role="status">
        <p>{{ testResult.sources.length ? `找到 ${testResult.sources.length} 段文本參考` : '所選範圍內沒有找到相關資料' }}</p>
        <ol class="rag-results"><li v-for="(source, index) in testResult.sources" :key="index"><strong>{{ source.document_name || '未命名文件' }}</strong><p>{{ source.content }}</p></li></ol>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { normalizeRagSelection, toggleDataset, selectionError, ragScopeLabel } from '../ragScope.js'

const props = defineProps({
  modelValue: { type: Object, required: true },
  profileId: { type: String, required: true },
  profileName: { type: String, required: true },
  disabled: Boolean
})
const emit = defineEmits(['update:modelValue'])
const selection = computed(() => normalizeRagSelection(props.modelValue))
const scopeError = computed(() => selectionError(selection.value))
const configured = ref(false), ready = ref(false), loading = ref(false), loadError = ref('')
const datasets = ref([]), documentLists = ref({}), managementUrl = ref('http://127.0.0.1:8088')
const testQuestion = ref(''), testing = ref(false), testError = ref(''), testResult = ref(null)
let generation = 0, testGeneration = 0
const missingDatasets = computed(() => ready.value ? selection.value.dataset_ids.filter(id => !datasets.value.some(d => d.id === id)) : [])
const missingDocuments = computed(() => selection.value.document_ids.filter(id => !Object.values(documentLists.value).some(list => list.documents.some(d => d.id === id))))
const datasetName = id => datasets.value.find(d => d.id === id)?.name || id
const update = changes => emit('update:modelValue', { ...selection.value, ...changes })
const chooseDataset = (id, checked) => emit('update:modelValue', toggleDataset(selection.value, id, checked))
const chooseDocument = (id, checked) => update({ document_ids: checked ? [...new Set([...selection.value.document_ids, id])] : selection.value.document_ids.filter(x => x !== id) })
const documentStatus = doc => ({ DONE: '解析完成', 3: '解析完成', RUNNING: '解析中', 1: '解析中', UNSTART: '尚未解析', 0: '尚未解析', FAIL: '解析失敗', 4: '解析失敗', CANCEL: '解析已取消', 2: '解析已取消' }[doc.run] || '解析狀態未知') + ` · ${doc.chunk_count} 個片段`

async function readJson(response) {
  const body = await response.json()
  if (!response.ok || body.code !== 0) throw Error(body.msg || 'RAGFlow 請求失敗')
  return body.data
}
async function refresh() {
  const current = ++generation
  loading.value = true; loadError.value = ''; ready.value = false
  documentLists.value = {}
  try {
    const status = await readJson(await fetch('/api/ragflow/status'))
    if (current !== generation) return
    configured.value = status.configured
    managementUrl.value = status.management_url || managementUrl.value
    if (!configured.value) return
    const data = await readJson(await fetch('/api/ragflow/datasets'))
    if (current !== generation) return
    datasets.value = data.datasets || []; ready.value = true
    await Promise.all(selection.value.dataset_ids.map(id => loadDocuments(id)))
  } catch (error) {
    if (current === generation) loadError.value = error.message
  } finally { if (current === generation) loading.value = false }
}
async function loadDocuments(id, page = 1) {
  const current = generation
  const entry = documentLists.value[id] = { documents: page > 1 ? documentLists.value[id]?.documents || [] : [], loading: true, error: '', page, has_more: false }
  try {
    const data = await readJson(await fetch(`/api/ragflow/datasets/${encodeURIComponent(id)}/documents?page=${page}`))
    if (current !== generation) return
    entry.documents = [...entry.documents, ...data.documents]; entry.has_more = data.has_more
  } catch (error) { if (current === generation) entry.error = error.message }
  finally { if (current === generation) { entry.loading = false; documentLists.value = { ...documentLists.value } } }
}
async function runTest() {
  const current = ++testGeneration
  testing.value = true; testError.value = ''; testResult.value = null
  try {
    const result = await readJson(await fetch('/api/ragflow/test', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: props.profileId, selection: selection.value, question: testQuestion.value.trim() })
    }))
    if (current === testGeneration) testResult.value = result
  } catch (error) { if (current === testGeneration) testError.value = error.message }
  finally { if (current === testGeneration) testing.value = false }
}
watch(() => selection.value.dataset_ids.join(','), () => {
  if (ready.value) for (const id of selection.value.dataset_ids) if (!documentLists.value[id]) loadDocuments(id)
})
watch(() => [props.profileId, JSON.stringify(selection.value), testQuestion.value], () => {
  ++testGeneration; testing.value = false; testResult.value = null; testError.value = ''
})
onMounted(refresh)
onUnmounted(() => { ++generation; ++testGeneration })
</script>

<style scoped>
.rag-editor{min-width:0}.rag-heading{display:flex;justify-content:space-between;align-items:start;gap:16px;flex-wrap:wrap}.rag-editor h3{margin:0;font-size:18px}.rag-editor h4{font-size:14px;margin:16px 0}.rag-editor h5{font-size:13px;margin:12px 0}.rag-editor p,.rag-hint{font-size:13px;line-height:1.65;color:var(--text-secondary)}.rag-heading p{margin:8px 0}.rag-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:28px}.rag-editor label{font-size:13px}.rag-check,.rag-item{display:flex;gap:10px;align-items:center;margin:12px 0}.rag-item{padding:12px;border:1px solid var(--border-default);border-radius:8px;background:var(--bg-surface-elevated);margin:0}.rag-item span{display:grid;gap:5px;min-width:0;overflow-wrap:anywhere}.rag-editor input{width:17px;height:17px;flex:none;accent-color:var(--brand-light)}.rag-list{display:grid;gap:8px;max-height:310px;overflow:auto;padding:3px}.rag-editor small{font-size:12px;color:var(--text-secondary);font-weight:400}.rag-alert{padding:12px;border:1px solid var(--warning);border-radius:8px;overflow-wrap:anywhere}.rag-connected{color:var(--success)!important}.rag-editor code{color:inherit;overflow-wrap:anywhere}.rag-test{border-top:1px solid var(--border-subtle);margin-top:24px;padding-top:8px}.rag-test>label{display:block;margin-bottom:8px}.rag-editor textarea{display:block;width:100%;padding:12px;color:var(--text-primary);background:var(--bg-surface-elevated);border:1px solid var(--border-default);border-radius:8px;font:inherit;resize:vertical;margin-bottom:12px}.rag-editor button,.rag-editor a{font-size:13px}.rag-editor button{padding:8px 12px;border:1px solid var(--border-default);background:var(--bg-surface-elevated);color:var(--text-primary);border-radius:8px;cursor:pointer}.rag-editor button:disabled{opacity:.5;cursor:not-allowed}.rag-editor a{color:var(--brand-light)}.rag-editor :focus-visible{outline:2px solid var(--brand-light);outline-offset:3px}.rag-results li{padding:12px;overflow-wrap:anywhere}.rag-results p{white-space:pre-wrap}@media(max-width:900px){.rag-columns{grid-template-columns:1fr;gap:12px}}
</style>
