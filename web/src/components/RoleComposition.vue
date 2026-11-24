<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<!-- 角色組合與交接：左側成員名單、中間所選成員的設定、右側交接路線與角色轉場（ADR 0023）。
     主數位人、每位專門數位人與角色轉場各自儲存；版本衝突只影響那一份。 -->
<template>
  <div class="role-compose" :aria-busy="!library">
    <div v-if="loadError" class="rc-banner danger" role="alert">
      <i class="bi bi-exclamation-octagon" aria-hidden="true"></i>
      <div><b>無法讀取角色組合</b><div class="rc-detail">{{ loadError }}</div></div>
      <button type="button" class="rc-btn sm" @click="load">重新載入</button>
    </div>
    <p v-else-if="!library" class="rc-hint" role="status">正在載入當次角色組合…</p>
    <template v-if="library && scopes">
      <div class="rc-bar">
        <label for="rc-main-select"><i class="bi bi-house-door" aria-hidden="true"></i>主數位人</label>
        <select id="rc-main-select" ref="mainSelect" class="rc-input" :value="mainId" :disabled="structureBusy" @change="changeMain($event.target.value)">
          <option v-for="p in library.profiles" :key="p.id" :value="p.id" :disabled="memberIds.includes(p.id)">{{ p.name }}{{ memberIds.includes(p.id) ? '（已是專門數位人）' : '' }}</option>
        </select>
        <span class="rc-count">已啟用 <span class="num">{{ enabled }}</span>／{{ MAX_ENABLED }}</span>
        <span class="rc-meta rc-wide">共用：{{ ttsLabel(mainProfile) }} · {{ llmLabel(mainProfile) }}</span>
        <button v-if="dirtyKeys.length" type="button" class="rc-chip warn" @click="select(dirtyKeys[0])">
          <i class="bi bi-exclamation-triangle" aria-hidden="true"></i>{{ dirtyKeys.length }} 處未儲存：{{ dirtyKeys.map(labelOf).join('、') }}
        </button>
        <span class="rc-spacer"></span>
        <span class="rc-meta" role="status">{{ applyText }}</span>
        <button v-if="pendingApply" type="button" class="rc-btn sm" :disabled="applying" @click="applyNow"><i class="bi bi-play-circle" aria-hidden="true"></i>{{ applying ? '套用中…' : '套用組合' }}</button>
        <button type="button" class="rc-btn sm primary" :disabled="!candidates.length || memberCount >= MAX_MEMBERS" :title="addTitle" @click="select('add')"><i class="bi bi-plus-lg" aria-hidden="true"></i>加入專門數位人</button>
      </div>
      <p v-if="barError" class="rc-banner danger rc-bar-error" role="alert"><i class="bi bi-exclamation-octagon" aria-hidden="true"></i><span>{{ barError }}</span><button type="button" class="rc-btn sm ghost" aria-label="關閉訊息" @click="barError = ''"><i class="bi bi-x-lg" aria-hidden="true"></i></button></p>

      <div class="rc-work">
        <!-- 成員名單 -->
        <article class="rc-card rc-list-card" aria-labelledby="rc-list-title">
          <div class="rc-card-head"><div><h3 id="rc-list-title"><i class="bi bi-people" aria-hidden="true"></i>當次角色組合</h3><p>點選一位，在右側編輯並單獨儲存。</p></div></div>
          <div class="rc-card-body">
            <div class="rc-slot-group">主數位人</div>
            <ul class="rc-slots" aria-label="主數位人">
              <li><button type="button" class="rc-slot" :aria-current="selected === 'main' ? 'true' : undefined" @click="select('main')">
                <span class="rc-av" :style="{ background: colorOf(mainId) }" aria-hidden="true">{{ initialOf(mainId) }}</span>
                <span class="rc-slot-text"><span class="rc-top"><b>{{ nameOf(mainId) }}</b><span v-if="dirty(scopes.main)" class="rc-mini dirty">未儲存</span><span v-else class="rc-mini main">開場／兜底</span></span>
                  <span class="rc-sub"><small>相容基準：{{ ttsLabel(mainProfile) }} · {{ mainProfile?.llm?.model }}</small></span></span>
              </button></li>
            </ul>
            <div class="rc-slot-group"><span>專門數位人</span><span class="num">啟用 {{ enabled }}／{{ MAX_ENABLED }}</span></div>
            <ul class="rc-slots" aria-label="專門數位人">
              <li v-for="row in rows" :key="row.key">
                <button v-if="row.empty" type="button" class="rc-slot empty" :aria-current="selected === 'add' && row.first ? 'true' : undefined" @click="select('add')">
                  <span class="rc-av" aria-hidden="true"><i class="bi bi-plus-lg"></i></span>
                  <span class="rc-slot-text"><b>空位 {{ row.seat }}</b><span class="rc-sub"><small>加入專門數位人</small></span></span>
                </button>
                <button v-else type="button" class="rc-slot" :aria-current="selected === row.key ? 'true' : undefined" @click="select(row.key)">
                  <span :class="['rc-av', row.avatarState]" :style="{ background: row.avatarState ? undefined : colorOf(row.id) }" aria-hidden="true">{{ initialOf(row.id) }}</span>
                  <span class="rc-slot-text">
                    <span class="rc-top"><b>{{ nameOf(row.id) }}</b><span v-if="row.dirty" class="rc-mini dirty">未儲存</span></span>
                    <span class="rc-sub"><span :class="['rc-chip', row.chip.tone]"><i v-if="row.chip.icon" :class="row.chip.icon" aria-hidden="true"></i><span v-else class="rc-dot" aria-hidden="true"></span>{{ row.chip.text }}</span>
                      <span v-if="row.weather" class="rc-mini tool"><i class="bi bi-cloud-sun" aria-hidden="true"></i> 天氣</span><small>{{ ttsLabel(profileOf(row.id)) }}</small></span>
                    <span v-if="row.reasons.length" class="rc-why">{{ row.reasons.join('；') }}</span>
                  </span>
                </button>
              </li>
            </ul>
            <p class="rc-hint">任一位可直接交給任一位（含主數位人）。組合成員共用同一套語音合成引擎與回答模型服務；不相容者保留設定但無法啟用。</p>
          </div>
        </article>

        <!-- 所選成員 -->
        <article class="rc-card rc-editor" aria-live="off" aria-label="所選成員的設定">
          <!-- 主數位人 -->
          <template v-if="selected === 'main'">
            <div class="rc-ed-head">
              <div class="rc-who"><span class="rc-av lg" :style="{ background: colorOf(mainId) }" aria-hidden="true">{{ initialOf(mainId) }}</span>
                <div><h3>{{ nameOf(mainId) }}<span class="rc-mini main">主數位人 · 開場／兜底</span></h3><p>設定檔 <span class="mono">{{ mainId }}</span> · 在上方「主數位人」更換</p></div></div>
              <div class="rc-acts"><RoleSaveState :scope="scopes.main" /><button type="button" class="rc-btn sm ghost" :disabled="!dirty(scopes.main) || scopes.main.status === 'saving'" @click="revert('main')"><i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>還原</button><button type="button" class="rc-btn sm primary" :disabled="!dirty(scopes.main) || scopes.main.status === 'saving'" @click="save('main')"><i class="bi bi-check-lg" aria-hidden="true"></i>儲存這位</button></div>
            </div>
            <div class="rc-ed-alerts">
              <div v-if="!scopes.main.draft.enabled" class="rc-banner warn"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i><div><b>角色交接已關閉</b><div class="rc-detail">只有{{ nameOf(mainId) }}回答訪客；其他角色保留設定但不接手。</div></div></div>
              <RoleScopeError :scope="scopes.main" :name="nameOf(mainId)" @use-latest="useLatest('main')" @overwrite="overwrite('main')" @reload="load" />
            </div>
            <div class="rc-ed-body">
              <div class="rc-col">
                <RoleHandoffFields v-model="scopes.main.draft" :name="nameOf(mainId)" prefix="rc-main" main :error="fieldError(scopes.main, 'announcement')" />
                <div class="rc-section-title"><i class="bi bi-info-circle" aria-hidden="true"></i>何時交接</div>
                <ul class="rc-info-list">
                  <li><i class="bi bi-chat-left-text" aria-hidden="true"></i><span><b>追問留在目前的角色</b>：延續上一題的追問（例如「那後天呢？」）由正在回答的角色繼續。</span></li>
                  <li><i class="bi bi-arrow-right" aria-hidden="true"></i><span><b>明確換了主題才交接</b>：每一輪都考量所有已啟用的角色（含{{ nameOf(mainId) }}），直接交給最適合的一位，不必先回到{{ nameOf(mainId) }}。</span></li>
                  <li><i class="bi bi-exclamation-triangle" aria-hidden="true"></i><span><b>主題混雜時先問訪客</b>：同時涉及多位角色又無法判斷時，先請訪客確認優先主題。</span></li>
                </ul>
              </div>
              <div class="rc-col">
                <div class="rc-block">
                  <div class="rc-block-head"><span class="rc-sub-title"><i class="bi bi-share" aria-hidden="true"></i>角色交接</span>
                    <label class="rc-switch"><input id="rc-handoff" v-model="scopes.main.draft.enabled" type="checkbox"><span class="rc-state">{{ scopes.main.draft.enabled ? '啟用角色交接' : '角色交接已關閉' }}</span></label></div>
                  <p class="rc-hint">關閉後只由{{ nameOf(mainId) }}回答，等同單角色模式；各角色的設定都保留，重新開啟即恢復。</p>
                </div>
                <div class="rc-block"><div class="rc-sub-title"><i class="bi bi-house-door" aria-hidden="true"></i>開場／兜底</div>
                  <ul class="rc-info-list">
                    <li><i class="bi bi-chat-left-text" aria-hidden="true"></i><span>每場對話由<b>{{ nameOf(mainId) }}</b>開場。</span></li>
                    <li><i class="bi bi-arrow-left" aria-hidden="true"></i><span><b>反向角色交接</b>：問題不屬於組合中任何一位專門數位人時，自動交回{{ nameOf(mainId) }}接續回答原問題。</span></li>
                    <li><i class="bi bi-arrow-left" aria-hidden="true"></i><span>訪客選擇返回，或訪客對話重置時，回到{{ nameOf(mainId) }}。</span></li>
                  </ul></div>
                <div class="rc-block"><div class="rc-sub-title"><i class="bi bi-lock" aria-hidden="true"></i>組合共用服務（相容基準）</div>
                  <dl class="rc-kv"><dt>語音合成引擎</dt><dd>{{ ttsLabel(mainProfile) }}</dd><dt>回答模型服務</dt><dd class="mono">{{ llmLabel(mainProfile) }}</dd><dt>唇形引擎</dt><dd>{{ engineLabel(mainProfile) }}</dd></dl>
                  <p class="rc-hint">專門數位人必須與這三項相同才能啟用。要改基準，請到「數位人設定檔」修改{{ nameOf(mainId) }}。</p></div>
                <div class="rc-block"><div class="rc-sub-title"><i class="bi bi-soundwave" aria-hidden="true"></i>預設聲音</div>
                  <p class="rc-hint rc-strong">尚未套用任何數位人設定檔時，數位人也使用{{ nameOf(mainId) }}的聲音：<span class="mono">{{ voiceLabel(mainProfile) }}</span>。</p>
                  <button type="button" class="rc-btn link" @click="$emit('edit-profile', mainId, 'voice')">到數位人設定檔編輯聲音</button></div>
                <div class="rc-note"><i class="bi bi-chat-heart" aria-hidden="true"></i><span>閒置招呼只由主數位人播放；內容在「閒置招呼」頁設定。</span></div>
              </div>
            </div>
          </template>

          <!-- 空位：選設定檔加入 -->
          <template v-else-if="selected === 'add'">
            <div class="rc-ed-head"><div class="rc-who"><span class="rc-av lg rc-av-empty" aria-hidden="true"><i class="bi bi-plus-lg"></i></span><div><h3>加入專門數位人</h3><p>選一份數位人設定檔加入當次角色組合</p></div></div></div>
            <div class="rc-ed-alerts"></div>
            <div class="rc-col rc-single">
              <div v-for="p in candidates" :key="p.id" class="rc-cand">
                <span class="rc-av" :style="{ background: colorOf(p.id) }" aria-hidden="true">{{ initialOf(p.id) }}</span>
                <div><b>{{ p.name }}</b><small>{{ ttsLabel(p) }} · {{ llmLabel(p) }}</small>
                  <div v-if="reasonsOf(p.id).length" class="rc-field-error"><i class="bi bi-x-circle" aria-hidden="true"></i>{{ reasonsOf(p.id).join('；') }}</div></div>
                <button type="button" :class="['rc-btn', 'sm', { primary: !reasonsOf(p.id).length }]" @click="addCandidate(p.id)"><i class="bi bi-plus-lg" aria-hidden="true"></i>加入{{ reasonsOf(p.id).length ? '（無法啟用）' : '' }}</button>
              </div>
              <p v-if="!candidates.length" class="rc-hint">所有設定檔都已在組合中。先到「數位人設定檔」複製一份。</p>
              <p class="rc-hint">加入後預設為未啟用；填好交接規則與交接說明並按「儲存這位」，再開啟啟用。</p>
            </div>
          </template>

          <!-- 專門數位人 -->
          <template v-else-if="current">
            <div class="rc-ed-head">
              <div class="rc-who"><span :class="['rc-av', 'lg', memberAvatarState(current)]" :style="{ background: memberAvatarState(current) ? undefined : colorOf(current.draft.profile_id) }" aria-hidden="true">{{ initialOf(current.draft.profile_id) }}</span>
                <div><h3>{{ nameOf(current.draft.profile_id) }}<span class="rc-mini">專門 #{{ seatOf(selected) }}</span></h3><p>設定檔 <span class="mono">{{ current.draft.profile_id }}</span> · {{ voiceLabel(profileOf(current.draft.profile_id)) }}</p></div></div>
              <div class="rc-acts"><RoleSaveState :scope="current" /><button type="button" class="rc-btn sm ghost" :disabled="current.kind === 'new' || !dirty(current) || current.status === 'saving'" @click="revert(selected)"><i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>還原</button><button type="button" class="rc-btn sm primary" :disabled="!dirty(current) || current.status === 'saving'" @click="save(selected)"><i class="bi bi-check-lg" aria-hidden="true"></i>儲存這位</button></div>
            </div>
            <div class="rc-ed-alerts">
              <div v-if="currentReasons.length" class="rc-banner danger"><i class="bi bi-exclamation-octagon" aria-hidden="true"></i><div><b>無法啟用：與主數位人不相容</b><div class="rc-detail">{{ currentReasons.join('；') }}。設定仍可編輯與儲存，但不參與交接。</div></div><button type="button" class="rc-btn sm" @click="$emit('edit-profile', current.draft.profile_id, 'voice')">修改設定檔</button></div>
              <div v-else-if="current.kind === 'new'" class="rc-banner info"><i class="bi bi-info-circle" aria-hidden="true"></i><div><b>新加入，尚未儲存</b><div class="rc-detail">按「儲存這位」後才會出現在交接路線中。</div></div><button type="button" class="rc-btn sm ghost" @click="discardNew(selected)">取消加入</button></div>
              <div v-if="current.missing" class="rc-banner warn"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i><div><b>這位已被其他控制台移出組合</b><div class="rc-detail">你的草稿仍保留；要保留這位，請重新加入。</div></div></div>
              <RoleScopeError :scope="current" :name="nameOf(current.draft.profile_id)" @use-latest="useLatest(selected)" @overwrite="overwrite(selected)" @reload="load" />
            </div>
            <div class="rc-ed-body">
              <div class="rc-col">
                <RoleHandoffFields v-model="current.draft" :name="nameOf(current.draft.profile_id)" :prefix="`rc-${selected.replace(':', '-')}`" :error="fieldError(current, 'announcement')" />
                <p class="rc-hint">專長內的追問留在這位；不屬於任何角色的問題自動交回{{ nameOf(mainId) }}（反向角色交接）。</p>
              </div>
              <div class="rc-col">
                <div class="rc-block">
                  <div class="rc-block-head"><span class="rc-sub-title">啟用與相容</span>
                    <label class="rc-switch"><input id="rc-member-enabled" v-model="current.draft.enabled" type="checkbox" :disabled="enableLocked" :aria-describedby="enableHint ? 'rc-enable-hint' : undefined"><span class="rc-state">{{ enabledLabel }}</span></label></div>
                  <span v-if="enableHint" id="rc-enable-hint" :class="['rc-hint', { 'rc-danger-text': currentReasons.length || fieldError(current, 'enabled') }]">{{ enableHint }}</span>
                  <div class="rc-field"><label for="rc-member-profile">使用的數位人設定檔</label>
                    <select id="rc-member-profile" v-model="current.draft.profile_id" class="rc-input" :aria-invalid="Boolean(fieldError(current, 'profile_id'))">
                      <option v-for="p in profileChoices" :key="p.id" :value="p.id">{{ p.name }}</option></select>
                    <span v-if="fieldError(current, 'profile_id')" class="rc-field-error">{{ fieldError(current, 'profile_id') }}</span></div>
                  <ul class="rc-compat" aria-label="與主數位人的相容性">
                    <li v-for="row in compatRows" :key="row.label" :class="row.ok ? 'ok' : 'bad'"><i :class="row.ok ? 'bi bi-check-circle' : 'bi bi-x-circle'" aria-hidden="true"></i><div><b>{{ row.label }}</b> <span>{{ row.text }}</span></div></li>
                  </ul>
                </div>
                <div class="rc-block">
                  <span class="rc-sub-title"><i class="bi bi-cloud-sun" aria-hidden="true"></i>工具</span>
                  <label class="rc-check"><input id="rc-member-weather" v-model="current.draft.tools.weather.enabled" type="checkbox" :disabled="weatherLocked" :aria-describedby="weatherLocked ? 'rc-weather-lock' : undefined">
                    <span class="rc-ct"><b>CWA 天氣查詢</b><span class="rc-hint">中央氣象署開放資料 · {{ roleRuntime.weather_configured ? '授權碼已設定' : '授權碼尚未設定（僅能在服務端設定）' }}</span></span></label>
                  <span v-if="fieldError(current, 'tools.weather.enabled')" class="rc-field-error"><i class="bi bi-exclamation-triangle" aria-hidden="true"></i>{{ fieldError(current, 'tools.weather.enabled') }}</span>
                  <div v-if="weatherLocked" id="rc-weather-lock" class="rc-note lock"><i class="bi bi-lock" aria-hidden="true"></i><span>天氣工具目前由「{{ nameOf(holder) }}」提供，一個組合同時只限一位。要改給這位，請先在{{ nameOf(holder) }}取消並儲存。
                    <button type="button" class="rc-btn link" @click="select(`m:${holder}`)">前往{{ nameOf(holder) }}</button></span></div>
                  <div v-else-if="current.draft.tools.weather.enabled" class="rc-field"><span class="rc-l"><i class="bi bi-geo-alt" aria-hidden="true"></i> 場域預設地點</span>
                    <div class="rc-grid-2">
                      <div class="rc-field"><label for="rc-weather-county" class="rc-hint">縣市</label><input id="rc-weather-county" v-model="current.draft.tools.weather.county" class="rc-input" maxlength="80" placeholder="例：臺北市"></div>
                      <div class="rc-field"><label for="rc-weather-town" class="rc-hint">鄉鎮市區</label><input id="rc-weather-town" v-model="current.draft.tools.weather.town" class="rc-input" maxlength="80" placeholder="例：信義區"></div>
                    </div>
                    <span class="rc-hint">訪客沒說地點時查這裡；訪客臨時指定的地點只屬於該場對話。留白時會先向訪客確認。氣象資料來源：交通部中央氣象署。</span></div>
                  <span v-else class="rc-hint">{{ holder ? '' : '組合中目前沒有人提供天氣查詢。勾選後由這位負責，其他位會鎖定。' }}</span>
                </div>
                <div class="rc-note"><i class="bi bi-film" aria-hidden="true"></i><span>交給或離開{{ nameOf(current.draft.profile_id) }}時的視覺銜接，在右側「角色轉場」統一設定。</span></div>
                <button v-if="current.kind === 'member'" type="button" class="rc-btn sm danger rc-self-start" :disabled="structureBusy" @click="removeMember(selected)"><i class="bi bi-person-x" aria-hidden="true"></i>移出組合</button>
              </div>
            </div>
          </template>
        </article>

        <!-- 交接路線、交接試算、角色轉場 -->
        <div class="rc-aside">
          <article class="rc-card rc-topo-card" aria-labelledby="rc-topo-title">
            <div class="rc-card-head"><div><h3 id="rc-topo-title"><i class="bi bi-share" aria-hidden="true"></i>交接路線</h3><p>任一位可直接交給任一位；點節點可編輯。</p></div></div>
            <div class="rc-topo-wrap">
              <RoleTopology :nodes="topologyNodes" :live="liveKeys" :description="topologyDescription" @select="select" />
              <div class="rc-legend" aria-hidden="true"><span><i class="e"></i>可直接交接</span><span><i class="o"></i>未啟用</span><span><i class="x"></i>不相容</span></div>
              <!-- 交接試算：以已儲存的組合實際詢問路由；不播報，也不寫入對話。 -->
              <form id="rc-dry-run" class="rc-sim" aria-labelledby="rc-sim-title" aria-describedby="rc-sim-hint" @submit.prevent="dryRun">
                <span id="rc-sim-title" class="rc-sub-title"><i class="bi bi-chat-left-text" aria-hidden="true"></i>交接試算<span v-if="library" class="rc-mini">已儲存版本 {{ library.revision }}</span></span>
                <div class="rc-sim-row">
                  <div class="rc-field"><label for="rc-sim-from">目前角色</label>
                    <select id="rc-sim-from" v-model="sim.from" class="rc-input" :disabled="!simReady || sim.busy"><option v-for="id in liveKeysById" :key="id" :value="id">{{ nameOf(id) }}</option></select></div>
                  <div class="rc-field"><label for="rc-sim-question">訪客問題</label><input id="rc-sim-question" v-model="sim.text" class="rc-input" maxlength="500" :disabled="!simReady || sim.busy" placeholder="例：捷運怎麼去？"></div>
                </div>
                <button type="submit" class="rc-btn sm rc-self-start" :disabled="!simReady || sim.busy || !sim.text.trim()"><i class="bi bi-signpost-split" aria-hidden="true"></i>{{ sim.busy ? '試算中…' : '試算由誰回答' }}</button>
                <div v-if="sim.result" class="rc-sim-result" role="status">
                  <b v-if="sim.result.target === null">先向訪客釐清：{{ sim.result.clarification }}</b>
                  <b v-else-if="sim.result.handoff">交給{{ sim.result.target_name }}</b>
                  <b v-else>留在{{ sim.result.target_name }}回答</b>
                  <span class="rc-hint">{{ sim.result.reason || '模型未提供原因' }}（{{ sim.result.decided_by === 'keyword' ? '關鍵字初篩' : '模型判斷' }}）</span>
                </div>
                <p v-if="sim.error" class="rc-hint rc-sim-error" role="alert">{{ sim.error }}</p>
                <p id="rc-sim-hint" class="rc-hint">{{ simHint }}</p>
              </form>
            </div>
          </article>
          <RoleTransitions v-model:scope="scopes.transitions" v-model:media="media" :members="transitionMembers" :live="liveKeysById" :names="names"
            @save="save('transitions')" @revert="revert('transitions')" @use-latest="useLatest('transitions')" @overwrite="overwrite('transitions')" />
        </div>
      </div>
    </template>

    <div v-if="dialog" class="rc-scrim" @click.self="answer(false)">
      <div class="rc-dialog" role="alertdialog" aria-modal="true" aria-labelledby="rc-dialog-title" aria-describedby="rc-dialog-text" @keydown.esc="answer(false)">
        <div class="rc-dialog-body"><h3 id="rc-dialog-title">{{ dialog.title }}</h3><div id="rc-dialog-text"><p v-for="line in dialog.lines" :key="line">{{ line }}</p></div></div>
        <div class="rc-dialog-acts"><button type="button" class="rc-btn ghost" @click="answer(false)">取消</button><button ref="dialogOk" type="button" :class="['rc-btn', dialog.danger ? 'danger-solid' : 'primary']" @click="answer(true)">{{ dialog.ok }}</button></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, h, nextTick, onMounted, ref, shallowRef, toRaw, watch } from 'vue'
