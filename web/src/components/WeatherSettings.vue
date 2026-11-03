<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="weather-layout">
    <section class="weather-card">
      <div class="weather-heading">
        <div>
          <h2><i class="bi bi-cloud-sun" aria-hidden="true"></i> 即時氣象查詢（中央氣象署）</h2>
          <p>查詢臺灣各縣市及鄉鎮市區的即時觀測與未來 7 天天氣預報；回答仍由目前的 AI 模型產生。</p>
        </div>
        <span class="weather-status" :class="statusKind" role="status" aria-atomic="true">
          {{ statusText }}
        </span>
      </div>

      <p v-if="!loading && !configured" class="weather-alert" role="alert">
        尚未設定中央氣象署 API 金鑰（<code>NOVA_CWA_API_KEY</code> 或 <code>config/cwa.env</code>）。設定完成前，詢問天氣時將自動提醒暫時無法取得最新天氣資料。
      </p>
      <p v-if="loadError" class="weather-alert" role="alert">{{ loadError }}</p>

      <div class="weather-toggle-row">
        <label class="weather-checkbox">
          <input v-model="draft.enabled" type="checkbox" :disabled="saving">
          <span>啟用中央氣象署即時氣象查詢</span>
        </label>
        <span>儲存後從下一輪對話生效</span>
      </div>

      <div class="weather-fields">
        <div class="weather-field">
          <label for="weather-default-county">場域預設縣市</label>
          <select id="weather-default-county" v-model="draft.county" :disabled="saving" @change="onCountyChange">
            <option value="">不指定（訪客未提地點時主動追問）</option>
            <option v-for="county in counties" :key="county" :value="county">{{ county }}</option>
          </select>
          <small>若數位人固定部署於特定展場，可設定預設縣市；未設定時會先向訪客確認縣市。</small>
        </div>

        <div class="weather-field">
          <label for="weather-default-town">場域預設鄉鎮市區（選填）</label>
          <input
            id="weather-default-town"
            v-model.trim="draft.town"
            type="text"
            maxlength="40"
            :disabled="saving || !draft.county"
            placeholder="例如：板橋區、信義區（留空代表縣市整體預報）"
          >
          <small>指定鄉鎮市區時會使用中央氣象署 368 鄉鎮預報資料。</small>
        </div>
      </div>

      <div class="weather-actions">
        <a :href="sourceUrl" target="_blank" rel="noopener noreferrer" class="weather-secondary">
          <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i> {{ sourceName }}
        </a>
        <button type="button" class="weather-primary" :disabled="saving || !dirty" @click="save">
          {{ saving ? '儲存中…' : '儲存氣象設定' }}
        </button>
      </div>
      <p v-if="saveNotice" class="weather-notice" role="status" aria-atomic="true">{{ saveNotice }}</p>
      <p v-if="saveError" class="weather-alert" role="alert">{{ saveError }}</p>
    </section>

    <section class="weather-card">
      <h3><i class="bi bi-compass" aria-hidden="true"></i> 測試氣象查詢</h3>
      <p class="weather-hint">測試地點與日期解析及中央氣象署查詢結果，不會呼叫回答模型，也不會加入對話歷史。</p>
      <label class="weather-test-label" for="weather-test-question">測試問題</label>
      <textarea
        id="weather-test-question"
        v-model.trim="testQuestion"
        rows="3"
        maxlength="500"
        placeholder="例如：今天臺北天氣如何？或 明天新北市板橋區會下雨嗎？"
      ></textarea>
      <div class="weather-actions">
        <span v-if="dirty" class="weather-hint">先儲存氣象設定，再執行測試。</span>
        <button
          type="button"
          class="weather-primary"
          :disabled="testing || dirty || !testQuestion.trim()"
          @click="runTest"
        >
          {{ testing ? '查詢中…' : '測試氣象查詢' }}
        </button>
      </div>
      <p v-if="testError" class="weather-alert" role="alert">{{ testError }}</p>
      <div v-if="testResult" class="weather-test-output" role="status" aria-atomic="true">
        <p class="weather-result-summary">
          路由判定：<strong>{{ routeLabel(testResult.route) }}</strong>
          <template v-if="testResult.plan && testResult.plan.county">
            · {{ testResult.plan.county }}{{ testResult.plan.town || '' }}
            （{{ testResult.plan.kind === 'current' ? '現在觀測' : `${testResult.plan.start_date} 預報` }}）
          </template>
        </p>
        <p class="weather-result-text">{{ testResult.summary }}</p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  active: { type: Boolean, default: false }
})

