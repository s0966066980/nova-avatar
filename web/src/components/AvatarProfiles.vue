<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <div class="role-settings" :aria-busy="busy">
    <header class="role-top">
      <div><h2>數位人設定檔與角色交接</h2><p>分別保存每位角色的身分、知識範圍與聲音。儲存後，套用至舞台與控制台。</p></div>
      <div class="role-actions"><button type="button" @click="load" :disabled="busy">重新載入</button><button type="submit" form="role-library-form" :disabled="busy || !draft">儲存設定</button><button type="button" class="primary" :disabled="busy || dirty || !draft" @click="apply">{{ busy ? '處理中…' : '套用已儲存設定' }}</button></div>
    </header>
    <p v-if="error" class="role-error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p class="role-status">{{ roleRuntime.enabled ? '角色交接已啟用' : '使用單角色模式' }} · {{ rolePhaseLabel(roleRuntime.phase) }} · {{ roleRuntime.weather_configured ? 'CWA 已設定' : 'CWA 尚未設定授權碼' }} <span v-if="dirty">· 有尚未儲存的修改</span></p>
    <p v-if="roleRuntime.error" class="role-error" role="alert">{{ roleRuntime.error }}</p>
    <form v-if="draft" id="role-library-form" @submit.prevent="save">
      <fieldset :disabled="busy">
        <section class="role-card">
          <h3>當次角色組合</h3>
          <label class="check"><input type="checkbox" v-model="draft.enabled">啟用即時角色交接</label>
          <div class="role-grid"><label>主數位人<select v-model="draft.pair.main"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label><label>專門數位人<select v-model="draft.pair.specialist"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label></div>
          <p>首版組合共用 MuseTalk 推理與同一 LLM 服務、模型；每位角色保留自己的 Prompt、RAG、聲線及訪客記憶。</p>
        </section>
        <section class="role-card">
          <div class="role-actions"><h3>角色設定檔</h3><button type="button" @click="cloneProfile">複製為新設定檔</button><button type="button" :disabled="draft.profiles.length <= 2 || inPair(selected)" @click="removeProfile">刪除設定檔</button></div>
          <label>正在編輯<select v-model="selected"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}（{{ p.id }}）</option></select></label>
          <template v-if="profile">
            <div class="role-grid"><label>顯示名稱<input v-model="profile.name" required maxlength="80"></label><label>人物素材<select v-model="profile.avatar_id"><option v-for="a in avatars" :key="a.id" :value="a.id">{{ a.label || a.name || a.id }}</option><option v-if="!avatars.some(a => a.id === profile.avatar_id)" :value="profile.avatar_id">{{ profile.avatar_id }}</option></select></label></div>
            <div class="role-grid"><label>推理引擎<select v-model="profile.engine"><option value="musetalk">MuseTalk</option><option value="wav2lip">Wav2Lip · Research / Non-commercial（不可用於即時組合）</option></select></label><label>助手自稱<input v-model="profile.assistant_profile.assistant_name" maxlength="200"></label></div>
            <label>身分 Prompt<textarea v-model="profile.assistant_profile.system_prompt" rows="4" maxlength="12000"></textarea></label>
            <label>限制 Prompt<textarea v-model="profile.assistant_profile.restriction_prompt" rows="3" maxlength="12000"></textarea></label>
            <div class="role-grid"><label>輸出語系<select v-model="profile.assistant_profile.output_locale"><option value="zh-TW">繁體中文（臺灣）</option><option value="zh-CN">簡體中文</option><option value="en">英文</option><option value="auto">自動</option></select></label><label>禁止自稱名稱（逗號分隔）<input :value="profile.assistant_profile.forbidden_self_names.join(', ')" @change="profile.assistant_profile.forbidden_self_names = $event.target.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)"></label></div>
            <label class="check"><input type="checkbox" v-model="profile.assistant_profile.enforce_output_locale">限制輸出語系</label>
            <h4>回答模型</h4>
            <div class="role-grid"><label>服務<select v-model="profile.llm.provider"><option value="llamacpp">llama.cpp</option><option value="ollama">Ollama</option><option value="openai">OpenAI 相容服務</option></select></label><label>模型<input v-model="profile.llm.model" required list="role-models"></label></div>
            <datalist id="role-models"><option v-for="m in models" :key="m" :value="m"></option></datalist>
            <label>服務網址<input v-model="profile.llm.base_url" type="url" placeholder="http://127.0.0.1:8080/v1"></label>
            <div class="role-grid"><label>口語字數上限<input type="number" v-model.number="profile.llm.response_max_chars" min="20" max="2000"></label><label>模型 Token 預算<input type="number" v-model.number="profile.llm.max_tokens" min="16" max="8192"></label></div>
            <h4>知識範圍</h4><label class="check"><input type="checkbox" v-model="profile.rag.enabled">啟用此角色的 RAG</label>
            <button type="button" @click="loadDatasets">讀取知識庫清單</button>
            <label v-for="d in datasets" :key="d.id" class="check"><input type="checkbox" :value="d.id" v-model="profile.rag.dataset_ids">{{ d.name || d.id }}</label>
            <label>已選知識庫 ID（逗號分隔）<input :value="profile.rag.dataset_ids.join(', ')" @change="profile.rag.dataset_ids = $event.target.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)"></label>
            <h4>聲音與回覆規則</h4>
            <div class="role-grid"><label>語音引擎<input v-model="profile.tts.type" required></label><label>聲線／參考音檔<input v-model="profile.tts.ref_file" placeholder="zh-TW-HsiaoChenNeural"></label></div>
            <details><summary>其他聲音設定</summary><label v-for="key in ['mode','ref_text','tts_server','model','language','speaker','instruct','device']" :key="key">{{ key }}<input :value="profile.tts[key] || ''" @input="profile.tts[key] = $event.target.value"></label></details>
            <label v-for="(title,key) in ruleTitles" :key="key">{{ title }}<textarea v-model="profile.reply_rules[key]" rows="3" maxlength="12000"></textarea></label>
            <label class="check"><input type="checkbox" v-model="profile.tools.weather">使用 CWA 即時天氣工具（臺灣）</label>
          </template>
        </section>
        <section class="role-card"><h3>主數位人的交接規則</h3>
          <label>專門角色的專長介紹<textarea v-model="draft.handoff.description" rows="2" required maxlength="2000"></textarea></label>
          <label>何時交接<textarea v-model="draft.handoff.rules" rows="3" required maxlength="12000"></textarea></label>
          <label>交接說明（播完後才轉場）<textarea v-model="draft.handoff.announcement" rows="2" required maxlength="2000"></textarea></label>
          <h4>場域預設查詢地點</h4><p>留白時會向訪客確認縣市與鄉鎮，不會猜測地點。</p>
          <div class="role-grid"><label>縣市<input v-model="draft.weather.county" placeholder="臺北市"></label><label>鄉鎮市區<input v-model="draft.weather.town" placeholder="中正區"></label></div>
          <p>氣象資料來源：<a href="https://opendata.cwa.gov.tw/" target="_blank" rel="noopener">交通部中央氣象署</a>。授權碼僅在服務端設定。</p>
        </section>
        <section class="role-card"><h3>指定方向的角色轉場</h3><p>去程與回程可各自設定。自訂影片會移除音軌，長寬比例保留，空白處沿用舞台背景。</p>
          <div class="role-grid"><label>來源<select v-model="edgeSource"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label><label>目的<select v-model="edgeTarget"><option v-for="p in draft.profiles" :key="p.id" :value="p.id">{{ p.name }}</option></select></label></div>
          <template v-if="edgeSource && edgeTarget && edgeSource !== edgeTarget">
            <label>轉場類型<select v-model="edge.kind"><option value="effect">內建特效</option><option value="video">自訂影片</option></select></label>
            <div v-if="edge.kind === 'effect'" class="role-grid"><label>特效<select v-model="edge.effect"><option value="fade">淡入淡出</option><option value="slide_left">向左滑動</option><option value="slide_right">向右滑動</option><option value="zoom">縮放</option></select></label><label>時長（秒）<input type="number" v-model.number="edge.duration" min="0.2" max="2" step="0.1"></label></div>
            <template v-else><label>轉場影片<select v-model="edge.asset_id"><option value="">請選擇影片</option><option v-for="m in media" :key="m.id" :value="m.id">{{ m.name }} · {{ m.duration.toFixed(2) }} 秒</option></select></label><video v-if="edge.asset_id" :src="`/api/profiles/media/${edge.asset_id}`" controls muted playsinline class="role-video"></video></template>
          </template>
          <label>上傳轉場影片（MP4／MOV／WebM，100 MiB、30 秒內）<input type="file" accept=".mp4,.mov,.webm" @change="upload"></label>
          <details><summary>管理轉場影片（{{ media.length }}）</summary><div v-for="m in media" :key="m.id" class="role-actions"><span>{{ m.name }}</span><button type="button" @click="deleteMedia(m.id)">刪除影片</button></div></details>
        </section>
      </fieldset>
    </form>
  </div>
