<!-- Derived from Kedreamix/Linly-Talker-Stream; Apache-2.0.
     Modified by HongXian0903, 2026. See LICENSE and NOTICE. -->
<template>
  <div class="settings-page-layout" id="settings-page-layout">

    <!-- 左側類別導覽軌 (Fixed Left Rail) -->
    <aside class="settings-sidebar-rail">
      <div class="rail-header">
        <div class="rail-title">
          <i class="bi bi-sliders2" style="color: var(--brand-light);"></i>
          <span>{{ t('settings.systemSettings') }}</span>
        </div>
        <div class="rail-desc">管理數位人的回答、知識與舞台體驗</div>
        <button type="button" class="sample-btn settings-return-console" @click="closeSettings">
          <i class="bi bi-arrow-left" aria-hidden="true"></i> 返回控制台
        </button>
      </div>
      <nav class="rail-nav-list" role="tablist" :aria-label="t('settings.tabs.label')">
        <button
          v-for="(tab, index) in settingsTabs"
          :key="tab.id"
          :id="`railTab-${tab.id}`"
          type="button"
          class="rail-nav-item"
          role="tab"
          :class="{ active: activeSettingsTab === tab.id }"
          :aria-selected="activeSettingsTab === tab.id"
          :aria-controls="tab.id === 'stage' ? 'settings-panel-stage' : `catPanel-${tab.id}`"
          :tabindex="activeSettingsTab === tab.id ? 0 : -1"
          @click="selectSettingsTab(tab.id)"
          @keydown="handleTabKeydown($event, index)"
        >
          <div class="rail-item-left">
            <i :class="tab.icon"></i>
            <span>{{ tab.label }}</span>
          </div>
          <span class="rail-item-badge" v-if="tab.badge">{{ tab.badge }}</span>
        </button>
      </nav>
    </aside>

    <!-- ★ 右側主設定空間：100% 滿板自適應，無任何 1100px 截斷！ -->
    <main class="settings-main-container">
      <div class="settings-content-scroll" ref="settingsContentRef">

        <div v-if="loadingSettings" class="runtime-state-banner" role="status">
          <i class="bi bi-arrow-repeat spin" aria-hidden="true"></i>
          <span>正在載入目前 Prompt、數位人與執行設定…</span>
        </div>
        <div v-else-if="settingsError" class="runtime-state-banner error" role="alert">
          <i class="bi bi-exclamation-triangle" aria-hidden="true"></i>
          <span>無法讀取目前設定：{{ settingsError }}</span>
          <button type="button" class="btn-retry" @click="loadRuntimePanel">重新載入</button>
        </div>

        <p v-if="runtime.pending_settings?.items?.length" role="status" class="settings-error-banner">
          待套用：{{ runtime.pending_settings.items.join('、') }}。設定已儲存，控制台與舞台皆斷線後才更新。
          {{ runtime.pending_settings.error }}
        </p>

        <div v-show="activeSettingsTab === 'conversation'" class="settings-category-panel unified-role-panel"
          id="catPanel-conversation" role="tabpanel" aria-labelledby="railTab-conversation">
          <button type="button" class="sample-btn conversation-return-console" @click="closeSettings">返回控制台</button>
          <ConversationPanel :session-id="sessionId" @session-summary="emit('conversation-summary', $event)" />
        </div>

        <div v-show="activeSettingsTab === 'roles'" class="settings-category-panel unified-role-panel"
          id="catPanel-roles" role="tabpanel" aria-labelledby="railTab-roles">
          <AvatarProfiles ref="profilesRef" :initial-section="roleInitialSection" />
        </div>

        <div v-show="activeSettingsTab === 'greeting'" class="settings-category-panel unified-role-panel" id="catPanel-greeting" role="tabpanel" aria-labelledby="railTab-greeting">
          <IdleGreetingSettings v-if="greetingVisited" ref="greetingRef" :active="activeSettingsTab === 'greeting'" />
        </div>

        <!-- ── 分類 2：數位人與畫質 (滿板寬敞角色展示) ── -->
        <div
          v-show="activeSettingsTab === 'avatar'"
          class="settings-category-panel"
          id="catPanel-avatar"
          role="tabpanel"
          aria-labelledby="railTab-avatar"
        >
          <!-- 左欄：演算法引擎與貼回畫質參數 -->
          <section class="setting-card">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-layers-fill"></i> 唇形驅動引擎與畫質調優</div>
                <div class="card-subtitle-desc">選擇驅動人臉口型的神經網路架構與高清貼回參數。</div>
              </div>
              <button
                type="button"
                class="btn-apply-primary"
                style="padding: 6px 14px; font-size: 12px;"
                :disabled="applyingQuality"
                @click="handleApplyMouthQuality"
              >
                <i class="bi bi-check2" :class="{ spin: applyingQuality }"></i> 套用畫質
              </button>
            </div>

            <div class="grid-options-row">
              <div
                class="option-card-btn"
                :class="{ selected: selectedEngine === 'musetalk' }"
                @click="selectEngine('musetalk')"
              >
                <div class="opt-header-line">
                  <span class="opt-title">MuseTalk (Supported / Commercial)</span>
                  <span class="opt-badge">推薦高畫質</span>
                </div>
                <span class="opt-detail">潛空間擴散模型，口型細緻自然，邊緣連續無抖動。</span>
              </div>
              <div
                class="option-card-btn"
                :class="{ selected: selectedEngine === 'wav2lip' }"
                @click="selectEngine('wav2lip')"
              >
                <div class="opt-header-line">
                  <span class="opt-title">Wav2Lip (Research / Non-commercial)</span>
                  <span class="opt-badge" style="background: rgba(14,165,233,0.15); color: #38bdf8;">極速輕量</span>
                </div>
                <span class="opt-detail">傳統 GAN 架構，顯存消耗低，適合輕量邊緣設備。</span>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label for="paste-interpolation" class="field-main-label">{{ t('settings.quality.pasteInterpolation') }}</label>
                <span class="field-sub-hint">Lanczos 提供最佳邊緣文字級銳利度</span>
              </div>
              <div class="field-control-area">
                <select
                  id="paste-interpolation"
                  class="std-select"
                  v-model="qualityDraft.paste_interpolation"
                >
                  <option value="lanczos">Lanczos (最佳高清晰度 · 推薦)</option>
                  <option value="bicubic">Bicubic (雙立方平滑)</option>
                  <option value="bilinear">Bilinear (傳統雙線性)</option>
                </select>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label for="mouth-sharpen" class="field-main-label">{{ t('settings.quality.mouthSharpen') }}</label>
                <span class="field-sub-hint">消除唇邊貼回模糊，建議 0.5–0.8</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    id="mouth-sharpen"
                    type="range"
                    class="std-range"
                    min="0"
                    max="2"
                    step="0.1"
                    v-model.number="qualityDraft.mouth_sharpen"
                  >
                  <span class="std-val-pill">{{ qualityDraft.mouth_sharpen }}</span>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label for="bbox-shift" class="field-main-label">{{ t('settings.quality.bboxShift') }}</label>
                <span class="field-sub-hint">調整唇部框選區域上下偏移</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    id="bbox-shift"
                    type="range"
                    class="std-range"
                    min="-30"
                    max="30"
                    step="1"
                    v-model.number="qualityDraft.bbox_shift"
                  >
                  <span class="std-val-pill">{{ qualityDraft.bbox_shift }}px</span>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label for="extra-margin" class="field-main-label">{{ t('settings.quality.extraMargin') }}</label>
                <span class="field-sub-hint">外擴邊距控制</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    id="extra-margin"
                    type="range"
                    class="std-range"
                    min="0"
                    max="50"
                    step="1"
                    v-model.number="qualityDraft.extra_margin"
                  >
                  <span class="std-val-pill">{{ qualityDraft.extra_margin }}px</span>
                </div>
              </div>
            </div>

            <div style="font-size: 11.5px; color: var(--text-tertiary); margin-top: 10px; line-height: 1.5;">
              {{ t('settings.quality.rebuildHint') }}
            </div>
          </section>

          <!-- 右欄：滿板大縮圖角色相簿與匯入 -->
          <section class="setting-card">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-person-bounding-box"></i> 現有數位人角色庫</div>
                <div class="card-subtitle-desc">全景滿板展示，解析度與規格一清二楚。</div>
              </div>
              <button
                type="button"
                class="btn-apply-primary"
                style="padding: 6px 14px; font-size: 12px;"
                :disabled="applyingAvatar"
                @click="handleApplyAvatar"
              >
                <i class="bi bi-check2" :class="{ spin: applyingAvatar }"></i> 切換角色
              </button>
            </div>

            <div v-if="filteredCharacters.length" class="avatar-cards-grid">
              <div
                v-for="char in filteredCharacters"
                :key="char.id"
                class="avatar-item-card"
                :class="{ selected: selectedAvatarId === char.id }"
                @click="selectCharacter(char.id)"
              >
                <div class="avatar-preview-face">
                  <img v-if="char.preview_url || char.thumbnail" :src="char.preview_url || char.thumbnail" :alt="char.label || char.name || char.id" style="width: 100%; height: 100%; object-fit: cover; border-radius: var(--radius-sm);">
                  <i v-else class="bi bi-person-fill"></i>
                  <span class="avatar-badge-active" v-if="runtime.avatar.avatar_id === char.id">使用中</span>
                </div>
                <div class="avatar-meta-row">
                  <div class="avatar-name-txt">{{ char.label || char.name || char.id }}</div>
                  <div class="avatar-specs-txt">{{ char.resolution || '1080x1920' }} · {{ char.fps || 25 }}fps · {{ selectedEngine }}</div>
                </div>
                <div style="padding: 0 10px 10px; display: flex; justify-content: space-between; align-items: center; gap: 8px;">
                  <small>{{ char.green_screen ? '綠幕角色 · 可換背景' : '既有角色' }}</small>
                  <button type="button" class="btn-secondary" style="padding: 3px 8px; font-size: 11px;"
                    :disabled="runtime.avatar.avatar_id === char.id || importing"
                    :aria-label="`刪除 ${char.label || char.id}`"
                    @click.stop="requestDeleteAvatar(char)">刪除</button>
                </div>
              </div>
            </div>
            <div v-else-if="!filteredCharacters.length && !loadingSettings" class="empty-state-card">
              <i class="bi bi-person-video3" aria-hidden="true"></i>
              <strong>目前沒有可顯示的數位人角色</strong>
              <span v-if="settingsError">請先重新連線後端並重新載入設定。</span>
              <span v-else>{{ t('settings.avatar.emptyCharacters') }}</span>
            </div>

            <details v-if="archivedCharacters.items.length" style="margin-top: 14px;">
              <summary style="cursor: pointer; font-size: 12px;">本機回收區（{{ archivedCharacters.items.length }}）</summary>
              <div v-for="item in archivedCharacters.items" :key="item.archive_name"
                style="display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0;">
                <span style="font-size: 12px;">{{ item.avatar_id }}</span>
                <div style="display: flex; align-items: center; gap: 6px;">
                  <button type="button" class="btn-secondary" style="padding: 3px 8px; font-size: 11px;"
                    @click="handleRestoreAvatar(item.archive_name)">復原</button>
                  <button type="button" class="btn-danger" style="padding: 3px 8px; font-size: 11px;"
                    :aria-label="`永久刪除 ${item.avatar_id}`"
                    @click="requestPermanentlyDeleteAvatar(item)">刪除</button>
                </div>
              </div>
            </details>

            <div style="border-top: 1px solid var(--border-subtle); padding-top: 14px; margin-top: 12px;">
              <span style="font-size: 13px; font-weight: 600; display: block; margin-bottom: 8px;">
                <i class="bi bi-cloud-arrow-up-fill" style="color: var(--brand-light);"></i> 匯入自訂短影片以產生新角色
              </span>
              <div
                style="border: 1.5px dashed var(--border-default); border-radius: var(--radius-md); padding: 18px; text-align: center; color: var(--text-tertiary); background: var(--bg-input); cursor: pointer;"
                @dragover.prevent="onImportDragOver"
                @drop.prevent="onImportDrop"
                @click="importFileInput?.click()"
              >
                <input
                  ref="importFileInput"
                  type="file"
                  accept="video/mp4,video/quicktime,video/webm"
                  style="display: none;"
                  @change="onImportFileChange"
                >
                <i class="bi bi-film" style="font-size: 26px; color: var(--brand-light); display: block; margin-bottom: 6px;"></i>
                <span v-if="importFile">{{ importFile.name }} (點擊替換)</span>
                <span v-else>拖曳 MP4 / MOV 正面影片至此，或點擊選取檔案</span>
              </div>
              <label v-if="selectedEngine === 'musetalk'" style="display: flex; gap: 8px; align-items: center; margin-top: 10px; font-size: 12px;">
                <input type="checkbox" v-model="importGreenScreen"> 上傳影片為綠幕素材（建立後可使用舞台背景）
              </label>
              <div v-if="importFile" style="margin-top: 10px; display: flex; gap: 8px; align-items: center;">
                <input
                  type="text"
                  class="chat-text-entry"
                  v-model="importAvatarId"
                  :placeholder="importNamePlaceholder"
                  style="flex: 1;"
                >
                <button
                  type="button"
                  class="btn-apply-primary"
                  :disabled="!canStartImport"
                  @click="handleImportCharacter"
                >
                  開始建立
                </button>
              </div>
            </div>
          </section>
        </div>

        <!-- ── 分類 3：舞台與看板排版 (滿板大尺寸 9:16 對照視窗) ── -->
        <div
          v-show="activeSettingsTab === 'stage'"
          class="settings-category-panel"
          id="settings-panel-stage"
          role="tabpanel"
          aria-labelledby="railTab-stage"
        >
          <section class="setting-card" style="grid-column: 1 / -1;">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-image"></i> 演播場景背景</div>
                <div class="card-subtitle-desc">共用同一場景；圖片、循環影片及 GIF 均可作為背景。講話中也可切換。</div>
              </div>
              <button type="button" class="btn-secondary" :disabled="backgrounds.busy || !backgrounds.background_id"
                @click="handleSelectBackground('')">顯示原始綠幕</button>
            </div>
            <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 14px;">
              <input ref="backgroundFileInput" type="file" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm" aria-label="選擇舞台背景">
              <button type="button" class="btn-apply-primary" :disabled="backgrounds.busy" @click="handleUploadBackground">上傳背景</button>
              <small v-if="backgrounds.error" role="alert" style="color: #e57070;">{{ backgrounds.error }}</small>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px;">
              <div v-for="item in backgrounds.items" :key="item.id" style="min-width: 0;">
                <button type="button" class="option-card-btn"
                  :class="{ selected: backgrounds.background_id === item.id }"
                  :disabled="backgrounds.busy" @click="handleSelectBackground(item.id)"
                  style="padding: 6px; text-align: left; overflow: hidden; width: 100%;">
                  <img v-if="item.preview_url" :src="item.preview_url" :alt="item.label"
                    style="width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 4px;">
                  <span class="opt-title" style="display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ item.label }}</span>
                  <small>{{ item.kind === 'video' ? '循環影片' : item.kind === 'gif' ? 'GIF' : '圖片' }}</small>
                </button>
                <button type="button" class="btn-secondary"
                  style="width: 100%; margin-top: 5px; padding: 4px 8px; font-size: 11px;"
                  :disabled="backgrounds.busy || backgrounds.background_id === item.id"
                  :title="backgrounds.background_id === item.id ? '請先切換背景再刪除' : `刪除 ${item.label}`"
                  @click="requestDeleteBackground(item)">刪除背景</button>
              </div>
            </div>
            <p v-if="!backgrounds.items.length && !backgrounds.loading" style="font-size: 12px; color: var(--text-tertiary);">尚無背景，請先上傳。</p>
            <details v-if="backgrounds.archivedItems.length" style="margin-top: 14px;">
              <summary style="cursor: pointer; font-size: 12px;">背景回收區（{{ backgrounds.archivedItems.length }}）</summary>
              <div v-for="item in backgrounds.archivedItems" :key="item.archive_name"
                style="display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0;">
                <span style="font-size: 12px;">{{ item.label }}</span>
                <button type="button" class="btn-secondary" style="padding: 3px 8px; font-size: 11px;"
                  :disabled="backgrounds.busy" @click="handleRestoreBackground(item.archive_name)">復原</button>
              </div>
            </details>
          </section>
          <!-- 左欄：看板排版參數與九宮格 -->
          <section class="setting-card">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-layout-wtf"></i> 看板視覺風格樣式</div>
                <div class="card-subtitle-desc">設定浮動看板的材質外觀、尺寸與九宮格定位。</div>
              </div>
              <button
                type="button"
                class="btn-apply-primary"
                style="padding: 6px 14px; font-size: 12px;"
                :disabled="applyingStage"
                @click="handleApplyStage"
              >
                <i class="bi bi-check2" :class="{ spin: applyingStage }"></i> 套用舞台設定
              </button>
            </div>

            <div class="stage-composer-controls" style="border-top:1px solid var(--border-subtle);padding-top:14px">
              <label class="field-main-label"><input type="checkbox" v-model="composerDraft.composer_enabled"> 開啟舞台文字與附件輸入</label>
              <p class="field-sub-hint">套用所有舞台；各場對話與附件互相獨立。高度隨舞台等比縮放，內容較多時在框內捲動；預覽與舞台都會避開回覆文字區。</p>
              <div class="stage-position-sliders">
                <template v-for="field in composerFields" :key="field.key">
                  <label :for="field.key">{{ field.label }} {{ composerDraft[field.key] }}{{ field.unit }}</label>
                  <input :id="field.key" type="range" class="std-range" :min="field.min" :max="field.max" step="1" v-model.number="composerDraft[field.key]">
                </template>
              </div>
              <label for="composer-placeholder-zh" class="field-main-label">中文輸入提示</label>
              <input id="composer-placeholder-zh" class="std-input" maxlength="200" v-model="composerDraft.composer_placeholder_zh">
              <label for="composer-placeholder-en" class="field-main-label">英文輸入提示</label>
              <input id="composer-placeholder-en" class="std-input" maxlength="200" v-model="composerDraft.composer_placeholder_en">
            </div>
            <!-- 看板風格卡片: glass / slate / cue -->
            <div class="grid-options-row" style="grid-template-columns: repeat(3, 1fr);">
              <div
                v-for="style in stageBoardStyles"
                :key="style.id"
                :id="`stage-board-style-${style.id}`"
                class="option-card-btn"
                :class="{ selected: selectedBoardStyle === style.id }"
                @click="selectedBoardStyle = style.id"
              >
                <span class="opt-title">{{ style.icon }} {{ style.label }}</span>
                <span class="opt-detail">{{ style.desc }}</span>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label class="field-main-label">看板寬度 (Width px)</label>
                <span class="field-sub-hint">舞台畫布內的橫向尺寸 (200–720px)</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    type="range"
                    class="std-range"
                    min="200"
                    max="720"
                    step="10"
                    v-model.number="selectedBoardWidth"
                  >
                  <span class="std-val-pill">{{ selectedBoardWidth }}px</span>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label class="field-main-label">看板高度 (Height px)</label>
                <span class="field-sub-hint">條列項目展開的縱向高度 (180–720px)</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    type="range"
                    class="std-range"
                    min="180"
                    max="720"
                    step="10"
                    v-model.number="selectedBoardHeight"
                  >
                  <span class="std-val-pill">{{ selectedBoardHeight }}px</span>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label class="field-main-label">背景半透明度 (%)</label>
                <span class="field-sub-hint">透出人物背景同時維持字型對比</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    type="range"
                    class="std-range"
                    min="0"
                    max="90"
                    step="5"
                    v-model.number="selectedBoardTransparency"
                  >
                  <span class="std-val-pill">{{ selectedBoardTransparency }}%</span>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label for="stage-caption-max-chars" class="field-main-label">舞台字幕上限</label>
                <span class="field-sub-hint">保留最新字幕片段的最大字元數 (20–2000)</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    id="stage-caption-max-chars"
                    type="number"
                    class="std-range"
                    min="20"
                    max="2000"
                    step="10"
                    v-model.number="selectedStageCaptionMaxChars"
                  >
                  <span class="std-val-pill">{{ selectedStageCaptionMaxChars }} 字</span>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <label for="stage-board-preview" class="field-main-label">常態預覽看板</label>
                <span class="field-sub-hint">在舞台與控制台中預設顯示示範看板</span>
              </div>
              <div class="field-control-area">
                <label class="std-switch">
                  <input
                    id="stage-board-preview"
                    type="checkbox"
                    v-model="selectedBoardPreview"
                  >
                  <span class="std-slider-track"></span>
                </label>
              </div>
            </div>

            <div class="stage-caption-controls" style="border-top: 1px solid var(--border-subtle); padding-top: 14px;">
              <span style="font-size: 13px; font-weight: 600; display: block; margin-bottom: 8px;">
                <i class="bi bi-badge-cc-fill" style="color: var(--brand-light);"></i> 即時字幕帶展示區域
              </span>
              <div class="stage-position-sliders">
                <label for="stage-caption-x">水平位置 {{ selectedCaptionX }}%</label>
                <input id="stage-caption-x" type="range" class="std-range" min="0" max="100" step="1" v-model.number="selectedCaptionX">
                <label for="stage-caption-y">垂直位置 {{ selectedCaptionY }}%</label>
                <input id="stage-caption-y" type="range" class="std-range" min="0" max="100" step="1" v-model.number="selectedCaptionY">
                <label for="stage-caption-width">展示寬度 {{ selectedCaptionWidth }}%</label>
                <input id="stage-caption-width" type="range" class="std-range" min="40" max="100" step="1" v-model.number="selectedCaptionWidth">
              </div>
              <span class="field-sub-hint">可在右側舞台直接拖曳字幕帶；滑桿可精準調整位置與寬度。</span>
            </div>

            <!-- 九宮格定位器 -->
            <div style="border-top: 1px solid var(--border-subtle); padding-top: 14px;">
              <span style="font-size: 13px; font-weight: 600; display: block; margin-bottom: 8px;">
                <i class="bi bi-grid-3x3" style="color: var(--brand-light);"></i> 舞台位置九宮格快速對齊
              </span>
              <div class="position-alignment-box">
                <div class="grid-9-matrix" id="gridMatrix9">
                  <button
                    v-for="preset in boardPresets"
                    :key="preset.id"
                    type="button"
                    class="matrix-btn"
                    :class="{ active: selectedBoardPreset === preset.id }"
                    @click="selectBoardPreset(preset.id)"
                    :title="t(preset.labelKey)"
                  ></button>
                </div>
                <div style="font-size: 12px; color: var(--text-tertiary); line-height: 1.5;">
                  點選九宮格定位，即時觀察右側 9:16 大尺寸舞台縮圖連動。<br>
                  預設為「右上」，避免遮擋人物臉頰與底部字幕帶。
                </div>
              </div>
            </div>

            <div class="stage-mic-controls" style="border-top: 1px solid var(--border-subtle); padding-top: 14px;">
              <span style="font-size: 13px; font-weight: 600; display: block; margin-bottom: 8px;">
                <i class="bi bi-mic-fill" style="color: var(--brand-light);"></i> 麥克風位置
              </span>
              <div class="position-alignment-box">
                <div class="grid-9-matrix" id="stageMicGridMatrix">
                  <button
                    v-for="preset in boardPresets"
                    :key="`mic-${preset.id}`"
                    type="button"
                    class="matrix-btn"
                    :class="{ active: selectedMicPreset === preset.id }"
                    :aria-label="`麥克風：${t(preset.labelKey)}`"
                    @click="selectMicPreset(preset.id)"
                  ></button>
                </div>
                <div style="font-size: 12px; color: var(--text-tertiary); line-height: 1.5;">
                  麥克風按鈕的位置會與右側舞台預覽同步，避免遮擋人物或看板。
                </div>
              </div>
              <div class="stage-position-sliders">
                <label for="stage-mic-x">水平位置 {{ selectedMicX }}%</label>
                <input id="stage-mic-x" type="range" class="std-range" min="0" max="100" step="1" v-model.number="selectedMicX" @input="markMicPositionCustom">
                <label for="stage-mic-y">垂直位置 {{ selectedMicY }}%</label>
                <input id="stage-mic-y" type="range" class="std-range" min="0" max="100" step="1" v-model.number="selectedMicY" @input="markMicPositionCustom">
              </div>
            </div>

            <div class="stage-open-board-controls" style="border-top: 1px solid var(--border-subtle); padding-top: 14px;">
              <span style="font-size: 13px; font-weight: 600; display: block; margin-bottom: 8px;">
                <i class="bi bi-layout-sidebar-inset-reverse" style="color: var(--brand-light);"></i> 展開看板按鈕位置
              </span>
              <div class="stage-position-sliders">
                <label for="stage-board-open-x">水平位置 {{ selectedBoardOpenX }}%</label>
                <input id="stage-board-open-x" type="range" class="std-range" min="0" max="100" step="1" v-model.number="selectedBoardOpenX">
                <label for="stage-board-open-y">垂直位置 {{ selectedBoardOpenY }}%</label>
                <input id="stage-board-open-y" type="range" class="std-range" min="0" max="100" step="1" v-model.number="selectedBoardOpenY">
              </div>
            </div>
          </section>

          <!-- 右欄：大尺寸 9:16 舞台即時對照全景視窗 (滿板震撼) -->
          <section class="stage-live-preview-card stage-layout-preview">
            <span style="font-size: 14px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
              <i class="bi bi-eye-fill" style="color: var(--brand-light);"></i> 9:16 舞台即時對照全景 (所見即所得)
            </span>
            <div
              ref="stagePreviewRef" data-composer-canvas
              class="interactive-large-stage stage-direct-editor standalone-stage-preview"
              :data-board-style="selectedBoardStyle"
              @pointermove="moveStageDirectEdit"
              @pointerup="finishStageDirectEdit"
              @pointercancel="finishStageDirectEdit"
            >
              <img
                v-if="stageScenePreviewUrl"
                class="stage-preview-avatar"
                :src="stageScenePreviewUrl"
                :alt="`${stagePreviewAvatarName} 數位人舞台預覽`"
              >
              <div v-else class="mini-avatar-shape"></div>
              <div class="stage-preview-mode"><span class="stage-preview-mode-dot"></span><span>點擊開始收音</span></div>
              <!-- 即時同步的浮動看板 -->
              <div
                class="mini-board-rect stage-preview-float-board"
                id="miniBoardRect"
                :class="`board-style-${selectedBoardStyle}`"
                :style="stagePreviewBoardStyle"
                role="button"
                tabindex="0"
                aria-label="拖曳調整看板位置"
                @pointerdown.stop.prevent="startStageDirectEdit('board', $event)"
              >
                <div class="stage-preview-board-header">
                  <span>回答看板</span>
                  <span class="stage-preview-count-pill">預覽</span>
                </div>
                <div class="stage-preview-board-content">
                  <span class="stage-preview-kicker">ON SCREEN</span>
                  <strong>第一次展示，準備這四件事</strong>
                  <span class="stage-preview-source">控制台預覽 · 對位置與大小</span>
                  <span class="stage-preview-item"><b>01</b> 選擇看板位置，避免遮擋人物與字幕。</span>
                  <span class="stage-preview-item"><b>02</b> 拖曳整張看板即可移動。</span>
                </div>
              </div>
              <button
                type="button"
                class="stage-preview-board-open"
                :style="stagePreviewBoardOpenPresentation.style"
                :data-edge="stagePreviewBoardOpenPresentation.edge"
                aria-label="拖曳調整展開看板按鈕位置"
                @pointerdown.stop.prevent="startStageDirectEdit('board-open', $event)"
              ><span class="stage-board-open-icon" aria-hidden="true">{{ stagePreviewBoardOpenPresentation.icon }}</span> 展開看板</button>
              <ConversationComposer v-if="composerDraft.composer_enabled" stage preview :settings="composerDraft" :enabled="true"
                style="z-index:6;cursor:grab;touch-action:none" @pointerdown.stop.prevent="startStageDirectEdit('composer', $event)" />
              <div class="stage-preview-mic-wrap" :style="stagePreviewMicStyle">
                <button
                  type="button"
                  class="stage-preview-mic"
                  aria-label="拖曳調整麥克風位置"
                  @pointerdown.stop.prevent="startStageDirectEdit('mic', $event)"
                >
                  <span class="stage-preview-ring"></span><span class="stage-preview-ring second"></span>
                  <i class="bi bi-mic-fill"></i>
                </button>
                <span class="stage-preview-mic-hint">直接說話</span>
              </div>
              <div
                class="stage-preview-captions"
                :style="stagePreviewCaptionStyle"
                role="button"
                tabindex="0"
                aria-label="拖曳調整即時字幕帶展示區域"
                @pointerdown.stop.prevent="startStageDirectEdit('caption', $event)"
              >
                <span class="stage-preview-said">準備好後，直接開始對話</span>
                <div class="stage-preview-reply">「即時字幕帶展示區域」</div>
              </div>
            </div>
            <span style="font-size: 11.5px; color: var(--text-tertiary);">
              可直接拖曳看板、麥克風或展開看板按鈕；放開後會套用並保存到數位人舞台。亦可用左側滑桿微調。
            </span>
          </section>
        </div>

        <div v-show="activeSettingsTab === 'interaction'" class="settings-category-panel" id="catPanel-interaction" role="tabpanel" aria-labelledby="railTab-interaction">
          <section class="setting-card">
            <div class="card-title-row"><div><h2 class="card-title-text">訪客互動</h2><p class="card-subtitle-desc">管理訪客何時開始說話、何時送出，以及上一場對話何時清除。</p></div><button type="button" class="btn-apply-primary" :disabled="applyingVisitor || visitorResetError" @click="handleApplyVisitorSettings">套用訪客清場時間</button></div>
            <div class="setting-form-row">
              <div class="field-label-group">
                <label for="visitor-idle-reset-seconds" class="field-main-label">訪客對話重置時間</label>
                <span class="field-sub-hint">完整重置清除本場記憶、附件與草稿並返回主角色；舞台空場後再等招呼間隔。</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    id="visitor-idle-reset-seconds"
                    type="number"
                    class="std-range"
                    min="3"
                    max="300"
                    step="1"
                    v-model.number="selectedVisitorResetSeconds"
                    :aria-invalid="visitorResetError"
                  >
                  <span class="std-val-pill">{{ selectedVisitorResetSeconds }} 秒</span>
                </div>
              </div>
            </div>

            <label class="field-main-label" for="clear-display-seconds">只清畫面時間（秒，保留記憶與附件）</label>
            <input id="clear-display-seconds" type="number" min="1" :max="selectedVisitorResetSeconds" v-model.number="selectedClearDisplaySeconds" class="std-input">
            <p v-if="visitorError" role="alert">{{ visitorError }}</p>
            <p>控制台與舞台各自依上述時間清畫面、清空對話並返回主數位人，停止、返回與收音操作不影響另一邊；閒置招呼只在舞台播放。</p>
          </section>
          <!-- 左欄：Silero VAD 免持收音 -->
          <section class="setting-card">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-soundwave"></i> Silero VAD 語音端點偵測</div>
                <div class="card-subtitle-desc">自動判斷發話開始與停頓；播放期間暫停收音，可點選插話。</div>
              </div>
              <button
                type="button"
                class="btn-apply-primary"
                style="padding: 6px 14px; font-size: 12px;"
                :disabled="applyingVad"
                @click="handleApplyVad"
              >
                <i class="bi bi-check2" :class="{ spin: applyingVad }"></i> 套用 VAD
              </button>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">啟用免持自動收音</span>
                <span class="field-sub-hint">開口即錄，停頓超過閥值自動送出</span>
              </div>
              <div class="field-control-area">
                <label class="std-switch">
                  <input type="checkbox" v-model="vadDraft.enabled">
                  <span class="std-slider-track"></span>
                </label>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">發話判定門檻 (Threshold)</span>
                <span class="field-sub-hint">閥值愈高抗噪愈佳，建議 0.45–0.55</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    type="range"
                    class="std-range"
                    min="0.1"
                    max="0.9"
                    step="0.05"
                    v-model.number="vadDraft.threshold"
                  >
                  <span class="std-val-pill">{{ vadDraft.threshold }}</span>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">最小靜音判定時間 (ms)</span>
                <span class="field-sub-hint">停頓超過此毫秒數即視為發話完畢</span>
              </div>
              <div class="field-control-area">
                <div class="std-slider-combo">
                  <input
                    type="range"
                    class="std-range"
                    min="200"
                    max="1500"
                    step="50"
                    v-model.number="vadDraft.min_silence_duration_ms"
                  >
                  <span class="std-val-pill">{{ vadDraft.min_silence_duration_ms }}ms</span>
                </div>
              </div>
            </div>
          </section>

        </div>

        <!-- ── 分類 4：語音活動與辨識 ── -->
        <div
          v-show="activeSettingsTab === 'voice'"
          class="settings-category-panel"
          id="catPanel-voice"
          role="tabpanel"
          aria-labelledby="railTab-voice"
        >
          <!-- 右欄：STT 與 TTS 雙引擎設定 -->
          <section class="setting-card">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-translate"></i> STT 語音辨識與 TTS 語音合成</div>
                <div class="card-subtitle-desc">配置音訊轉換模型與數位人播音音色。</div>
              </div>
              <div style="display: flex; gap: 8px;">
                <button
                  type="button"
                  class="btn-apply-primary"
                  style="padding: 6px 14px; font-size: 12px;"
                  :disabled="applyingStt"
                  @click="handleApplySpeech('stt')"
                >
                  <i class="bi bi-check2" :class="{ spin: applyingStt }"></i> 套用 STT
                </button>
                <button
                  type="button"
                  class="btn-apply-primary"
                  style="padding: 6px 14px; font-size: 12px;"
                  :disabled="applyingTts"
                  @click="handleApplySpeech('tts')"
                >
                  <i class="bi bi-check2" :class="{ spin: applyingTts }"></i> 套用 TTS
                </button>
              </div>
            </div>

            <!-- STT 引擎 -->
            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">STT 語音辨識引擎</span>
              </div>
              <div class="field-control-area">
                <select id="stt-engine" class="std-select" v-model="sttDraft.type">
                  <option
                    v-for="engine in sttEngineOptions"
                    :key="engine.id"
                    :value="engine.id"
                    :disabled="engine.available === false && engine.id !== sttDraft.type"
                  >
                    {{ engine.label || engine.id }}{{ engine.available === false ? '（未安裝）' : '' }}
                  </option>
                </select>
              </div>
            </div>

            <div class="setting-form-row" v-if="sttModelOptions.length">
              <div class="field-label-group">
                <label for="stt-model-size" class="field-main-label">辨識模型</label>
              </div>
              <div class="field-control-area">
                <select id="stt-model-size" class="std-select" v-model="sttDraft.model_size">
                  <option v-for="model in sttModelOptions" :key="model" :value="model">{{ model }}</option>
                </select>
              </div>
            </div>

            <!-- FunASR 繁簡字元集 -->
            <div class="setting-form-row" v-if="sttDraft.type === 'funasr'">
              <div class="field-label-group">
                <span class="field-main-label">輸出文字字元集</span>
              </div>
              <div class="field-control-area">
                <select class="std-select" v-model="sttDraft.output_script">
                  <option value="traditional-tw">繁體中文 (台灣正體)</option>
                  <option value="simplified">簡體中文</option>
                </select>
              </div>
            </div>

            <!-- STT 預熱進度條 -->
            <div
              v-if="applyingStt"
              class="stt-prewarm-progress"
              role="status"
              aria-live="polite"
              style="margin-bottom: 12px;"
            >
              <div
                class="progress-track"
                role="progressbar"
                :aria-label="t('settings.speech.prewarmProgressLabel')"
                :aria-valuetext="t('settings.speech.prewarming')"
              >
                <div class="progress-fill progress-fill-indeterminate"></div>
              </div>
              <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 4px;">
                {{ speech.stt.local_model_ready && sttDraft.type === 'funasr'
                  ? t('settings.speech.localPrewarmProgressHint')
                  : t('settings.speech.prewarmProgressHint') }}
              </p>
            </div>

            <!-- TTS 引擎 -->
            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">TTS 語音合成引擎</span>
                <span v-if="ttsDraft.type === 'edgetts'" class="field-sub-hint">開發用：使用 Microsoft Edge 朗讀功能的非公開端點，無正式商用授權；場域斷網即無法發聲。</span>
              </div>
              <div class="field-control-area">
                <select class="std-select" v-model="ttsDraft.type">
                  <option value="edgetts">Edge TTS (Development only) · 開發用</option>
                  <option value="breezyvoice">BreezyVoice (本機台灣華語 · 聲音複製)</option>
                </select>
              </div>
            </div>
            <!-- 設定檔或角色指到已移除的引擎時，伺服器已改用 Edge TTS -->
            <p v-if="speech.tts.notice" class="settings-error-banner" role="status">{{ speech.tts.notice }}</p>

            <!-- Edge TTS 聲線 -->
            <div class="setting-form-row" v-if="ttsDraft.type === 'edgetts'">
              <div class="field-label-group">
                <span class="field-main-label">播音音色 (Voice)</span>
              </div>
              <div class="field-control-area">
                <select class="std-select" v-model="ttsDraft.ref_file">
                  <option v-for="voice in edgeVoiceOptions" :key="voice.id" :value="voice.id">
                    {{ voice.name || voice.label || voice.id }}{{ voice.gender ? `（${voice.gender === 'female' ? '女聲' : '男聲'}）` : '' }}
                  </option>
                </select>
              </div>
            </div>

            <!-- BreezyVoice：音訊庫的參考錄音＋逐字稿，整段合成 -->
            <template v-if="ttsDraft.type === 'breezyvoice'">
              <div class="setting-form-row">
                <div class="field-label-group">
                  <label for="tts-breezyvoice-ref-text" class="field-main-label">參考語音逐字稿 *</label>
                  <span class="field-sub-hint">選取音訊庫錄音時會帶入它的逐字稿；上傳新錄音前先填好，逐字稿會一併存進音訊庫。錄音請用 8 秒內、乾淨的台灣華語，逐字稿須與整段錄音完全一致。</span>
                </div>
                <div class="field-control-area">
                  <textarea id="tts-breezyvoice-ref-text" class="chat-text-entry" v-model.trim="ttsDraft.ref_text" rows="2" placeholder="例如：您好，歡迎使用 Nova Avatar。"></textarea>
                </div>
              </div>
              <div class="setting-form-row">
                <div class="field-label-group">
                  <label for="tts-breezyvoice-model" class="field-main-label">{{ t('settings.speech.ttsModel') }}</label>
                  <span class="field-sub-hint">「自動」使用 models/BreezyVoice（由 scripts/breezyvoice_weights.py 下載）。</span>
                </div>
                <div class="field-control-area">
                  <select id="tts-breezyvoice-model" class="std-select" v-model="ttsDraft.model">
                    <option value="">{{ t('settings.speech.ttsModelAuto') }}</option>
                    <option v-for="model in ttsModelOptions" :key="model.id" :value="model.id">{{ model.id }}</option>
                  </select>
                </div>
              </div>
            </template>

            <!-- 參考音訊（非 Edge-TTS 時）：只能從伺服器的音訊庫選擇或上傳 -->
            <div class="setting-form-row" v-if="ttsDraft.type !== 'edgetts'">
              <div class="field-label-group">
                <label for="tts-voice-library" class="field-main-label">{{ t('settings.speech.reference') }}</label>
                <span class="field-sub-hint">{{ t('settings.speech.voiceLibraryDesc') }}</span>
              </div>
              <div class="field-control-area">
                <div class="input-group">
                  <select id="tts-voice-library" class="std-select" v-model="ttsDraft.ref_file" :disabled="voiceLibraryBusy">
                    <option value="">{{ t('settings.speech.voiceLibraryChoose') }}</option>
                    <option v-for="voice in ttsVoiceOptions" :key="voice.id" :value="voice.id">{{ voice.name }}（{{ voice.seconds }} 秒）</option>
                  </select>
                  <button type="button" class="btn btn-outline-secondary" :disabled="voiceLibraryBusy" @click="voiceFileInput?.click()">{{ t('settings.speech.voiceLibraryUpload') }}</button>
                  <button type="button" class="btn btn-outline-secondary" :disabled="voiceLibraryBusy || !ttsDraft.ref_file" @click="removeSelectedVoice">{{ t('settings.speech.voiceLibraryDelete') }}</button>
                </div>
                <input ref="voiceFileInput" type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a,.webm" hidden @change="onVoiceFileChosen">
              </div>
            </div>
          </section>
        </div>

        <!-- ── 分類 5：系統偏好與自訂 ── -->
        <div
          v-show="activeSettingsTab === 'experience'"
          class="settings-category-panel"
          id="catPanel-experience"
          role="tabpanel"
          aria-labelledby="railTab-experience"
        >
          <section class="setting-card">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-palette-fill"></i> 外觀主題與操作語系</div>
                <div class="card-subtitle-desc">自訂控制台視覺風格與介面繁簡語言。</div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">介面色彩主題</span>
                <span class="field-sub-hint">目前套用的主題會以紫色外框標示。</span>
              </div>
              <div class="field-control-area">
                <div class="grid-options-row theme-choice-grid" role="radiogroup" aria-label="介面色彩主題">
                  <button
                    v-for="theme in themeOptions"
                    :key="theme.id"
                    type="button"
                    class="option-card-btn theme-choice-card"
                    :class="{ selected: selectedThemeValue === theme.id }"
                    :aria-checked="selectedThemeValue === theme.id"
                    role="radio"
                    @click="selectTheme(theme.id)"
                  >
                    <span class="opt-title">{{ theme.icon }} {{ theme.label }}</span>
                    <span class="opt-detail">{{ theme.desc }}</span>
                  </button>
                </div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">介面語系 (Language)</span>
              </div>
              <div class="field-control-area">
                <select class="std-select" v-model="settings.uiLanguage" @change="onLanguageChange">
                  <option value="zh-TW">繁體中文 (台灣正體)</option>
                  <option value="en-US">English (US)</option>
                </select>
              </div>
            </div>
          </section>

          <section class="setting-card">
            <div class="card-title-row">
              <div>
                <div class="card-title-text"><i class="bi bi-speedometer"></i> 診斷監控與錄製配置</div>
                <div class="card-subtitle-desc">效能除錯輔助與本機影片封裝選項。</div>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">顯示即時除錯監控浮層</span>
                <span class="field-sub-hint">即時顯示 WebRTC 封包遺失率、FPS 與延遲統計</span>
              </div>
              <div class="field-control-area">
                <label class="std-switch">
                  <input type="checkbox" v-model="settings.showDebugPanel">
                  <span class="std-slider-track"></span>
                </label>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">訊息精確時間戳記</span>
                <span class="field-sub-hint">在每條對話氣泡旁標注發送與接收時間</span>
              </div>
              <div class="field-control-area">
                <label class="std-switch">
                  <input type="checkbox" v-model="settings.showTimestamp">
                  <span class="std-slider-track"></span>
                </label>
              </div>
            </div>

            <div class="setting-form-row">
              <div class="field-label-group">
                <span class="field-main-label">影片錄製封裝格式</span>
              </div>
              <div class="field-control-area">
                <select class="std-select" v-model="settings.recordFormat">
                  <option value="mp4">MP4 (H.264 · 廣泛相容)</option>
                  <option value="webm">WebM (VP8/VP9)</option>
                </select>
              </div>
            </div>
          </section>
        </div>

      </div>

      <!-- 滿板固定底部動作條 -->
      <footer v-show="!['roles', 'greeting', 'conversation'].includes(activeSettingsTab)" class="settings-fixed-footer">
        <button v-if="activeSettingsTab === 'experience'" type="button" class="btn-restore-gray" @click="confirmKind = 'reset'">
          <i class="bi bi-arrow-counterclockwise"></i> 還原系統偏好預設
        </button>
        <div class="footer-right-actions">
          <span class="dirty-badge-text" id="dirtyIndicator" v-if="hasUnsavedChanges">
            <i class="bi bi-exclamation-circle-fill"></i> 有未儲存的變更
          </span>
          <button type="button" class="btn-apply-primary" :disabled="savingSettings || pageInvalid" @click="saveActiveSettings">
            <i class="bi bi-check-lg"></i> 儲存並套用本頁設定
          </button>
        </div>
      </footer>
    </main>

    <!-- 確認對話方塊 -->
    <transition name="fade">
      <div v-if="confirmKind" class="confirm-dialog-overlay" @click="confirmKind = ''">
        <div class="confirm-dialog" @click.stop role="dialog" aria-modal="true">
          <div class="confirm-header">
            <i class="bi bi-exclamation-triangle"></i>
            <h4>{{ confirmDialogTitle }}</h4>
          </div>
          <div class="confirm-body">
            {{ confirmDialogMessage }}
          </div>
          <div class="confirm-footer">
            <button type="button" class="btn-secondary" @click="confirmKind = ''">{{ t('settings.cancel') }}</button>
            <button
              type="button"
              :class="['reset', 'delete-avatar', 'delete-background', 'purge-avatar'].includes(confirmKind) ? 'btn-danger' : 'btn-primary'"
              @click="confirmAction"
            >
              {{ t('settings.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </transition>

  </div>
</template>

<script setup>
import ConversationComposer from './ConversationComposer.vue'
import ConversationPanel from './ConversationPanel.vue'
import { composerGeometry } from '../conversationAttachments.js'
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from '../composables/useI18n'
import { useRuntimeSettings } from '../composables/useRuntimeSettings'
import { avatarScenePreviewUrl } from '../scenePreview.js'
import AvatarProfiles from './AvatarProfiles.vue'
import IdleGreetingSettings from './IdleGreetingSettings.vue'
import {
  boardReopenPresentation,
  captionStyle,
  micStyle,
  placeStageBoard,
  previewScale,
  STAGE_CAPTION_RATIO
} from '../stageBoardLayout.js'
import { LEGACY_STORAGE_KEYS, STORAGE_KEYS, readMigratedStorage } from '../storageKeys.js'

const { t, setLocale } = useI18n()
const props = defineProps({
  sessionId: { type: Number, default: 0 },
  isConnected: {
    type: Boolean,
    default: false
  },
  currentTheme: {
    type: String,
    default: 'obsidian'
  },
  initialTab: {
    type: String,
    default: 'roles'
  }
})

const emit = defineEmits([
  'settings-changed',
  'notification',
  'request-disconnect',
  'avatar-ready',
  'switch-theme',
  'close-settings',
  'conversation-summary'
])

const showSettings = ref(true)
const isFullBleed = ref(true)
const activeSettingsTab = ref(['ai', 'rag', 'roles'].includes(props.initialTab) ? 'roles' : props.initialTab || 'roles')
const profilesRef = ref(null)
const greetingRef = ref(null)
const greetingVisited = ref(props.initialTab === 'greeting')
const roleInitialSection = ref(props.initialTab === 'rag' ? 'rag' : props.initialTab === 'ai' ? 'model' : 'identity')
const settingsContentRef = ref(null)
const confirmKind = ref('')
const stagePreviewRef = ref(null)
const stagePreviewSize = ref({ width: 405, height: 720 })
let stagePreviewObserver = null
const stageDirectEditTarget = ref('')
const stageBoardStyles = [
  { id: 'glass', icon: '🪟', label: '毛玻璃視窗', desc: '半透霧面高雅質感' },
  { id: 'slate', icon: '🎬', label: '場記板', desc: '實色底與高對比色條' },
  { id: 'cue', icon: '🏷️', label: '廣播字卡', desc: '獨立懸浮條目小卡' }
]

const themeOptions = [
  { id: 'obsidian', icon: '🌙', label: '深色模式', desc: '低眩光的控制台深色介面' },
  { id: 'bento', icon: '☀️', label: '淺色模式', desc: '明亮、高對比的設定介面' }
]

const boardPresets = [
  { id: 'tl', labelKey: 'settings.stage.posTl' },
  { id: 'tc', labelKey: 'settings.stage.posTc' },
  { id: 'tr', labelKey: 'settings.stage.posTr' },
  { id: 'ml', labelKey: 'settings.stage.posMl' },
  { id: 'mc', labelKey: 'settings.stage.posMc' },
  { id: 'mr', labelKey: 'settings.stage.posMr' },
  { id: 'bl', labelKey: 'settings.stage.posBl' },
  { id: 'bc', labelKey: 'settings.stage.posBc' },
  { id: 'br', labelKey: 'settings.stage.posBr' }
]

const {
  runtime,
  loadingSettings,
  applyingAvatar,
  applyingStage,
  backgrounds,
  loadBackgrounds,
  uploadBackground,
  selectBackground,
  deleteBackground,
  restoreBackground,
  deleteCharacter,
  archivedCharacters,
  loadArchivedCharacters,
  restoreCharacter,
  permanentlyDeleteCharacter,
  applyMouthQuality,
  qualityDraft,
  qualityDirty,
  applyingQuality,
  qualityError,
  settingsError,
  stageError,
  selectedEngine,
  selectedAvatarId,
  selectedStageCaptionMaxChars,
  selectedVisitorResetSeconds,
  selectedClearDisplaySeconds,
  composerDraft,
  visitorResetError,
  visitorDirty,
  visitorError,
  applyingVisitor,
  applyVisitorSettings,
  selectedCaptionX,
  selectedCaptionY,
  selectedCaptionWidth,
  selectedBoardStyle,
  selectedBoardWidth,
  selectedBoardHeight,
  selectedBoardTransparency,
  selectedBoardX,
  selectedBoardY,
  selectedBoardPreset,
  selectedBoardPreview,
  isStageConfiguring,
  selectedBoardOpenX,
  selectedBoardOpenY,
  selectedMicX,
  selectedMicY,
  selectedMicPreset,
  boardSizeError,
  selectBoardPreset,
  markBoardPositionCustom,
  selectMicPreset,
  markMicPositionCustom,
  stageCaptionLengthError,
  filteredCharacters,
  stageDirty,
  avatarDirty,
  loadRuntimeSettings,
  loadOllamaModels,
  applyStageSettings,
  applyAvatar,
  importCharacter,
  importing,
  importJob,
  importError,
  selectEngine,
  selectCharacter,
  vad,
  vadDraft,
  vadDirty,
  vadError,
  applyingVad,
  applyVadSettings,
  speech,
  sttDraft,
  ttsDraft,
  sttDirty,
  sttEngineOptions,
  sttModelOptions,
  ttsDirty,
  edgeVoiceOptions,
  ttsVoiceOptions,
  ttsModelOptions,
  voiceLibraryBusy,
  uploadTtsVoice,
  deleteTtsVoice,
  applyingStt,
  applyingTts,
  applySttSettings,
  applyTtsSettings
} = useRuntimeSettings()

const voiceFileInput = ref(null)

async function onVoiceFileChosen(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const voice = await uploadTtsVoice(file, '', ttsDraft.type === 'breezyvoice' ? ttsDraft.ref_text : '')
    ttsDraft.ref_file = voice.id
    emit('notification', '參考音訊已加入音訊庫', 'success')
  } catch (error) { emit('notification', error.message, 'error') }
}

async function removeSelectedVoice() {
  try {
    await deleteTtsVoice(ttsDraft.ref_file)
    emit('notification', '參考音訊已移入回收桶', 'success')
  } catch (error) { emit('notification', error.message, 'error') }
}

const currentBoardStyleLabel = computed(() => {
  const s = stageBoardStyles.find(item => item.id === selectedBoardStyle.value)
  return s ? s.label : '毛玻璃'
})

const settingsTabs = computed(() => [
  { id: 'conversation', icon: 'bi bi-chat-square-text', label: '對話記憶與語系' },
  { id: 'roles', icon: 'bi bi-people-fill', label: '數位人、AI 與知識設定' },
  { id: 'greeting', icon: 'bi bi-chat-heart', label: '閒置招呼' },
  { id: 'interaction', icon: 'bi bi-mic', label: '訪客互動' },
  { id: 'avatar', icon: 'bi bi-person-video3', label: '數位人與畫質', badge: selectedEngine.value === 'musetalk' ? 'MuseTalk' : 'Wav2Lip · Research' },
  { id: 'stage', icon: 'bi bi-badge-cc-fill', label: '舞台與看板排版', badge: currentBoardStyleLabel.value },
  { id: 'voice', icon: 'bi bi-soundwave', label: '語音辨識與合成' },
  { id: 'experience', icon: 'bi bi-palette-fill', label: '系統偏好與自訂' }
])

const stagePreviewAvatar = computed(() => {
  const avatarId = selectedAvatarId.value || runtime.avatar.avatar_id
  return runtime.characters.find((character) => character.id === avatarId) || null
})

const stageScenePreviewUrl = computed(() => avatarScenePreviewUrl(
  stagePreviewAvatar.value,
  runtime.stage?.background_id
))

const stagePreviewAvatarName = computed(() => (
  stagePreviewAvatar.value?.label || stagePreviewAvatar.value?.name || stagePreviewAvatar.value?.id || '目前數位人'
))

const stagePreviewBoardStyle = computed(() => {
  const stageWidth = stagePreviewSize.value.width
  const stageHeight = stagePreviewSize.value.height
  const scale = previewScale(stageWidth, stageHeight)
  const box = placeStageBoard({
    stageW: stageWidth,
    stageH: stageHeight,
    targetW: Number(selectedBoardWidth.value),
    targetH: Number(selectedBoardHeight.value),
    x: Number(selectedBoardX.value),
    y: Number(selectedBoardY.value),
    scale,
    captionRatio: STAGE_CAPTION_RATIO
  })
  return {
    top: `${box.top}px`,
    left: `${box.left}px`,
    width: `${box.width}px`,
    height: `${box.height}px`,
    opacity: Math.max(0.2, 1 - Number(selectedBoardTransparency.value) / 100)
  }
})

const stagePreviewMicStyle = computed(() => micStyle(selectedMicX.value, selectedMicY.value))
const stagePreviewBoardOpenPresentation = computed(() => boardReopenPresentation(
  selectedBoardOpenX.value,
  selectedBoardOpenY.value
))
const stagePreviewCaptionStyle = computed(() => captionStyle(
  selectedCaptionX.value,
  selectedCaptionY.value,
  selectedCaptionWidth.value
))

const measureStagePreview = () => {
  const stageNode = stagePreviewRef.value
  if (!stageNode?.clientWidth || !stageNode?.clientHeight) return
  stagePreviewSize.value = { width: stageNode.clientWidth, height: stageNode.clientHeight }
}

const observeStagePreview = () => {
  stagePreviewObserver?.disconnect()
  if (!window.ResizeObserver) return
  stagePreviewObserver = new ResizeObserver(measureStagePreview)
  if (stagePreviewRef.value) stagePreviewObserver.observe(stagePreviewRef.value)
  measureStagePreview()
}

const composerFields = [
  { key:'composer_x', label:'輸入框水平位置', min:0, max:100, unit:'%' },
  { key:'composer_y', label:'輸入框垂直位置', min:0, max:100, unit:'%' },
  { key:'composer_width', label:'輸入框寬度', min:40, max:100, unit:'%' },
  { key:'composer_height', label:'輸入框高度', min:120, max:480, unit:'px' },
  { key:'composer_font_size', label:'輸入框字級', min:12, max:28, unit:'px' },
  { key:'composer_opacity', label:'輸入框背景不透明度', min:0, max:100, unit:'%' }
]

const clampPercent = (value) => Math.max(0, Math.min(100, Math.round(value)))

const startStageDirectEdit = (target, event) => {
  stageDirectEditTarget.value = target
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

const moveStageDirectEdit = (event) => {
  const target = stageDirectEditTarget.value
  const rect = stagePreviewRef.value?.getBoundingClientRect()
  if (!target || !rect?.width || !rect?.height) return

  if (target === 'composer') {
    const box = composerGeometry(composerDraft, stagePreviewSize.value.width, stagePreviewSize.value.height)
    composerDraft.composer_x = clampPercent(((event.clientX - rect.left) / rect.width * stagePreviewSize.value.width - box.width / 2 - box.pad) / Math.max(1, stagePreviewSize.value.width - box.width - box.pad * 2) * 100)
    composerDraft.composer_y = clampPercent(((event.clientY - rect.top) / rect.height * stagePreviewSize.value.height - box.height / 2 - box.pad) / Math.max(1, stagePreviewSize.value.height - box.height - box.pad * 2) * 100)
    return
  }
  const x = ((event.clientX - rect.left) / rect.width) * 100
  const y = ((event.clientY - rect.top) / rect.height) * 100
  if (target === 'mic') {
    selectedMicX.value = clampPercent(x)
    selectedMicY.value = clampPercent(y)
    selectedMicPreset.value = 'custom'
    return
  }
  if (target === 'board-open') {
    selectedBoardOpenX.value = clampPercent(x)
    selectedBoardOpenY.value = clampPercent(y)
    return
  }
  if (target === 'caption') {
    selectedCaptionX.value = clampPercent(x)
    selectedCaptionY.value = clampPercent(y)
    return
  }

  const stageWidth = rect.width
  const stageHeight = rect.height
  const scale = previewScale(stageWidth, stageHeight)
  const box = placeStageBoard({
    stageW: stageWidth,
    stageH: stageHeight,
    targetW: Number(selectedBoardWidth.value),
    targetH: Number(selectedBoardHeight.value),
    x: Number(selectedBoardX.value),
    y: Number(selectedBoardY.value),
    scale,
    captionRatio: STAGE_CAPTION_RATIO
  })
  const stageX = ((event.clientX - rect.left) / rect.width) * stageWidth
  const stageY = ((event.clientY - rect.top) / rect.height) * stageHeight
  const maxX = Math.max(1, stageWidth - box.inset * 2 - box.width)
  const maxY = Math.max(1, stageHeight - box.captionH - box.inset - box.height)
  selectedBoardX.value = clampPercent(((stageX - box.inset - box.width / 2) / maxX) * 100)
  selectedBoardY.value = clampPercent(((stageY - box.inset - box.height / 2) / maxY) * 100)
  selectedBoardPreset.value = 'custom'
}

const finishStageDirectEdit = async () => {
  if (!stageDirectEditTarget.value) return
  stageDirectEditTarget.value = ''
  try {
    await applyStageSettings()
    emit('notification', '舞台位置已套用。', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const defaultSettings = {
  useStun: false,
  stunServer: 'stun:stun.miwifi.com:3478',
  customStunServer: '',
  autoRecord: false,
  recordFormat: 'mp4',
  showDebugPanel: false,
  showTimestamp: true,
  theme: 'obsidian',
  uiLanguage: 'zh-TW',
  videoSize: 100
}

const normalizeThemeValue = (theme) => (
  theme === 'bento' || theme === 'white' || theme === 'light' ? 'bento' : 'obsidian'
)

const settings = ref({ ...defaultSettings })
const selectedThemeValue = ref(normalizeThemeValue(props.currentTheme))

const selectSettingsTab = (tabId) => {
  if (tabId === 'greeting') greetingVisited.value = true
  if (tabId === 'ai' || tabId === 'rag') {
    roleInitialSection.value = tabId === 'rag' ? 'rag' : 'model'
    tabId = 'roles'
  }
  activeSettingsTab.value = tabId
  if (settingsContentRef.value) settingsContentRef.value.scrollTop = 0
}

const handleTabKeydown = (event, currentIndex) => {
  const lastIndex = settingsTabs.value.length - 1
  let nextIndex = currentIndex
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    nextIndex = currentIndex === lastIndex ? 0 : currentIndex + 1
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    nextIndex = currentIndex === 0 ? lastIndex : currentIndex - 1
  } else {
    return
  }
  event.preventDefault()
  selectSettingsTab(settingsTabs.value[nextIndex].id)
}

const handleApplyMouthQuality = async () => {
  try {
    await applyMouthQuality()
    emit('notification', t('notifications.qualityApplied'), 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleApplyStage = async () => {
  try {
    await applyStageSettings()
    emit('notification', t('notifications.stageSettingsUpdated'), 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleApplyAvatar = () => applyAvatarChange()

const applyAvatarChange = async () => {
  try {
    const data = await applyAvatar()
    if (data.pending) {
      emit('notification', '設定已儲存，待控制台與舞台皆斷線後套用。', 'success')
      return
    }
    emit('avatar-ready')
    emit('notification', t('notifications.avatarSwitched'), 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleApplyVisitorSettings = async () => {
  try {
    await applyVisitorSettings()
    emit('notification', '訪客清場時間已套用', 'success')
  } catch (error) { emit('notification', error.message, 'error') }
}

const handleApplyVad = async () => {
  try {
    vadDraft.type = 'silero'
    const data = await applyVadSettings()
    if (data.pending) {
      emit('notification', '收音設定已儲存，待兩端斷線後套用。', 'success')
      return
    }
    if (data.warmup_error) {
      emit('notification', data.warmup_error, 'warning')
      return
    }
    emit('notification', `${t('notifications.vadSwitched')}: Silero VAD`, 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleApplySpeech = (kind) => applySpeechChange(kind)

const applySpeechChange = async (kind) => {
  try {
    const apply = kind === 'stt' ? applySttSettings : applyTtsSettings
    const data = await apply()
    if (data.pending) {
      emit('notification', '設定已儲存，待控制台與舞台皆斷線後套用。', 'success')
      return
    }
    emit('notification', t(kind === 'stt' ? 'settings.speech.sttApplied' : 'settings.speech.ttsApplied'), 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const selectTheme = (theme) => {
  selectedThemeValue.value = theme
  settings.value.theme = theme
  emit('switch-theme', theme)
}

const onLanguageChange = () => {
  setLocale(settings.value.uiLanguage)
}

const syncTheme = (theme) => {
  selectedThemeValue.value = normalizeThemeValue(theme)
  settings.value.theme = selectedThemeValue.value
}

const savingSettings = ref(false)
const pageInvalid = computed(() => (activeSettingsTab.value === 'interaction' && visitorResetError.value) || (activeSettingsTab.value === 'stage' && (stageCaptionLengthError.value || boardSizeError.value)))
const hasUnsavedChanges = computed(() => {
  const states = {
    roles: profilesRef.value?.dirty || profilesRef.value?.pendingApply,
    greeting: greetingRef.value?.dirty,
    stage: stageDirty.value,
    interaction: visitorDirty.value || vadDirty.value,
    avatar: avatarDirty.value || qualityDirty.value,
    voice: sttDirty.value || ttsDirty.value
  }
  return Boolean(states[activeSettingsTab.value])
})

const saveActiveSettings = async () => {
  if (savingSettings.value) return
  savingSettings.value = true
  try {
    const tab = activeSettingsTab.value
    if (tab === 'stage' && stageDirty.value) await applyStageSettings()
    if (tab === 'interaction') {
      if (visitorDirty.value) await applyVisitorSettings()
      if (vadDirty.value) await applyVadSettings()
    }
    if (tab === 'avatar') {
      if (qualityDirty.value) await applyMouthQuality()
      if (avatarDirty.value) await applyAvatarChange()
    }
    if (tab === 'voice') {
      if (sttDirty.value) await applySpeechChange('stt')
      if (ttsDirty.value) await applySpeechChange('tts')
    }
    if (tab === 'experience') persistLocalSettings()
    emit('notification', '本頁設定已儲存並套用', 'success')
  } catch (err) { emit('notification', err.message, 'error') }
  finally { savingSettings.value = false }
}

const persistLocalSettings = () => {
  localStorage.setItem(STORAGE_KEYS.settings, JSON.stringify(settings.value))
  emit('settings-changed', settings.value)
}

const resetSettings = () => {
  settings.value = { ...defaultSettings }
  localStorage.removeItem(STORAGE_KEYS.settings)
  emit('settings-changed', settings.value)
  emit('notification', t('notifications.settingsReset'), 'success')
}

const importFile = ref(null)
const importAvatarId = ref('')
const importGreenScreen = ref(true)
const backgroundFileInput = ref(null)
const avatarToDelete = ref(null)
const archivedAvatarToDelete = ref(null)
const backgroundToDelete = ref(null)
const importFileInput = ref(null)
const importNamePlaceholder = computed(() => `${selectedEngine.value || 'avatar'}_custom`)
const canStartImport = computed(() => !!importFile.value && !importing.value && !applyingAvatar.value)

const onImportDragOver = () => {}
const onImportDrop = (event) => {
  const file = event.dataTransfer?.files?.[0]
  if (file) importFile.value = file
}
const onImportFileChange = (event) => {
  const file = event.target.files?.[0]
  importFile.value = file || null
}

const handleImportCharacter = async () => {
  if (!canStartImport.value) return
  try {
    const result = await importCharacter({
      file: importFile.value,
      engine: selectedEngine.value,
      avatarId: importAvatarId.value.trim(),
      greenScreen: importGreenScreen.value
    })
    await loadRuntimeSettings()
    selectedEngine.value = result.engine
    selectedAvatarId.value = result.avatar_id
    importFile.value = null
    importAvatarId.value = ''
    if (importFileInput.value) importFileInput.value.value = ''
    emit('notification', t('notifications.avatarImported'), 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleUploadBackground = async () => {
  try {
    const file = backgroundFileInput.value?.files?.[0]
    const item = await uploadBackground(file)
    await selectBackground(item.id)
    if (backgroundFileInput.value) backgroundFileInput.value.value = ''
    emit('notification', '背景已上傳並套用', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const handleSelectBackground = async (id) => {
  try {
    await selectBackground(id)
    emit('notification', id ? '背景已切換' : '已顯示原始畫面', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const requestDeleteBackground = (background) => {
  backgroundToDelete.value = background
  confirmKind.value = 'delete-background'
}

const handleDeleteBackground = async () => {
  try {
    await deleteBackground(backgroundToDelete.value.id)
    emit('notification', '背景已移至本機回收區', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  } finally {
    backgroundToDelete.value = null
  }
}

const handleRestoreBackground = async (archiveName) => {
  try {
    await restoreBackground(archiveName)
    emit('notification', '背景已復原', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const requestDeleteAvatar = (character) => {
  avatarToDelete.value = character
  confirmKind.value = 'delete-avatar'
}

const handleDeleteAvatar = async () => {
  try {
    await deleteCharacter(avatarToDelete.value.id)
    emit('notification', '數字人已移至本機封存', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  } finally {
    avatarToDelete.value = null
  }
}

const handleRestoreAvatar = async (archiveName) => {
  try {
    await restoreCharacter(archiveName)
    emit('notification', '數字人已復原', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  }
}

const requestPermanentlyDeleteAvatar = (item) => {
  archivedAvatarToDelete.value = item
  confirmKind.value = 'purge-avatar'
}

const handlePermanentlyDeleteAvatar = async () => {
  try {
    await permanentlyDeleteCharacter(archivedAvatarToDelete.value.archive_name)
    emit('notification', '數字人已永久刪除', 'success')
  } catch (error) {
    emit('notification', error.message, 'error')
  } finally {
    archivedAvatarToDelete.value = null
  }
}

const confirmDialogTitle = computed(() => {
  if (confirmKind.value === 'delete-background') return '刪除背景'
  if (confirmKind.value === 'delete-avatar') return '刪除數字人'
  if (confirmKind.value === 'purge-avatar') return '永久刪除數字人'
  if (confirmKind.value === 'avatar') return t('settings.avatar.confirmTitle')
  if (confirmKind.value === 'stt' || confirmKind.value === 'tts') return t('settings.speech.confirmTitle')
  return t('settings.confirmTitle')
})

const confirmDialogMessage = computed(() => {
  if (confirmKind.value === 'delete-background') return `將 ${backgroundToDelete.value?.label || ''} 移至本機背景回收區？之後可以復原。`
  if (confirmKind.value === 'delete-avatar') return `將 ${avatarToDelete.value?.label || avatarToDelete.value?.id || ''} 從角色庫移出並封存於本機？`
  if (confirmKind.value === 'purge-avatar') return `永久刪除 ${archivedAvatarToDelete.value?.avatar_id || ''}？回收區中的原片和角色素材都會移除，且無法復原。`
  if (confirmKind.value === 'avatar') return t('settings.avatar.confirmMessage')
  if (confirmKind.value === 'stt' || confirmKind.value === 'tts') return t('settings.speech.confirmMessage')
  return t('settings.confirmMessage')
})

const confirmAction = () => {
  const kind = confirmKind.value
  confirmKind.value = ''
  if (kind === 'reset') resetSettings()
  else if (kind === 'delete-background') handleDeleteBackground()
  else if (kind === 'delete-avatar') handleDeleteAvatar()
  else if (kind === 'purge-avatar') handlePermanentlyDeleteAvatar()
  else if (kind === 'avatar') applyAvatarChange()
  else if (kind === 'stt' || kind === 'tts') applySpeechChange(kind)
}

const loadRuntimePanel = async () => {
  const [runtimeResult] = await Promise.allSettled([
    loadRuntimeSettings(),
    loadOllamaModels()
  ])
  if (runtimeResult.status === 'fulfilled') {
    await loadBackgrounds().catch((error) => console.error('Failed to load backgrounds:', error))
    await loadArchivedCharacters().catch((error) => console.error('Failed to load archived avatars:', error))
    vadDraft.type = 'silero'
    if (vad.type !== 'silero' || (vad.enabled && vad.asr_mode !== 'server')) {
      await applyVadSettings().catch((error) => {
        console.error('Failed to normalize VAD settings:', error)
      })
    }
  } else {
    console.error('Failed to load runtime settings:', runtimeResult.reason)
  }
}

onMounted(() => {
  observeStagePreview()
  loadRuntimePanel()
  const savedSettings = readMigratedStorage(
    localStorage,
    STORAGE_KEYS.settings,
    LEGACY_STORAGE_KEYS.settings
  )
  if (savedSettings) {
    try {
      settings.value = { ...defaultSettings, ...JSON.parse(savedSettings) }
    } catch (e) {
      console.error(e)
    }
  }
  selectedThemeValue.value = normalizeThemeValue(props.currentTheme)
})

onUnmounted(() => {
  stagePreviewObserver?.disconnect()
})

watch(activeSettingsTab, (tab) => {
  isStageConfiguring.value = (tab === 'stage')
}, { immediate: true })

watch(settings, () => {
  emit('settings-changed', settings.value)
}, { deep: true })

watch(() => props.currentTheme, (t) => {
  if (t) selectedThemeValue.value = normalizeThemeValue(t)
})

const openSettings = (tab = 'roles') => {
  if (typeof tab === 'string') selectSettingsTab(tab)
  showSettings.value = true
}

const closeSettings = () => {
  emit('close-settings')
}

const toggleSettings = () => {
  showSettings.value = !showSettings.value
}

defineExpose({
  openSettings,
  closeSettings,
  toggleSettings,
  showSettings,
  isFullBleed,
  activeSettingsTab,
  selectSettingsTab,
  syncTheme
})
</script>

<style scoped>
.unified-role-panel { display: block; }
.settings-return-console { margin-top: 12px; }
.conversation-return-console { margin-bottom: 14px; }

.confirm-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
}

.confirm-dialog {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 24px;
  max-width: 440px;
  width: 90%;
  box-shadow: var(--shadow-lg);
}

.confirm-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  color: var(--warning);
  font-size: 18px;
}

.confirm-header h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.confirm-body {
  font-size: 13.5px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 20px;
}

.confirm-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.btn-secondary {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-default);
  color: var(--text-primary);
  font-size: 13px;
}

.btn-danger {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  background: var(--danger);
  color: #fff;
  border: none;
  font-size: 13px;
  font-weight: 600;
}

.stt-prewarm-progress {
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
}

.runtime-state-banner {
  min-height: 44px;
  margin-bottom: 16px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
}

.runtime-state-banner.error {
  color: var(--warning);
  background: var(--warning-surface);
  border-color: color-mix(in srgb, var(--warning) 45%, transparent);
}

.btn-retry {
  margin-left: auto;
  flex-shrink: 0;
  padding: 6px 12px;
  color: var(--text-primary);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  font-weight: 600;
}

.empty-state-card {
  min-height: 150px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  text-align: center;
  color: var(--text-tertiary);
  background: var(--bg-input);
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-md);
}

.empty-state-card i { font-size: 30px; color: var(--brand-light); }
.empty-state-card strong { color: var(--text-primary); }

.progress-track {
  height: 4px;
  width: 100%;
  background: var(--bg-surface);
  border-radius: 2px;
  overflow: hidden;
  position: relative;
}

.progress-fill-indeterminate {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 40%;
  background: linear-gradient(90deg, var(--brand), var(--brand-light));
  border-radius: 2px;
  animation: indeterminate 1.5s infinite ease-in-out;
}

@keyframes indeterminate {
  0% { left: -40%; }
  50% { left: 40%; width: 50%; }
  100% { left: 100%; width: 20%; }
}

@media (prefers-reduced-motion: reduce) {
  .progress-fill-indeterminate {
    animation: none;
    left: 0;
    width: 100%;
  }
}
</style>