const DEFAULT_COUNTIES = [
  '基隆市', '臺北市', '新北市', '桃園市', '新竹市', '新竹縣',
  '苗栗縣', '臺中市', '彰化縣', '南投縣', '雲林縣', '嘉義市',
  '嘉義縣', '臺南市', '高雄市', '屏東縣', '宜蘭縣', '花蓮縣',
  '臺東縣', '澎湖縣', '金門縣', '連江縣'
]

const draft = reactive({ enabled: true, county: '', town: '' })
const saved = reactive({ enabled: true, county: '', town: '' })
const counties = ref([...DEFAULT_COUNTIES])
const configured = ref(false)
const sourceName = ref('中央氣象署開放資料平臺')
const sourceUrl = ref('https://opendata.cwa.gov.tw')
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const saveError = ref('')
const saveNotice = ref('')
const testing = ref(false)
const testQuestion = ref('')
const testError = ref('')
const testResult = ref(null)
let loadGeneration = 0

const dirty = computed(() =>
  draft.enabled !== saved.enabled ||
  draft.county !== saved.county ||
  draft.town !== saved.town
)

const statusKind = computed(() =>
  loading.value ? 'loading' : configured.value ? 'ready' : 'unconfigured'
)

const statusText = computed(() =>
  loading.value ? '檢查中…' : configured.value ? '已設定 CWA 金鑰' : '尚未設定金鑰'
)

function onCountyChange() {
  if (!draft.county) {
    draft.town = ''
  }
}

function routeLabel(route) {
  if (route === 'specialist') return '氣象查詢 (specialist)'
  if (route === 'clarify') return '地點追問 (clarify)'
  return '一般對話 (answer)'
}

async function readJson(response) {
  const body = await response.json()
  if (!response.ok || body.code !== 0) throw new Error(body.msg || '氣象設定請求失敗')
  return body.data
}