</template>

<script setup>
import {ref, computed, onMounted, toRaw} from 'vue'
import {useRoles} from '../composables/useRoles.js'
import {useRuntimeSettings} from '../composables/useRuntimeSettings.js'
import {directedTransition, rolePhaseLabel} from '../roleState.js'
const {roleRuntime, roleRequest} = useRoles()
const {runtime} = useRuntimeSettings()
const draft=ref(null), selected=ref(''), media=ref([]), datasets=ref([]), models=ref([])
const busy=ref(false), error=ref(''), notice=ref(''), savedText=ref(''), edgeSource=ref(''), edgeTarget=ref('')
const ruleTitles={activation:'何時使用看板', speech:'口語回覆規則', board:'看板呈現規則'}
const dirty=computed(()=>draft.value && JSON.stringify(draft.value)!==savedText.value)
const profile=computed(()=>draft.value?.profiles.find(p=>p.id===selected.value))
const avatars=computed(()=>runtime.characters.filter(a=>!a.type || a.type==='musetalk'))
const edge=computed(()=>directedTransition(draft.value,edgeSource.value,edgeTarget.value))
const inPair=id=>Object.values(draft.value.pair).includes(id)
async function perform(action) { busy.value=true; error.value=''; notice.value=''; try {await action()} catch(e) {error.value=e.message} finally {busy.value=false} }
function adopt(data) {draft.value=structuredClone(data.library); selected.value=draft.value.profiles.some(p=>p.id===selected.value)?selected.value:draft.value.pair.main; edgeSource.value=draft.value.pair.main; edgeTarget.value=draft.value.pair.specialist; directedTransition(draft.value,edgeSource.value,edgeTarget.value); savedText.value=JSON.stringify(draft.value); if(data.media)media.value=data.media}
const load=()=>perform(async()=>{adopt(await roleRequest()); try {const r=await fetch('/api/llm/models'); const j=await r.json(); models.value=(j.data?.models||[]).map(m=>typeof m==='string'?m:m.id||m.name)}catch(_){}})
const save=()=>perform(async()=>{if(draft.value.pair.main===draft.value.pair.specialist)throw Error('主角色與專門角色需選擇不同設定檔');adopt(await roleRequest('','PUT',{library:draft.value,expected_revision:draft.value.revision}));notice.value='設定已儲存，請套用以更新演播。'})
const apply=()=>perform(async()=>{await roleRequest('/apply','POST');notice.value=roleRuntime.enabled?'設定已套用，演播回到主數位人。':'已套用單角色模式。'})
function cloneProfile(){const p=structuredClone(toRaw(profile.value));p.id='role_'+crypto.randomUUID().replaceAll('-','').slice(0,12);p.name+=' 副本';draft.value.profiles.push(p);selected.value=p.id}
function removeProfile(){draft.value.transitions=draft.value.transitions.filter(e=>e.source!==selected.value&&e.target!==selected.value);draft.value.profiles=draft.value.profiles.filter(p=>p.id!==selected.value);selected.value=draft.value.pair.main}
const loadDatasets=()=>perform(async()=>{const r=await fetch('/api/ragflow/datasets');const j=await r.json();if(!r.ok)throw Error(j.msg||'無法讀取知識庫');datasets.value=j.data.datasets||[]})
const upload=event=>perform(async()=>{const f=event.target.files[0];if(!f)return;if(f.size>100*1024*1024)throw Error('影片不可超過 100 MiB');const body=new FormData();body.append('file',f);const data=await roleRequest('/media','POST',body);media.value=data.media;if(edgeSource.value!==edgeTarget.value){edge.value.kind='video';edge.value.asset_id=data.asset.id;}event.target.value='';notice.value='影片已驗證並轉為無聲轉場，請儲存設定。'})
const deleteMedia=id=>perform(async()=>{const data=await roleRequest('/media/'+id,'DELETE');media.value=data.media})
onMounted(load)
</script>