import { useRoles } from '../composables/useRoles.js'
import { useRuntimeSettings } from '../composables/useRuntimeSettings.js'
import { missingVoiceModelLabel, voiceModelLabel } from '../voiceSelection.js'
import {
  MAX_ENABLED, MAX_MEMBERS, avatarColor, enabledCount, isDirty, liveMemberIds, newMemberScope, readFailure, rebase,
  reconcile, savePlan, scopesFrom, weatherHolder
} from '../roleComposition.js'
import RoleHandoffFields from './RoleHandoffFields.vue'
import RoleTopology from './RoleTopology.vue'
import RoleTransitions from './RoleTransitions.vue'

const emit = defineEmits(['edit-profile', 'notification'])
const { roleRequest, roleLibrary, roleCompatibility, libraryRuntime: roleRuntime } = useRoles()
const { speech } = useRuntimeSettings()

// Save state of one scope, shown in its header.
const RoleSaveState = { props: ['scope'], setup(props) {
  return () => {
    const s = props.scope
    const [cls, icon, text] = s.status === 'saving' ? ['busy', 'bi bi-arrow-repeat spin', '儲存中…']
      : s.status === 'error' ? ['err', 'bi bi-exclamation-octagon', '儲存失敗，草稿仍保留']
      : isDirty(s) ? ['dirty', 'bi bi-exclamation-triangle', '有未儲存的變更']
      : ['', 'bi bi-check-circle', s.base.revision ? `已儲存${s.savedAt ? ` · ${s.savedAt}` : ` · 第 ${s.base.revision} 版`}` : '']
    return text ? h('span', { class: ['rc-save-state', cls], role: 'status' }, [h('i', { class: icon, 'aria-hidden': 'true' }), text]) : null
  }
} }
const INLINE_FIELDS = ['announcement', 'enabled', 'profile_id', 'tools.weather.enabled']
// A failed save of one scope; the other scopes are untouched.
const RoleScopeError = { props: ['scope', 'name'], emits: ['use-latest', 'overwrite', 'reload'], setup(props, { emit: send }) {
  return () => {
    const s = props.scope
    // Field errors show next to their field.
    if (s.status !== 'error' || (INLINE_FIELDS.includes(s.field) && !s.conflict)) return null
    const own = s.conflict && s.conflict.scope !== 'composition' && s.conflict.current
    const title = s.conflict ? (s.conflict.scope === 'composition' ? '儲存失敗：角色組合已被另一個控制台更新' : `儲存失敗：「${props.name}」已被另一個控制台更新`) : '儲存失敗'
    const detail = `${s.error}${s.conflict ? ' 你的草稿仍保留；其他成員不受影響。' : ''}${s.reasons.length && !s.error.includes(s.reasons[0]) ? ` ${s.reasons.join('；')}` : ''}`
    const actions = own ? [h('button', { type: 'button', class: 'rc-btn sm', onClick: () => send('use-latest') }, '載入最新版本'),
      h('button', { type: 'button', class: 'rc-btn sm', onClick: () => send('overwrite') }, '以草稿覆寫')]
      : s.conflict ? [h('button', { type: 'button', class: 'rc-btn sm', onClick: () => send('reload') }, '重新載入組合')] : []
    return h('div', { class: 'rc-banner danger', role: 'alert' }, [h('i', { class: 'bi bi-exclamation-octagon', 'aria-hidden': 'true' }),
      h('div', [h('b', title), h('div', { class: 'rc-detail' }, detail)]), h('span', { class: 'rc-acts' }, actions)])
  }
} }