async function load() {
  const generation = ++loadGeneration
  if (!props.active) return
  loading.value = true
  saving.value = false
  testing.value = false
  loadError.value = ''
  saveNotice.value = ''
  testResult.value = null
  try {
    const data = await readJson(await fetch('/api/weather/settings'))
    if (generation !== loadGeneration) return
    saved.enabled = Boolean(data.enabled)
    saved.county = String(data.county || '')
    saved.town = String(data.town || '')
    draft.enabled = saved.enabled
    draft.county = saved.county
    draft.town = saved.town
    configured.value = Boolean(data.configured)
    if (Array.isArray(data.counties) && data.counties.length) {
      counties.value = [...data.counties]
    }
    if (data.source) sourceName.value = data.source
    if (data.source_url) sourceUrl.value = data.source_url
  } catch (error) {
    if (generation === loadGeneration) loadError.value = error.message
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

async function save() {
  const generation = loadGeneration
  saveError.value = ''
  saveNotice.value = ''
  saving.value = true
  try {
    const payload = {
      enabled: draft.enabled,
      county: draft.county,
      town: draft.county ? draft.town : ''
    }
    const data = await readJson(await fetch('/api/weather/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }))
    if (generation !== loadGeneration) return
    saved.enabled = Boolean(data.enabled)
    saved.county = String(data.county || '')
    saved.town = String(data.town || '')
    draft.enabled = saved.enabled
    draft.county = saved.county
    draft.town = saved.town
    configured.value = Boolean(data.configured)
    saveNotice.value = '已儲存，從下一輪對話生效。'
  } catch (error) {
    if (generation === loadGeneration) saveError.value = error.message
  } finally {
    if (generation === loadGeneration) saving.value = false
  }
}

async function runTest() {
  const generation = loadGeneration
  testing.value = true
  testError.value = ''
  testResult.value = null
  try {
    const result = await readJson(await fetch('/api/weather/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: testQuestion.value.trim() })
    }))
    if (generation === loadGeneration) testResult.value = result
  } catch (error) {
    if (generation === loadGeneration) testError.value = error.message
  } finally {
    if (generation === loadGeneration) testing.value = false
  }
}

watch(() => props.active, load, { immediate: true })
</script>

<style scoped>
.weather-layout { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(300px, 1fr); gap: 18px; align-items: start; margin-top: 18px; }
.weather-card { padding: 24px; border: 1px solid var(--border-default); border-radius: var(--radius-lg); background: var(--bg-surface); color: var(--text-primary); }
.weather-heading, .weather-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.weather-heading { align-items: flex-start; }
h2, h3 { margin: 0; font-size: 19px; font-weight: 700; }
h3 { font-size: 16px; }
h2 i, h3 i { color: var(--brand-light); margin-right: 8px; }
.weather-heading p, .weather-hint { color: var(--text-secondary); font-size: 13px; line-height: 1.55; }
.weather-status { white-space: nowrap; border: 1px solid var(--border-default); border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 700; }
.weather-status.ready { color: var(--success); }
.weather-status.unconfigured { color: var(--warning); }
.weather-alert { margin: 12px 0; padding: 10px 12px; border: 1px solid var(--warning); border-radius: var(--radius-sm); color: var(--text-primary); font-size: 13px; line-height: 1.5; }
.weather-toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 16px 0; margin-top: 12px; border-block: 1px solid var(--border-subtle); color: var(--text-secondary); font-size: 12px; }
.weather-checkbox { display: flex; align-items: center; gap: 10px; cursor: pointer; color: var(--text-primary); font-size: 14px; font-weight: 700; }
input[type='checkbox'] { width: 18px; height: 18px; accent-color: var(--brand-light); flex: none; }
.weather-fields { display: grid; gap: 16px; margin-top: 18px; }
.weather-field { display: grid; gap: 6px; }
.weather-field label, .weather-test-label { font-size: 13px; font-weight: 700; display: block; }
.weather-field small { color: var(--text-secondary); font-size: 12px; line-height: 1.45; }
select, input[type='text'], textarea { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid var(--border-default); border-radius: var(--radius-sm); color: var(--text-primary); background: var(--bg-surface-elevated); font: inherit; font-size: 13px; }
textarea { min-height: 90px; resize: vertical; }
select:focus-visible, input[type='text']:focus-visible, textarea:focus-visible, button:focus-visible, a:focus-visible { outline: 2px solid var(--brand-light); outline-offset: 2px; }
.weather-actions { margin-top: 18px; justify-content: flex-end; flex-wrap: wrap; }
.weather-primary, .weather-secondary { min-height: 40px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 8px 14px; border-radius: var(--radius-sm); font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; text-decoration: none; }
.weather-primary { border: 1px solid var(--brand-light); background: var(--brand-light); color: #111827; }
.weather-secondary { border: 1px solid var(--border-default); background: var(--bg-surface-elevated); color: var(--text-primary); }
button:disabled, select:disabled, input:disabled { opacity: 0.55; cursor: not-allowed; }
.weather-notice { color: var(--success); font-size: 13px; margin-top: 10px; }
.weather-test-label { margin-top: 18px; margin-bottom: 7px; }
.weather-test-output { margin-top: 16px; padding: 12px; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); background: var(--bg-surface-elevated); }
.weather-result-summary { margin: 0 0 6px; font-size: 13px; }
.weather-result-text { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.55; white-space: pre-wrap; }
@media (max-width: 900px) { .weather-layout { grid-template-columns: 1fr; } }
@media (max-width: 540px) { .weather-card { padding: 16px; } .weather-heading, .weather-toggle-row { align-items: flex-start; flex-direction: column; } }
</style>