<style scoped>
.role-settings{color:var(--text-primary);width:100%;max-width:1400px;margin:auto;padding:8px}.role-top,.role-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:space-between}.role-top h2{font-size:22px}.role-top p,.role-card p,.role-status{font-size:13px;color:var(--text-secondary);line-height:1.7}.role-card{padding:24px;border:1px solid var(--border);border-radius:16px;background:var(--bg-surface);margin:18px 0}.role-card h3{font-size:17px;margin:0 0 14px}.role-card h4{font-size:14px;margin:20px 0 12px}.role-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.role-settings label{display:flex;flex-direction:column;gap:8px;font-size:13px;margin:14px 0}.role-settings .check{flex-direction:row;align-items:center}.role-settings input,.role-settings select,.role-settings textarea{background:var(--input-surface);color:var(--text-primary);border:1px solid var(--border);padding:10px 12px;border-radius:8px;width:100%;font:inherit}.role-settings .check input{width:auto}.role-settings textarea{resize:vertical;min-height:70px}.role-settings button{padding:10px 14px;border:1px solid var(--border);border-radius:8px;color:var(--text-primary);background:var(--bg-surface-elevated);font-size:13px;cursor:pointer}.role-settings button.primary{background:var(--brand,#7859d7);color:white}.role-settings button:disabled{opacity:.45;cursor:default}.role-settings :focus-visible{outline:2px solid #a893ff;outline-offset:3px}.role-settings fieldset{border:0;padding:0;min-width:0}.role-error{color:var(--danger);background:var(--danger-surface);padding:12px;border-radius:8px}.role-video{max-width:100%;height:220px;background:#111;margin-top:12px}.role-settings summary{cursor:pointer;padding:10px 0}@media(max-width:700px){.role-grid{grid-template-columns:1fr}.role-card{padding:16px}}
</style>