const library = shallowRef(null), scopes = ref(null), fresh = ref([]), media = ref([])
const selected = ref('main'), loadError = ref(''), barError = ref(''), structureBusy = ref(false), applying = ref(false)
const dialog = ref(null), dialogOk = ref(null), mainSelect = ref(null)
let freshId = 0, answerDialog = null, returnFocus = null

// ── Reading the library ──────────────────────────────────────────────
const profiles = computed(() => library.value?.profiles || [])
const names = computed(() => Object.fromEntries(profiles.value.map(p => [p.id, p.name])))
const nameOf = id => names.value[id] || id || ''
const initialOf = id => Array.from(nameOf(id))[0] || '?'
const colorOf = id => avatarColor(profiles.value, id)
const profileOf = id => profiles.value.find(p => p.id === id)
const mainId = computed(() => library.value?.composition.main.profile_id)
const mainProfile = computed(() => profileOf(mainId.value))
const memberIds = computed(() => library.value?.composition.members.map(m => m.profile_id) || [])
const memberCount = computed(() => memberIds.value.length + fresh.value.length)
const enabled = computed(() => library.value ? enabledCount(library.value) : 0)
const reasonsOf = id => roleCompatibility.value?.[id] || []
const live = computed(() => library.value ? liveMemberIds(library.value, roleCompatibility.value) : [])
const holder = computed(() => library.value ? weatherHolder(library.value) : '')
// Server catalog labels carry each engine's usage restriction, as in the profile editor.
const ttsLabel = p => speech.tts.engines.find(engine => engine.id === p?.tts?.type)?.label || p?.tts?.type || '—'
const llmLabel = p => p ? `${p.llm?.endpoint || '未選端點'} · ${p.llm?.model || '未選模型'}` : '—'
const engineLabel = p => ({ musetalk: 'MuseTalk' })[p?.engine] || p?.engine || '—'
// A Matcha voice is a voice model: show its name and usage label, as the profile editor does.
function voiceName(tts) {
  if (!tts?.ref_file) return '未選聲音'
  if (tts.type !== 'matcha') return tts.ref_file
  const model = (speech.tts.voice_models || []).find(item => item.id === tts.ref_file)
  return model ? voiceModelLabel(model) : missingVoiceModelLabel(tts.ref_file)
}
const voiceLabel = p => p ? `${ttsLabel(p)} · ${voiceName(p.tts)}` : '—'
const dirty = isDirty
const inUse = computed(() => new Set([mainId.value, ...memberIds.value, ...fresh.value.map(s => s.draft.profile_id)]))
const candidates = computed(() => profiles.value.filter(p => !inUse.value.has(p.id)))
const addTitle = computed(() => !candidates.value.length ? '所有設定檔都已在組合中；先到「數位人設定檔」複製一份' : '')

// ── Scopes and selection ─────────────────────────────────────────────
function scopeOf(key) {
  if (!scopes.value || !key) return null
  if (key === 'main') return scopes.value.main
  if (key === 'transitions') return scopes.value.transitions
  if (key.startsWith('m:')) return scopes.value.members[key.slice(2)] || null
  if (key.startsWith('new:')) return fresh.value.find(s => s.key === key) || null
  return null
}
const current = computed(() => (selected.value.startsWith('m:') || selected.value.startsWith('new:')) ? scopeOf(selected.value) : null)
watch(current, value => { if (!value && selected.value !== 'main' && selected.value !== 'add' && scopes.value) selected.value = 'main' })
function select(key) { selected.value = key }
const memberKeys = computed(() => [...Object.keys(scopes.value?.members || {}).map(id => `m:${id}`), ...fresh.value.map(s => s.key)])
const seatOf = key => memberKeys.value.indexOf(key) + 1
const dirtyKeys = computed(() => scopes.value ? ['main', ...memberKeys.value, 'transitions'].filter(key => isDirty(scopeOf(key))) : [])
const labelOf = key => key === 'main' ? nameOf(mainId.value) : key === 'transitions' ? '角色轉場' : nameOf(scopeOf(key)?.draft.profile_id)

function memberAvatarState(item) {
  if (reasonsOf(item.draft.profile_id).length) return 'bad'
  return item.kind === 'member' && item.base.enabled ? '' : 'off'
}
const rows = computed(() => {
  const list = memberKeys.value.map(key => {
    const item = scopeOf(key), id = item.draft.profile_id, reasons = reasonsOf(id), saved = item.kind === 'member' && !item.missing
    const chip = reasons.length ? { tone: 'danger', icon: 'bi bi-x-circle', text: '不相容' }
      : !saved ? { tone: 'neutral', text: '尚未儲存' }
      : item.base.enabled ? (live.value.includes(item.base.profile_id) ? { tone: 'ok', text: '已啟用' } : { tone: 'neutral', text: '交接已關閉' })
      : { tone: 'neutral', text: '未啟用 · 保留設定' }
    return { key, id, reasons, chip, dirty: isDirty(item), weather: saved && item.base.tools?.weather?.enabled, avatarState: memberAvatarState(item) }
  })
  const empties = Array.from({ length: Math.max(0, MAX_ENABLED - list.length) }, (_, i) => ({ key: `empty-${i}`, empty: true, first: i === 0, seat: list.length + i + 1 }))
  return [...list, ...empties]
})

// ── Selected member ──────────────────────────────────────────────────
const currentReasons = computed(() => current.value ? reasonsOf(current.value.draft.profile_id) : [])
const fieldError = (item, field) => item?.field === field ? item.error : ''
const enableLocked = computed(() => {
  const item = current.value
  if (!item || item.draft.enabled) return false
  const wasEnabled = item.kind === 'member' && item.base.enabled
  return Boolean(currentReasons.value.length) || (!wasEnabled && enabled.value >= MAX_ENABLED)
})
const enabledLabel = computed(() => {
  const item = current.value
  if (currentReasons.value.length) return item.draft.enabled ? '已啟用 · 不相容，暫不參與' : '無法啟用'
  return item.draft.enabled ? '已啟用' : '未啟用'
})
const enableHint = computed(() => {
  const item = current.value
  if (fieldError(item, 'enabled')) return fieldError(item, 'enabled')
  if (currentReasons.value.length) return `先讓這份設定檔改用 ${ttsLabel(mainProfile.value)} 與相同回答模型服務（${llmLabel(mainProfile.value)}）。`
  if (enableLocked.value) return `已啟用 ${MAX_ENABLED} 位專門數位人；先停用一位才能啟用這位。`
  return item.draft.enabled ? '' : '未啟用：保留全部設定，但不參與交接。'
})
const profileChoices = computed(() => {
  const item = current.value
  if (!item) return []
  return profiles.value.filter(p => p.id === item.draft.profile_id || p.id === item.base.profile_id || !inUse.value.has(p.id))
})
const compatRows = computed(() => {
  const p = profileOf(current.value?.draft.profile_id), m = mainProfile.value
  if (!p || !m) return []
  const same = (a, b) => a === b ? `（與${nameOf(m.id)}相同）` : `，組合使用 ${b}`
  return [
    { label: '唇形引擎', ok: p.engine === 'musetalk' && m.engine === 'musetalk', text: `${engineLabel(p)}${p.engine === 'musetalk' && m.engine === 'musetalk' ? '' : '；即時組合需要 MuseTalk'}` },
    { label: '回答模型服務', ok: llmLabel(p) === llmLabel(m), text: `${llmLabel(p)}${same(llmLabel(p), llmLabel(m))}` },
    { label: '語音合成引擎', ok: p.tts?.type === m.tts?.type, text: `${ttsLabel(p)}${same(ttsLabel(p), ttsLabel(m))}` }
  ]
})
const weatherLocked = computed(() => {
  const item = current.value
  return Boolean(item && holder.value && holder.value !== item.base.profile_id && !item.draft.tools.weather.enabled)
})

// ── Topology ─────────────────────────────────────────────────────────
const liveKeys = computed(() => library.value?.composition.enabled ? ['main', ...live.value.map(id => `m:${id}`)] : ['main'])
const liveKeysById = computed(() => library.value?.composition.enabled ? [mainId.value, ...live.value] : [mainId.value])
const topologyNodes = computed(() => {
  if (!library.value) return []
  const nodes = [{ key: 'main', target: 'main', main: true, name: nameOf(mainId.value), initial: initialOf(mainId.value), color: colorOf(mainId.value), state: 'live', selected: selected.value === 'main' }]
  for (const row of rows.value) {
    if (row.empty) nodes.push({ key: row.key, target: 'add', name: `空位 ${row.seat}`, initial: '+', state: 'empty', selected: false })
    else nodes.push({ key: row.key, target: row.key, name: nameOf(row.id), initial: initialOf(row.id), color: colorOf(row.id), selected: selected.value === row.key,
      state: row.reasons.length ? 'bad' : liveKeys.value.includes(row.key) ? 'live' : row.key.startsWith('new:') ? 'new' : 'off' })
  }
  return nodes
})
const topologyDescription = computed(() => {
  const linked = liveKeys.value.map(key => key === 'main' ? nameOf(mainId.value) : nameOf(key.slice(2)))
  return linked.length > 1 ? `交接路線：${linked.join('、')}彼此都可直接交接；${nameOf(mainId.value)}負責開場／兜底。` : `交接路線：目前只有${nameOf(mainId.value)}回答。`
})
const transitionMembers = computed(() => [{ id: mainId.value, name: nameOf(mainId.value), main: true }, ...memberIds.value.map(id => ({ id, name: nameOf(id) }))])

// ── Apply ────────────────────────────────────────────────────────────
const pendingApply = computed(() => Boolean(library.value && (!roleRuntime.profiles_applied || library.value.revision !== roleRuntime.active_revision)))
const applyText = computed(() => roleRuntime.pending ? '已排定套用，控制台與舞台皆斷線後更新'
  : pendingApply.value ? '已儲存，尚未套用' : '已套用 · 下一場對話採用目前組合')
async function applyNow() {
  applying.value = true; barError.value = ''
  try {
    await roleRequest('/apply', 'POST')
    emit('notification', roleRuntime.pending ? '組合已排定套用，控制台與舞台皆斷線後更新。' : '組合已套用，下一場對話採用；目前對話繼續使用原設定。', 'success')
  } catch (e) { barError.value = e.message } finally { applying.value = false }
}

// ── Loading and adopting ─────────────────────────────────────────────
function adopt(next) {
  if (!next?.composition) return
  library.value = toRaw(next)
  scopes.value = scopes.value ? reconcile(scopes.value, library.value) : scopesFrom(library.value)
  // A fresh draft saved meanwhile (by this or another console) is now a member.
  fresh.value = fresh.value.filter(s => !library.value.composition.members.some(m => m.profile_id === s.draft.profile_id) || s.status === 'saving')
}
async function load() {
  loadError.value = ''
  try {
    const data = await roleRequest()
    media.value = data.media || []
    adopt(data.library)
  } catch (e) { loadError.value = e.message }
}
watch(roleLibrary, value => { if (value && toRaw(value) !== library.value) adopt(value) })
onMounted(load)

// ── Saving one scope ─────────────────────────────────────────────────
const now = () => new Date().toTimeString().slice(0, 5)
function invalid(item) {
  if (item.kind === 'transitions') {
    const edges = [item.draft.default, ...item.draft.overrides]
    return edges.some(e => e.kind === 'video' && !e.asset_id) ? ['', '請為使用自訂影片的轉場選擇影片，或先在「轉場影片」上傳。'] : null
  }
  return item.draft.announcement.trim() ? null : ['announcement', '請填寫中文交接說明；交接前會先說這句。']
}
async function save(key) {
  const item = scopeOf(key)
  if (!item || item.status === 'saving') return
  const problem = invalid(item)
  if (problem) {
    Object.assign(item, { status: 'error', field: problem[0], error: problem[1], conflict: null, reasons: [] })
    if (problem[0]) focusField(key, problem[0])
    return
  }
  Object.assign(item, { status: 'saving', field: '', error: '', conflict: null, reasons: [] })
  const label = labelOf(key)
  try {
    let data = null
    for (const step of savePlan(item, library.value)) {
      data = await roleRequest(step.path, step.method, step.body)
      adopt(data.library)
    }
    finish(key, item)
    emit('notification', `已儲存「${label}」；其他位的草稿保持原樣。`, 'success')
  } catch (e) {
    const failure = readFailure(e)
    Object.assign(item, { status: 'error', error: failure.message, field: failure.field, reasons: failure.reasons, conflict: failure.conflict })
    if (failure.field === 'announcement') focusField(key, 'announcement')
  }
}
// Replace the saved scope with the server's version and keep it selected.
function finish(key, item) {
  const saved = scopesFrom(library.value)
  if (key === 'main' || key === 'transitions') {
    scopes.value[key] = { ...saved[key], savedAt: now() }
    return
  }
  const id = item.draft.profile_id
  if (key.startsWith('new:')) fresh.value = fresh.value.filter(s => s !== item)
  else if (id !== item.base.profile_id) delete scopes.value.members[item.base.profile_id]
  if (saved.members[id]) scopes.value.members[id] = { ...saved.members[id], savedAt: now() }
  selected.value = `m:${id}`
}
function revert(key) {
  const item = scopeOf(key)
  if (item) rebase(item, item.base)
}
function conflictBase(key, item) {
  const current = item.conflict?.current
  return key === 'main' ? { ...current, enabled: library.value.composition.enabled } : current
}
function useLatest(key) {
  const item = scopeOf(key)
  if (item?.conflict?.current) rebase(item, conflictBase(key, item))
}
function overwrite(key) {
  const item = scopeOf(key)
  if (!item?.conflict?.current) return
  rebase(item, conflictBase(key, item), true)
  save(key)
}
function focusField(key, field) {
  const prefix = key === 'main' ? 'rc-main' : `rc-${key.replace(':', '-')}`
  nextTick(() => globalThis.document?.getElementById?.(`${prefix}-${field.replace('_', '-')}`)?.focus?.())
}

// ── Composition-wide changes ─────────────────────────────────────────
function addCandidate(id) {
  const item = { ...newMemberScope(id, nameOf(id)), key: `new:${++freshId}` }
  fresh.value.push(item)
  selected.value = item.key
  focusField(item.key, 'description')
}
function discardNew(key) {
  fresh.value = fresh.value.filter(s => s.key !== key)
  selected.value = 'main'
}
async function removeMember(key) {
  const item = scopeOf(key), id = item.base.profile_id, name = nameOf(id)
  const ok = await ask({ title: `把「${name}」移出組合？`, ok: '移出組合', danger: true, lines: [
    `設定檔本身保留，但這一席的專長介紹、交接規則、交接說明與工具會一併移除${item.base.tools?.weather?.enabled ? '，天氣工具將沒有人提供' : ''}。`,
    '角色轉場中涉及這位的個別方向保留但暫不使用。'] })
  if (!ok) return
  structureBusy.value = true; barError.value = ''
  try {
    const data = await roleRequest(`/composition/members/${encodeURIComponent(id)}`, 'DELETE', { expected_revision: library.value.composition.revision })
    delete scopes.value.members[id]
    adopt(data.library)
    selected.value = 'main'
    emit('notification', `已將「${name}」移出組合`, 'success')
  } catch (e) { barError.value = e.message } finally { structureBusy.value = false }
}
async function changeMain(id) {
  const previous = mainId.value
  if (!id || id === previous) return
  const restore = () => { if (mainSelect.value) mainSelect.value.value = previous }
  const ok = await ask({ title: '更換主數位人？', ok: '更換並儲存', lines: [
    `改由「${nameOf(id)}」為每場對話開場，並在沒有其他角色適合時接手（開場／兜底）。`,
    '主數位人的專長介紹、交接規則與交接說明保留，請確認仍適用。',
    '正在進行的對話維持原組合；套用後由下一場對話開始生效。'] })
  if (!ok) return restore()
  structureBusy.value = true; barError.value = ''
  try {
    let data
    try {
      data = await roleRequest('/composition', 'PUT', { expected_revision: library.value.composition.revision, main: id })
    } catch (e) {
      const failure = readFailure(e)
      if (!failure.disableRequired.length) throw e
      const confirmed = await ask({ title: '部分專門數位人將改為未啟用', ok: '停用並更換', danger: true, lines: [
        `${failure.disableRequired.map(nameOf).join('、')} 與新的主數位人不相容，將改為未啟用（設定保留）。`] })
      if (!confirmed) return restore()
      data = await roleRequest('/composition', 'PUT', { expected_revision: library.value.composition.revision, main: id, confirm_disable: true })
    }
    adopt(data.library)
    const disabled = data.disabled_members || []
    emit('notification', `主數位人已改為「${nameOf(id)}」${disabled.length ? `；${disabled.map(nameOf).join('、')} 已改為未啟用` : ''}。`, 'success')
  } catch (e) { restore(); barError.value = e.message } finally { structureBusy.value = false }
}

// ── Confirmation dialog ──────────────────────────────────────────────
function ask(options) {
  returnFocus = globalThis.document?.activeElement
  dialog.value = options
  nextTick(() => dialogOk.value?.focus?.())
  return new Promise(resolve => { answerDialog = resolve })
}
function answer(value) {
  dialog.value = null
  answerDialog?.(value); answerDialog = null
  returnFocus?.focus?.(); returnFocus = null
}

// ── 交接試算 ─────────────────────────────────────────────────────────
const sim = ref({ from: '', text: '', busy: false, result: null, error: '' })
const simReady = computed(() => liveKeysById.value.length > 1)
const simHint = computed(() => !simReady.value ? '開啟角色交接並至少啟用一位相容的專門數位人後即可試算。'
  : dirtyKeys.value.length ? '以已儲存的組合試算；未儲存的修改不列入，請先儲存。'
    : '以已儲存的組合實際詢問路由，當成新對話判斷；不播報，也不寫入對話。')
watch(liveKeysById, ids => { if (!ids.includes(sim.value.from)) sim.value.from = ids[0] || '' }, { immediate: true })
async function dryRun() {
  if (!simReady.value || sim.value.busy || !sim.value.text.trim()) return
  sim.value = { ...sim.value, busy: true, result: null, error: '' }
  try {
    const data = await roleRequest('/composition/dry-run', 'POST', { current_profile_id: sim.value.from, text: sim.value.text })
    sim.value.result = data
  } catch (e) { sim.value.error = e.message } finally { sim.value.busy = false }
}
defineExpose({ dirtyCount: computed(() => dirtyKeys.value.length), select, load })
</script>

<style>
/* 角色組合與交接：沿用控制台 token，選擇器都在 .role-compose 之下 */
.role-compose{--rc-xs:12px;--rc-sm:13px;--rc-md:14px;--rc-lg:16px;display:grid;grid-template-rows:auto auto minmax(0,1fr);gap:var(--s3);min-height:0;min-width:0;color:var(--text);font-size:var(--rc-sm)}
.role-compose h3,.role-compose p{margin:0}
.role-compose .mono,.role-compose .num{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.role-compose .rc-hint{font-size:var(--rc-xs);color:var(--text-3);line-height:1.5}
.role-compose .rc-hint.rc-strong{color:var(--text-2)}
.role-compose .rc-danger-text{color:var(--danger)}
.role-compose .rc-bar-error{grid-row:auto}
/* 組合列 */
.role-compose .rc-bar{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap;padding:var(--s2) var(--s3);border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-surface);box-shadow:var(--shadow-1);min-width:0}
.role-compose .rc-bar>label{font-weight:700;white-space:nowrap;display:inline-flex;gap:6px;align-items:center}
.role-compose .rc-bar>label i{color:var(--brand)}
.role-compose .rc-bar select{width:auto;min-width:9rem;max-width:16rem}
.role-compose .rc-meta{font-size:var(--rc-xs);color:var(--text-3);white-space:nowrap}
.role-compose .rc-spacer{flex:1}
.role-compose .rc-count{font-size:var(--rc-xs);font-weight:700;padding:3px 10px;border-radius:999px;background:var(--brand-surface);color:var(--brand-ink);white-space:nowrap}
/* 三欄 */
.role-compose .rc-work{display:grid;grid-template-columns:clamp(15rem,17vw,19.5rem) minmax(0,1fr) clamp(16rem,19vw,22rem);gap:var(--s3);min-height:0;min-width:0}
.role-compose .rc-aside{display:flex;flex-direction:column;gap:var(--s3);min-height:0;min-width:0;overflow-y:auto;overscroll-behavior:contain}
.role-compose .rc-aside>.rc-card{flex:none;overflow:visible}
/* 卡片 */
.role-compose .rc-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:var(--shadow-1);display:grid;grid-template-rows:auto minmax(0,1fr);min-height:0;min-width:0;overflow:hidden}
.role-compose .rc-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--s3);padding:var(--s3) var(--s4);border-bottom:1px solid var(--border)}
.role-compose .rc-card-head h3{font-size:var(--rc-md);font-weight:700;display:flex;align-items:center;gap:var(--s2)}
.role-compose .rc-card-head h3 i{color:var(--brand)}
.role-compose .rc-card-head p{font-size:var(--rc-xs);color:var(--text-3);margin-top:2px}
.role-compose .rc-card-body{overflow-y:auto;overscroll-behavior:contain;padding:var(--s3) var(--s4) var(--s4);min-height:0;display:flex;flex-direction:column;gap:var(--s2)}
.role-compose .rc-aside .rc-card-body{overflow:visible}
.role-compose .rc-sub-title{font-size:var(--rc-sm);font-weight:700;color:var(--text);display:flex;align-items:center;gap:var(--s2)}
.role-compose .rc-sub-title i{color:var(--brand)}
/* 表單 */
.role-compose .rc-field{display:flex;flex-direction:column;gap:var(--s1);min-width:0}
.role-compose .rc-field>label,.role-compose .rc-field>.rc-l{font-weight:600}
.role-compose .rc-opt{font-weight:500;color:var(--text-3);font-size:var(--rc-xs);margin-left:4px}
.role-compose .rc-req{color:var(--danger);margin-left:2px}
.role-compose .rc-grid-2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--s3)}
.role-compose .rc-input{width:100%;min-height:2.3rem;padding:.4rem .65rem;border:1px solid var(--border-strong);border-radius:var(--radius-sm);background:var(--bg-input);color:var(--text);font:inherit;transition:border-color var(--anim-fast),box-shadow var(--anim-fast)}
.role-compose textarea.rc-input{resize:vertical;line-height:1.55}
.role-compose .rc-input:hover:not(:disabled){border-color:var(--text-3)}
.role-compose .rc-input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-surface)}
.role-compose .rc-input:focus-visible{outline:2px solid var(--brand);outline-offset:1px}
.role-compose .rc-input:disabled{opacity:.5;cursor:not-allowed}
.role-compose .rc-input[aria-invalid="true"]{border-color:var(--danger);box-shadow:0 0 0 3px var(--danger-surface)}
.role-compose .rc-field-error{display:flex;gap:var(--s1);align-items:flex-start;color:var(--danger);font-size:var(--rc-xs);font-weight:600}
.role-compose .rc-check{display:flex;align-items:flex-start;gap:var(--s2);cursor:pointer}
.role-compose .rc-check input{accent-color:var(--brand);width:1.05rem;height:1.05rem;margin:.15rem 0 0;flex:none}
.role-compose .rc-check:has(input:disabled){cursor:not-allowed}
.role-compose .rc-check .rc-ct b{display:block}
.role-compose .rc-switch{display:inline-flex;align-items:center;gap:var(--s2);cursor:pointer}
.role-compose .rc-switch input{appearance:none;width:2.6rem;height:1.5rem;border-radius:999px;background:var(--border-strong);position:relative;cursor:pointer;transition:background var(--anim-fast);margin:0;flex:none}
.role-compose .rc-switch input::after{content:"";position:absolute;top:3px;left:3px;width:calc(1.5rem - 6px);height:calc(1.5rem - 6px);border-radius:50%;background:#fff;transition:transform var(--anim-fast);box-shadow:0 1px 2px rgba(0,0,0,.3)}
.role-compose .rc-switch input:checked{background:var(--brand)}
.role-compose .rc-switch input:checked::after{transform:translateX(1.1rem)}
.role-compose .rc-switch input:disabled{opacity:.45;cursor:not-allowed}
.role-compose .rc-switch input:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.role-compose .rc-switch .rc-state{font-size:var(--rc-xs);color:var(--text-2);font-weight:600}
.role-compose .rc-pill{font-family:var(--font-mono);font-size:var(--rc-xs);padding:0 8px;border-radius:999px;background:var(--bg-sunken);border:1px solid var(--border);white-space:nowrap;color:var(--text-2)}
/* 按鈕 */
.role-compose .rc-btn{display:inline-flex;align-items:center;justify-content:center;gap:var(--s2);min-height:2.3rem;padding:0 var(--s4);border-radius:var(--radius-sm);border:1px solid var(--border-strong);background:var(--bg-surface);color:var(--text);font:inherit;font-weight:600;cursor:pointer;white-space:nowrap;transition:background var(--anim-fast),border-color var(--anim-fast)}
.role-compose .rc-btn:hover:not(:disabled){background:var(--bg-hover)}
.role-compose .rc-btn:disabled{opacity:.45;cursor:not-allowed}
.role-compose .rc-btn:focus-visible,.role-compose .rc-slot:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.role-compose .rc-btn.primary{background:var(--brand);border-color:var(--brand);color:var(--on-brand)}
.role-compose .rc-btn.primary:hover:not(:disabled){background:var(--brand-hover);border-color:var(--brand-hover)}
.role-compose .rc-btn.ghost{border-color:transparent;background:transparent;color:var(--text-2)}
.role-compose .rc-btn.ghost:hover:not(:disabled){background:var(--bg-hover);color:var(--text)}
.role-compose .rc-btn.danger{color:var(--danger);border-color:var(--danger-border)}
.role-compose .rc-btn.danger:hover:not(:disabled){background:var(--danger-surface)}
.role-compose .rc-btn.danger-solid{background:var(--danger);border-color:var(--danger);color:var(--on-danger)}
.role-compose .rc-btn.sm{min-height:2rem;padding:0 var(--s3);font-size:var(--rc-xs)}
.role-compose .rc-btn.link{border:0;background:none;padding:0;min-height:0;color:var(--brand-ink);font-weight:600;text-decoration:underline;text-underline-offset:2px}
.role-compose .rc-btn.link:hover{background:none;color:var(--brand)}
.role-compose .rc-self-start{align-self:flex-start}
.role-compose .rc-acts{display:inline-flex;align-items:center;gap:var(--s2);flex-wrap:wrap}
/* 狀態 */
.role-compose .rc-banner{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:var(--s3);align-items:center;padding:var(--s2) var(--s3);border:1px solid var(--border);border-left-width:4px;border-radius:var(--radius-md);background:var(--bg-surface);margin:0}
.role-compose .rc-banner>i{font-size:1.2rem}
.role-compose .rc-banner b{font-weight:700}
.role-compose .rc-banner .rc-detail{color:var(--text-2);font-size:var(--rc-xs);margin-top:1px;overflow-wrap:anywhere}
.role-compose .rc-banner.warn{border-color:var(--warn-border);border-left-color:var(--warn-bar);background:var(--warn-surface)}
.role-compose .rc-banner.warn>i,.role-compose .rc-banner.warn b{color:var(--warn)}
.role-compose .rc-banner.danger{border-color:var(--danger-border);border-left-color:var(--danger);background:var(--danger-surface)}
.role-compose .rc-banner.danger>i,.role-compose .rc-banner.danger b{color:var(--danger)}
.role-compose .rc-banner.info{border-color:var(--border);border-left-color:var(--brand);background:var(--brand-surface)}
.role-compose .rc-banner.info>i,.role-compose .rc-banner.info b{color:var(--brand-ink)}
.role-compose .rc-chip{display:inline-flex;align-items:center;gap:6px;padding:1px 9px 1px 7px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid var(--border);background:var(--bg-raised);color:var(--text-2);white-space:nowrap;font-family:inherit}
.role-compose .rc-dot{width:.5rem;height:.5rem;border-radius:50%;background:var(--idle)}
.role-compose .rc-chip.ok{color:var(--ok);border-color:var(--ok-border);background:var(--ok-surface)}
.role-compose .rc-chip.ok .rc-dot{background:var(--ok)}
.role-compose .rc-chip.warn{color:var(--warn);border-color:var(--warn-border);background:var(--warn-surface)}
.role-compose .rc-chip.danger{color:var(--danger);border-color:var(--danger-border);background:var(--danger-surface)}
.role-compose .rc-chip.neutral{color:var(--text-3)}
.role-compose button.rc-chip{cursor:pointer;min-height:2rem;max-width:100%;overflow:hidden;text-overflow:ellipsis}
.role-compose .rc-note{display:flex;gap:var(--s2);align-items:flex-start;font-size:var(--rc-xs);color:var(--text-2);padding:var(--s2) var(--s3);border-radius:var(--radius-sm);background:var(--bg-sunken)}
.role-compose .rc-note>i{color:var(--brand);margin-top:1px}
.role-compose .rc-note.lock>i{color:var(--text-3)}
.role-compose .rc-mini{font-size:11px;font-weight:700;padding:0 6px;border-radius:4px;background:var(--bg-sunken);border:1px solid var(--border);color:var(--text-2);white-space:nowrap}
.role-compose .rc-mini.main{background:var(--brand-surface);color:var(--brand-ink);border-color:transparent}
.role-compose .rc-mini.tool{background:var(--ok-surface);color:var(--ok);border-color:transparent}
.role-compose .rc-mini.dirty{background:var(--warn-surface);color:var(--warn);border-color:var(--warn-border)}
.role-compose .rc-av{width:2.2rem;height:2.2rem;border-radius:50%;display:grid;place-items:center;font-weight:700;color:#fff;font-size:var(--rc-sm);flex:none}
.role-compose .rc-av.lg{width:2.8rem;height:2.8rem;font-size:var(--rc-md)}
.role-compose .rc-av.off{background:var(--bg-sunken);color:var(--text-3);border:1.5px dashed var(--border-strong)}
.role-compose .rc-av.bad{background:var(--danger-surface);color:var(--danger);border:1.5px dashed var(--danger)}
.role-compose .rc-av-empty{background:transparent;border:1.5px dashed var(--border-strong);color:var(--text-3)}
.role-compose .rc-save-state{display:inline-flex;align-items:center;gap:6px;font-size:var(--rc-xs);color:var(--text-3);white-space:nowrap}
.role-compose .rc-save-state i{color:var(--ok)}
.role-compose .rc-save-state.dirty{color:var(--warn);font-weight:700}
.role-compose .rc-save-state.dirty i{color:var(--warn)}
.role-compose .rc-save-state.err{color:var(--danger);font-weight:700}
.role-compose .rc-save-state.err i{color:var(--danger)}
.role-compose .rc-save-state.busy i{color:var(--brand)}
/* 成員名單 */
.role-compose .rc-slot-group{font-size:var(--rc-xs);font-weight:700;color:var(--text-3);letter-spacing:.04em;display:flex;justify-content:space-between;align-items:center;margin-top:var(--s1)}
.role-compose .rc-slots{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:var(--s2)}
.role-compose .rc-slot{width:100%;display:grid;grid-template-columns:auto minmax(0,1fr);gap:var(--s3);align-items:start;padding:var(--s2) var(--s3);border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-raised);cursor:pointer;text-align:left;color:var(--text);font:inherit;transition:border-color var(--anim-fast),background var(--anim-fast)}
.role-compose .rc-slot:hover{border-color:var(--border-strong)}
.role-compose .rc-slot[aria-current="true"]{border-color:var(--brand);background:var(--brand-surface);box-shadow:inset 0 0 0 1px var(--brand)}
.role-compose .rc-slot-text{min-width:0}
.role-compose .rc-top{display:flex;align-items:center;flex-wrap:wrap;gap:2px var(--s2);min-width:0}
.role-compose .rc-top b{line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.role-compose .rc-top .rc-mini{margin-left:auto}
.role-compose .rc-sub{display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-top:3px}
.role-compose .rc-sub small{color:var(--text-3);font-size:12px}
.role-compose .rc-why{display:block;font-size:12px;color:var(--danger);margin-top:3px;line-height:1.4}
.role-compose .rc-slot.empty{border-style:dashed;background:transparent;align-items:center}
.role-compose .rc-slot.empty .rc-av{background:transparent;border:1.5px dashed var(--border-strong);color:var(--text-3)}
.role-compose .rc-slot.empty b{color:var(--text-2);font-weight:600}
/* 所選成員 */
.role-compose .rc-editor{grid-template-rows:auto auto minmax(0,1fr)}
.role-compose .rc-ed-head{display:flex;align-items:center;gap:var(--s3);padding:var(--s3) var(--s4);border-bottom:1px solid var(--border);min-width:0;flex-wrap:wrap}
.role-compose .rc-who{display:flex;align-items:center;gap:var(--s3);min-width:0;flex:1}
.role-compose .rc-who>div{min-width:0}
.role-compose .rc-ed-head h3{font-size:var(--rc-lg);font-weight:700;line-height:1.25;display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap}
.role-compose .rc-ed-head p{font-size:var(--rc-xs);color:var(--text-3);overflow-wrap:anywhere}
.role-compose .rc-ed-alerts{display:grid;gap:var(--s2);padding:var(--s3) var(--s4) 0}
.role-compose .rc-ed-alerts:empty{padding:0}
.role-compose .rc-ed-body{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);min-height:0}
.role-compose .rc-col{min-height:0;min-width:0;overflow-y:auto;overscroll-behavior:contain;padding:var(--s3) var(--s4) var(--s4);display:flex;flex-direction:column;gap:var(--s3)}
.role-compose .rc-col+.rc-col{border-left:1px solid var(--border);background:var(--bg-raised)}
.role-compose .rc-block{border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-surface);padding:var(--s3) var(--s4);display:flex;flex-direction:column;gap:var(--s3)}
.role-compose .rc-block-head{display:flex;align-items:center;justify-content:space-between;gap:var(--s2);flex-wrap:wrap}
.role-compose .rc-section-title{display:flex;align-items:center;gap:var(--s2);font-size:var(--rc-sm);font-weight:700;padding-bottom:var(--s1);border-bottom:1px solid var(--border)}
.role-compose .rc-section-title i{color:var(--brand)}
.role-compose .rc-step{font-family:var(--font-mono);font-size:11px;color:var(--text-3);font-weight:500;margin-left:auto}
.role-compose .rc-compat{display:grid;gap:4px;margin:0;padding:0;list-style:none}
.role-compose .rc-compat li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:var(--s2);font-size:var(--rc-xs);align-items:start}
.role-compose .rc-compat li b{font-weight:600;color:var(--text)}
.role-compose .rc-compat li span{color:var(--text-3);overflow-wrap:anywhere}
.role-compose .rc-compat li.ok>i{color:var(--ok)}
.role-compose .rc-compat li.bad>i,.role-compose .rc-compat li.bad span{color:var(--danger)}
.role-compose .rc-cand{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:var(--s3);align-items:center;padding:var(--s3);border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-raised)}
.role-compose .rc-cand b{display:block}
.role-compose .rc-cand small{color:var(--text-3);font-size:var(--rc-xs);overflow-wrap:anywhere}
.role-compose .rc-info-list{margin:0;padding:0;list-style:none;display:grid;gap:var(--s2)}
.role-compose .rc-info-list li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:var(--s2);font-size:var(--rc-xs);color:var(--text-2)}
.role-compose .rc-info-list li i{color:var(--brand);margin-top:2px}
.role-compose .rc-info-list li b{color:var(--text)}
.role-compose .rc-kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px var(--s3);font-size:var(--rc-xs);margin:0}
.role-compose .rc-kv dt{color:var(--text-3)}
.role-compose .rc-kv dd{margin:0;font-weight:600;overflow-wrap:anywhere}
/* 轉場 */
.role-compose .rc-trans{display:grid;gap:var(--s2);padding:var(--s2) var(--s3);border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg-raised)}
.role-compose .rc-dir{display:flex;align-items:center;gap:6px;font-weight:700;font-size:var(--rc-xs);flex-wrap:wrap}
.role-compose .rc-dir i{color:var(--brand)}
.role-compose .rc-trans .rc-input,.role-compose .rc-add-row .rc-input{min-height:2rem;padding:.25rem .5rem;font-size:var(--rc-xs)}
.role-compose .rc-row-effect{display:grid;grid-template-columns:minmax(0,1fr) 4.5rem;gap:var(--s2)}
.role-compose .rc-row-effect>:first-child{grid-column:1/-1}
.role-compose .rc-row-video{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--s2)}
.role-compose .rc-rm{margin-left:auto;min-height:1.6rem}
.role-compose .rc-tag-off{font-size:11px;color:var(--text-3);font-weight:500}
.role-compose details.rc-adv{border:1px solid var(--border);border-radius:var(--radius-md);background:var(--bg-surface)}
.role-compose details.rc-adv>summary{cursor:pointer;padding:var(--s2) var(--s3);font-weight:700;display:flex;align-items:center;gap:var(--s2);list-style:none}
.role-compose details.rc-adv>summary::-webkit-details-marker{display:none}
.role-compose details.rc-adv>summary:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
.role-compose .rc-chev{transition:transform var(--anim-fast);color:var(--text-3)}
.role-compose details.rc-adv[open]>summary .rc-chev{transform:rotate(90deg)}
.role-compose details.rc-adv>summary .rc-pill{margin-left:auto}
.role-compose .rc-adv-body{padding:0 var(--s3) var(--s3);display:flex;flex-direction:column;gap:var(--s2);min-width:0}
.role-compose .rc-adv-body input[type=file]{max-width:100%;font-size:var(--rc-xs);color:var(--text-2)}
.role-compose .rc-add-row{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr) auto;gap:var(--s2);align-items:center}
.role-compose .rc-add-row>i{color:var(--text-3)}
.role-compose .rc-media-row{display:flex;align-items:center;justify-content:space-between;gap:var(--s2);font-size:var(--rc-xs);overflow-wrap:anywhere}
/* 交接路線 */
.role-compose .rc-topo-wrap{padding:var(--s2) var(--s3) var(--s3);display:flex;flex-direction:column;gap:var(--s2);min-width:0}
.role-compose .rc-topo{width:100%;height:auto;max-height:13.5rem;display:block}
.role-compose .rc-topo .rc-edge{stroke:var(--brand);stroke-width:1.5;opacity:.45}
.role-compose .rc-topo .rc-node{cursor:pointer}
.role-compose .rc-topo .rc-node .rc-body{stroke-width:1.5}
.role-compose .rc-topo .rc-node.live .rc-body{stroke:none}
.role-compose .rc-topo .rc-node.off .rc-body,.role-compose .rc-topo .rc-node.new .rc-body{fill:var(--bg-sunken);stroke:var(--border-strong);stroke-dasharray:3 3}
.role-compose .rc-topo .rc-node.bad .rc-body{fill:var(--danger-surface);stroke:var(--danger);stroke-dasharray:3 3}
.role-compose .rc-topo .rc-node.empty .rc-body{fill:transparent;stroke:var(--border-strong);stroke-dasharray:2 3}
.role-compose .rc-topo .rc-ring{fill:none;stroke:var(--brand);stroke-width:2;opacity:0}
.role-compose .rc-topo .rc-node.sel .rc-ring{opacity:1}
.role-compose .rc-topo .rc-node:focus{outline:none}
.role-compose .rc-topo .rc-node:focus-visible .rc-ring{opacity:1;stroke-dasharray:3 2}
.role-compose .rc-topo .rc-ini{font-size:12px;font-weight:700;fill:#fff;text-anchor:middle;dominant-baseline:central;pointer-events:none}
.role-compose .rc-topo .rc-node.off .rc-ini,.role-compose .rc-topo .rc-node.new .rc-ini,.role-compose .rc-topo .rc-node.empty .rc-ini{fill:var(--text-3)}
.role-compose .rc-topo .rc-node.bad .rc-ini{fill:var(--danger)}
.role-compose .rc-topo .rc-lbl{font-size:10.5px;fill:var(--text-2);font-weight:600;dominant-baseline:central;pointer-events:none}
.role-compose .rc-topo .rc-lbl.dim{fill:var(--text-3);font-weight:500}
.role-compose .rc-topo .rc-tg{fill:var(--brand-ink);font-weight:700;font-size:9.5px}
.role-compose .rc-legend{display:flex;flex-wrap:wrap;gap:4px var(--s3);font-size:12px;color:var(--text-3)}
.role-compose .rc-legend span{display:inline-flex;align-items:center;gap:5px}
.role-compose .rc-legend i{display:inline-block;width:18px;height:0;border-top:2px solid var(--brand)}
.role-compose .rc-legend i.e{opacity:.6}
.role-compose .rc-legend i.o{width:10px;height:10px;border-radius:50%;border:1.5px dashed var(--border-strong)}
.role-compose .rc-legend i.x{width:10px;height:10px;border-radius:50%;border:1.5px dashed var(--danger)}
.role-compose .rc-sim{display:flex;flex-direction:column;gap:var(--s2);border-top:1px solid var(--border);padding-top:var(--s2);margin-top:2px}
.role-compose .rc-sim .rc-mini{margin-left:auto}
.role-compose .rc-sim-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:var(--s2)}
.role-compose .rc-sim .rc-field{gap:2px}
.role-compose .rc-sim .rc-field>label{font-size:var(--rc-xs);font-weight:600;color:var(--text-3)}
.role-compose .rc-sim .rc-input{min-height:2rem;padding:.25rem .5rem;font-size:var(--rc-xs)}
.role-compose .rc-sim-result{display:flex;flex-direction:column;gap:2px;font-size:var(--rc-xs)}
.role-compose .rc-sim-error{color:var(--danger)}
.role-compose .rc-single{overflow-y:auto}
/* 確認對話框 */
.role-compose .rc-scrim{position:fixed;inset:0;z-index:60;background:var(--scrim);display:grid;place-items:center;padding:var(--s4)}
.role-compose .rc-dialog{width:min(30rem,calc(100vw - 2rem));border:1px solid var(--border);border-radius:var(--radius-lg);background:var(--bg-surface);box-shadow:var(--shadow-2);overflow:hidden}
.role-compose .rc-dialog-body{padding:var(--s5);display:flex;flex-direction:column;gap:var(--s3)}
.role-compose .rc-dialog-body h3{font-size:var(--rc-lg)}
.role-compose .rc-dialog-body p{font-size:var(--rc-sm);color:var(--text-2);line-height:1.6}
.role-compose .rc-dialog-acts{display:flex;justify-content:flex-end;gap:var(--s2);padding:var(--s3) var(--s5);border-top:1px solid var(--border);background:var(--bg-raised)}
/* 較窄：所選成員改單欄；組合列的說明收起 */
@media (max-width:1560px){
  .role-compose .rc-ed-body{grid-template-columns:minmax(0,1fr);align-content:start;overflow-y:auto;overscroll-behavior:contain}
  .role-compose .rc-ed-body .rc-col{overflow:visible;min-height:auto}
  .role-compose .rc-col+.rc-col{border-left:0;border-top:1px solid var(--border)}
  .role-compose .rc-wide{display:none}
}
@media (max-height:820px){
  .role-compose .rc-topo{max-height:10.5rem}
  .role-compose .rc-slot{padding:6px var(--s3)}
  .role-compose .rc-card-head{padding:var(--s2) var(--s4)}
  .role-compose .rc-card-head p{display:none}
}
/* 一屏版面以外（窄或矮）：整頁捲動，右側欄移到下方 */
@media (max-width:1279.98px),(max-height:639.98px){
  .role-compose{display:flex;flex-direction:column}
  .role-compose .rc-work{grid-template-columns:minmax(14rem,16rem) minmax(0,1fr)}
  .role-compose .rc-aside{grid-column:1/-1;overflow:visible}
  .role-compose .rc-card,.role-compose .rc-col,.role-compose .rc-card-body{overflow:visible}
}
@media (max-width:820px){
  .role-compose .rc-work{grid-template-columns:minmax(0,1fr)}
  .role-compose .rc-grid-2,.role-compose .rc-sim-row{grid-template-columns:minmax(0,1fr)}
}
</style>
