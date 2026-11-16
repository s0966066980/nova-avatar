<!--
Derived from Kedreamix/Linly-Talker-Stream.
Copyright [Linly-talker-stream@kedreamix].
Licensed under the Apache License, Version 2.0.

Substantially modified by HongXian0903, 2026.
See LICENSE and NOTICE.
-->
<template>
  <div class="app-root-shell" :data-sample="currentTheme">

    <!-- ══════════════════════════════════════════════════════════════
         1. 應用主頂部導航列 (App Top Navbar)
         ══════════════════════════════════════════════════════════════ -->
    <header class="app-navbar">
      <div class="nav-brand-group">
        <div class="nav-logo-box">
          <i class="bi bi-robot"></i>
        </div>
        <div class="nav-brand-title">
          <span>Nova Avatar</span>
        </div>
      </div>

      <!-- 主頁面 Tabs 切換：即時演播控制台 vs 滿板系統設定中心 -->
      <nav v-if="canRenderConsole" class="nav-main-tabs" aria-label="主要視圖切換">
        <button
          class="main-tab-link"
          id="btnViewConsole"
          :class="{ active: currentMainView === 'console' }"
          @click="switchMainView('console')"
        >
          <i class="bi bi-broadcast"></i>
          <span>即時演播控制台</span>
        </button>
        <button
          class="main-tab-link"
          id="btnViewSettings"
          :class="{ active: currentMainView === 'settings' }"
          @click="switchMainView('settings')"
        >
          <i class="bi bi-sliders2"></i>
          <span>系統設定中心</span>
        </button>
      </nav>

      <div v-if="canRenderConsole" class="nav-status-group">
        <div class="webrtc-chip">
          <span class="live-dot" :class="{ 'connected': isConnected }"></span>
          <span>{{ isConnected ? 'WebRTC 已連線' : (connectionStatus === 'connecting' ? '連線中...' : 'WebRTC 未連線') }}</span>
          <span style="color: var(--text-muted); font-family: var(--font-mono); font-size: 11px;">{{ sessionId > 0 ? '#' + sessionId : '—' }}</span>
        </div>
        <div class="voice-badge-pill" id="voiceStatusBadge">
          <i :class="isRecordingVoice ? 'bi bi-mic-fill' : 'bi bi-soundwave'"></i>
          <span>{{ voiceBadgeText || '語音待命' }}</span>
        </div>
        <button
          id="btnMaintenanceDrawer"
          type="button"
          class="sample-btn"
          :class="{ active: showMaintenanceDrawer }"
          @click="showMaintenanceDrawer = !showMaintenanceDrawer"
          title="開啟系統維護／工程診斷"
          style="padding: 5px 10px;"
        >
          <i class="bi bi-wrench-adjustable-circle"></i>
          <span>系統維護／工程診斷</span>
        </button>
        <button
          v-if="adminAuthEnabled && adminAuthenticated"
          type="button"
          class="sample-btn admin-logout-btn"
          id="btnAdminLogout"
          @click="handleAdminLogout"
        >
          <i class="bi bi-box-arrow-right"></i> 登出
        </button>
      </div>
    </header>

    <!-- 管理者驗證邊界：未通過驗證前不掛載控制台與 SettingsPanel -->
    <section
      v-if="adminAuthReady && adminAuthEnabled && !adminAuthenticated"
      class="admin-auth-gate"
      id="adminLoginGate"
      aria-label="管理者登入"
    >
      <form class="admin-auth-card" @submit.prevent="handleAdminLogin">
        <div class="admin-auth-header">
          <div class="nav-logo-box"><i class="bi bi-shield-lock"></i></div>
          <div>
            <h2>Nova Avatar 控制台登入</h2>
            <p>請輸入管理者密碼或 PIN 碼以存取設定與演播控制台</p>
          </div>
        </div>
        <label class="admin-auth-label" for="adminPasswordInput">管理者密碼</label>
        <input
          id="adminPasswordInput"
          v-model="adminPasswordInput"
          type="password"
          class="admin-auth-input"
          autocomplete="current-password"
          placeholder="輸入管理者密碼或 PIN"
          :disabled="adminLoggingIn"
        />
        <p v-if="adminLoginError" id="adminLoginError" class="admin-auth-error" role="alert">
          {{ adminLoginError }}
        </p>
        <button
          id="btnAdminLogin"
          type="submit"
          class="admin-auth-submit"
          :disabled="adminLoggingIn || !adminPasswordInput"
        >
          {{ adminLoggingIn ? '驗證中...' : '登入控制台' }}
        </button>
      </form>
    </section>
    <section v-else-if="!adminAuthReady" class="admin-auth-gate" aria-label="正在檢查服務狀態">
      <div class="admin-auth-card">
        <p style="margin: 0; color: var(--text-secondary);">正在確認控制台驗證狀態...</p>
      </div>
    </section>

    <!-- ══════════════════════════════════════════════════════════════
         2. 頁面視圖容器 (Page Views)
         ══════════════════════════════════════════════════════════════ -->
    <div class="app-viewport" v-if="canRenderConsole">

      <!-- ──────────────────────────────────────────────────────────
           頁面 A：即時演播控制台 (Studio Console View)
           ────────────────────────────────────────────────────────── -->
      <div class="page-view" :class="{ active: currentMainView === 'console' }" id="viewConsole">
        <div class="studio-layout">

          <!-- 左側：對話調度與互動區 (studio-chat-panel) -->
          <div class="studio-chat-panel">
            <div class="chat-sub-toolbar">
              <div class="mode-pills-wrap">
                <button
                  class="mode-pill-btn"
                  :class="{ active: activeMode === 'chat' }"
                  @click="activeMode = 'chat'"
                >
                  <i class="bi bi-chat-text"></i> 對話模式
                </button>
                <button
                  class="mode-pill-btn"
                  :class="{ active: activeMode === 'tts' }"
                  @click="activeMode = 'tts'"
                >
                  <i class="bi bi-volume-up"></i> 朗讀模式
                </button>
              </div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <button
                  class="sample-btn"
                  @click="clearChatHistory"
                  :disabled="!isConnected"
                  :title="isConnected ? t('chat.clearHistory') : t('notifications.connectFirst')"
                  style="padding: 4px 10px;"
                >
                  <i class="bi bi-trash"></i> 清空紀錄
                </button>
                <button
                  class="sample-btn"
                  @click="switchMainView('settings', 'stage')"
                  style="padding: 4px 10px;"
                >
                  <i class="bi bi-sliders"></i> 前往看板設定
                </button>
              </div>
            </div>

            <!-- 對話模式：對話訊息瀑布流 -->
            <div v-if="activeMode === 'chat'" class="chat-flow-container" id="chatFlowBox" ref="messagesRef">
              <div
                v-for="(msg, index) in chatMessages"
                :key="index"
                class="bubble-row"
                :class="msg.type === 'user' ? 'user' : 'ai'"
              >
                <div class="bubble-avatar">
                  <i :class="msg.type === 'user' ? 'bi bi-person-fill' : 'bi bi-robot'"></i>
                </div>
                <div class="bubble-card">
                  <div v-if="appSettings.showTimestamp && msg.time" style="font-size: 10.5px; opacity: 0.6; margin-bottom: 4px; font-family: var(--font-mono);">{{ msg.time }}</div>
                  <div v-html="renderMarkdown(msg.text)"></div>
                  <div
                    v-if="msg.type === 'ai' && msg.voiceTurnId && ragByTurn[msg.voiceTurnId]
                      && (ragByTurn[msg.voiceTurnId].status === 'unavailable'
                        || ragByTurn[msg.voiceTurnId].sources.length)"
                    class="rag-turn-status"
                  >
                    <div v-if="ragByTurn[msg.voiceTurnId].status === 'unavailable'" class="rag-turn-warning" role="status">
                      <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
                      {{ ragByTurn[msg.voiceTurnId].strictRefusal ? '知識庫暫時無法連線，已依嚴格依據模式拒答。' : '知識庫暫時無法連線，本輪沿用一般回答。' }}
                    </div>
                    <details v-else-if="ragByTurn[msg.voiceTurnId].sources.length" class="rag-turn-references">
                      <summary>檢索參考 · {{ ragByTurn[msg.voiceTurnId].sources.length }} 段</summary>
                      <ol>
                        <li v-for="(source, sourceIndex) in ragByTurn[msg.voiceTurnId].sources" :key="`${source.document_id}-${sourceIndex}`">
                          <strong>{{ source.document_name || '未命名文件' }}</strong>
                          <p>{{ source.content }}</p>
                        </li>
                      </ol>
                    </details>
                  </div>
                  <div v-if="msg.boardItems && msg.boardItems.length" class="inline-board-preview">
                    <div class="inline-board-title"><i class="bi bi-stars"></i> 看板同步資料：</div>
                    <ul class="inline-board-list">
                      <li v-for="(bItem, bIdx) in msg.boardItems" :key="bIdx">
                        <span class="num-tag">{{ String(bIdx + 1).padStart(2, '0') }}</span>
                        <span><strong>{{ bItem.title }}：</strong>{{ bItem.body }}</span>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>

              <div v-if="isThinking" class="bubble-row ai">
                <div class="bubble-avatar"><i class="bi bi-robot"></i></div>
                <div class="bubble-card">
                  <div style="display: flex; gap: 5px; align-items: center; padding: 4px 0;">
                    <span style="width: 7px; height: 7px; background: currentColor; border-radius: 50%; opacity: 0.4; animation: pulse 1.2s infinite ease-in-out;"></span>
                    <span style="width: 7px; height: 7px; background: currentColor; border-radius: 50%; opacity: 0.7; animation: pulse 1.2s infinite ease-in-out 0.2s;"></span>
                    <span style="width: 7px; height: 7px; background: currentColor; border-radius: 50%; opacity: 1.0; animation: pulse 1.2s infinite ease-in-out 0.4s;"></span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 朗讀模式 -->
            <div v-else-if="activeMode === 'tts'" style="flex: 1; display: flex; flex-direction: column; padding: 18px; gap: 12px; overflow-y: auto;">
              <div style="font-size: 14px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
                <i class="bi bi-file-text" style="color: var(--brand-light);"></i> {{ t('chat.ttsTitle') }}
              </div>
              <textarea
                v-model="ttsInput"
                class="std-textarea"
                :placeholder="isConnected ? t('chat.ttsInputPlaceholder') : t('chat.inputPlaceholderDisconnected')"
                :disabled="!isConnected"
                rows="10"
                style="flex: 1; resize: none;"
              ></textarea>
              <button
                class="btn-send-main"
                @click="sendTTSMessage"
                :disabled="!isConnected || !ttsInput.trim()"
                style="align-self: flex-end; padding: 10px 24px;"
              >
                <i class="bi bi-play-circle-fill"></i>
                <span>{{ t('chat.ttsButton') }}</span>
              </button>
            </div>

            <!-- 底部輸入操作塢 -->
            <div class="studio-input-dock" v-show="activeMode === 'chat'">
              <ConversationComposer ref="composerRef" v-model="chatInput" :session-id="sessionId" :client-id="clientId" :connected="isConnected"
                @accepted="onComposerAccepted" @editing="onComposerEditing" />
              <div class="input-actions-bar">
                <div class="vad-status-label">
                  <i class="bi bi-check-circle-fill" :style="{ color: isConnected ? 'var(--success)' : 'var(--text-muted)' }"></i>
                  <span>{{ isConnected ? (handsFreeTalk ? 'Silero VAD 免持聆聽就緒 · 靜音 650ms 自動送出' : '文字模式就緒 · 點選按住說話或輸入') : '管理模式就緒 · 未建立 WebRTC 音視訊連線（不佔用 GPU）' }}</span>
                </div>
                <div class="dock-buttons-wrap">
                  <button
                    class="btn-voice-push"
                    id="btnPushVoice"
                    :class="{ 'active-listening': isRecordingVoice }"
                    :disabled="!isConnected"
                    @mousedown="handleVoiceButtonPress"
                    @mouseup="handleVoiceButtonRelease"
                    @click="handleVoiceButtonClick"
                    @touchstart.prevent="handleVoiceButtonPress"
                    @touchend="handleVoiceButtonRelease"
                  >
                    <i class="bi bi-mic-fill"></i>
                    <span id="voicePushText">{{ voiceButtonLabel }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 右側：9:16 數位人展示舞台 (studio-stage-panel) -->
          <div class="studio-stage-panel">
            <div class="stage-sub-header">
              <div style="display: flex; align-items: center; gap: 6px;">
                <i class="bi bi-camera-video-fill" style="color: var(--brand-light);"></i>
                <span>數位人視訊舞台</span>
              </div>
              <span style="font-size: 11.5px; color: var(--text-tertiary);">{{ currentAvatarMeta }}</span>
            </div>

            <div class="stage-viewport-center">
              <div class="stage-ratio-box" ref="videoWrapperRef" :data-board-style="runtime.stage.board_style || 'glass'">
                <img
                  v-if="!isConnected && consoleScenePreviewUrl"
                  :src="consoleScenePreviewUrl"
                  :alt="`${currentAvatar.label || currentAvatar.name || currentAvatar.id} 數位人預覽`"
                  class="stage-avatar-preview"
                />
                <svg v-else-if="!isConnected" viewBox="0 0 200 320" style="position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;">
                  <ellipse cx="100" cy="115" rx="36" ry="46" fill="#94a3b8"/>
                  <path d="M45 320C40 250 55 195 80 175C90 167 110 167 120 175C145 195 160 250 155 320H45Z" fill="#1e293b"/>
                  <ellipse cx="88" cy="108" rx="4" ry="3" fill="#0f172a"/>
                  <ellipse cx="112" cy="108" rx="4" ry="3" fill="#0f172a"/>
                  <path d="M92 135Q100 144 108 135Q100 139 92 135Z" fill="#f43f5e"/>
                </svg>

                <video id="video" autoplay playsinline style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 1;" :style="{ opacity: isConnected ? 1 : 0 }"></video>

                <!-- 舞台回答看板 (浮層) -->
                <div
                  v-if="visibleBoard.items.length && !stageBoard.hidden"
                  class="board-float-window"
                  id="boardFloat"
                  :style="consoleBoardStyle"
                  style="z-index: 2;"
                >
                  <div class="board-window-header">
                    <span class="board-window-title"><i class="bi bi-layout-sidebar-reverse"></i> {{ visibleBoard.title || '回答看板' }}</span>
                    <button class="btn-board-x" @click="stageBoard.hidden = true">✕</button>
                  </div>
                  <ul class="board-window-items">
                    <li v-for="(item, index) in visibleBoard.items" :key="index">
                      {{ String(index + 1).padStart(2, '0') }}. {{ item.title }}{{ item.body ? `：${item.body}` : '' }}
                    </li>
                  </ul>
                </div>

                <button
                  v-if="visibleBoard.items.length"
                  class="board-open-pill"
                  id="boardOpenPill"
                  type="button"
                  :style="consoleBoardOpenPresentation.style"
                  :data-edge="consoleBoardOpenPresentation.edge"
                  :aria-pressed="!stageBoard.hidden"
                  style="z-index: 2;"
                  @click="stageBoard.hidden = !stageBoard.hidden"
                >
                  <span class="stage-board-open-icon" aria-hidden="true">{{ consoleBoardOpenPresentation.icon }}</span> {{ stageBoard.hidden ? '展開看板' : '收合看板' }} ({{ visibleBoard.items.length }}項)
                </button>

                <div v-if="stageCaptionText" class="stage-captions-sub" style="z-index: 2;">
                  「{{ stageCaptionText }}」
                </div>

                <div class="recording-badge" v-if="isRecording" style="position: absolute; top: 12px; left: 12px; background: rgba(239, 68, 68, 0.9); color: #fff; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; display: flex; align-items: center; gap: 6px; z-index: 3;">
                  <i class="bi bi-record-circle"></i>
                  {{ t('video.recording') }}
                </div>
              </div>
            </div>

            <div class="stage-dock-footer">
              <div class="stage-footer-actions">
                <button
                  v-if="!isConnected"
                  class="btn-stage-sub"
                  @click="handleStartConnection"
                  :disabled="!canConnect"
                  :title="connectDisabledTitle"
                >
                  <i class="bi bi-play-circle" v-if="canConnect"></i>
                  <i class="bi bi-hourglass-split spin" v-else-if="!backendReady"></i>
                  <i class="bi bi-sliders" v-else></i>
                  {{ connectButtonLabel }}
                </button>
                <button
                  v-else
                  class="btn-stage-sub connected-state"
                  id="btnToggleConn"
                  @click="handleStopConnection"
                >
                  <i class="bi bi-stop-circle"></i> 中斷連線
                </button>

                <button
                  v-if="isConnected && replyPlaybackState === 'blocked'"
                  type="button"
                  class="btn-stage-sub"
                  @click="resumePlayback"
                  :title="t('video.enableSoundHint')"
                >
                  <i class="bi bi-volume-up" aria-hidden="true"></i>
                  {{ t('video.enableSound') }}
                </button>

                <button
                  class="btn-stage-sub"
                  @click="isRecording ? handleStopRecord() : handleStartRecord()"
                  :disabled="!isConnected || recordExportProgress !== null"
                >
                  <i class="bi bi-record-circle" :style="{ color: isRecording ? 'var(--danger)' : '' }"></i>
                  {{ recordExportProgress !== null ? `正在匯出 ${recordExportProgress}%` : isRecording ? '停止錄影' : '開始錄影' }}
                </button>

                <button
                  v-if="lastRecordFile"
                  class="btn-stage-sub"
                  @click="downloadRecord"
                >
                  <i class="bi bi-download"></i>
                  下載錄影
                </button>
              </div>
              <button class="btn-stage-sub" @click="openStageWindow" title="在新分頁開啟獨立 9:16 舞台視窗">
                <i class="bi bi-box-arrow-up-right"></i> 獨立舞台視窗
              </button>
            </div>
          </div>

        </div>
      </div>

      <!-- ──────────────────────────────────────────────────────────
           頁面 B：★ 獨立滿板系統設定中心 (Full Bleed Settings Suite)
           ────────────────────────────────────────────────────────── -->
      <div class="page-view" :class="{ active: currentMainView === 'settings' }" id="viewSettings">
        <SettingsPanel
          ref="settingsPanelRef"
          :is-connected="isConnected || connectionStatus === 'connecting'"
          :current-theme="currentTheme"
          @settings-changed="onSettingsChanged"
          @notification="showNotification"
          @request-disconnect="handleStopConnection"
          @avatar-ready="onAvatarReady"
          @switch-theme="setDesignSample"
          @close-settings="switchMainView('console')"
          @open-maintenance="showMaintenanceDrawer = true"
        />
      </div>

    </div>

    <input type="hidden" id="sessionid" :value="sessionId">

    <!-- 系統維護／工程診斷抽屜 -->
    <aside
      v-if="canRenderConsole && showMaintenanceDrawer"
      id="maintenanceDrawer"
      class="maintenance-drawer"
      aria-label="系統維護／工程診斷"
    >
      <div class="maintenance-drawer-header">
        <span class="maintenance-drawer-title">
          <i class="bi bi-wrench-adjustable-circle"></i>
          系統維護／工程診斷
        </span>
        <button
          type="button"
          class="sample-btn"
          @click="showMaintenanceDrawer = false"
          aria-label="關閉系統維護／工程診斷"
          style="padding: 4px 10px;"
        >
          ✕
        </button>
      </div>
      <div class="maintenance-drawer-body">
        <VoiceTestPanel
          ref="voiceTestPanelRef"
          :session-id="sessionId"
          :connected="isConnected"
          :busy="isThinking || ['avatar_speaking', 'tail_guard'].includes(voiceState)"
          :voice-state="voiceState"
          @close="showMaintenanceDrawer = false"
          @started="handleVoiceTestStarted"
          @finished="handleVoiceTestFinished"
          @notification="showNotification"
        />
        <div class="maintenance-debug-section">
          <label class="maintenance-debug-toggle">
            <input type="checkbox" v-model="appSettings.showDebugPanel">
            <span>顯示即時除錯監控資訊</span>
          </label>
          <DebugPanel
            v-if="appSettings.showDebugPanel"
            :connection-status="connectionStatus"
            :session-id="sessionId"
          />
        </div>
      </div>
    </aside>

    <!-- 通知提示 -->
    <div class="notification-container">
      <transition-group name="notification">
        <div
          v-for="notification in notifications"
          :key="notification.id"
          class="notification"
          :class="notification.type"
        >
          <i :class="getNotificationIcon(notification.type)"></i>
          <span>{{ notification.message }}</span>
        </div>
      </transition-group>
    </div>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import DebugPanel from './components/DebugPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import VoiceTestPanel from './components/VoiceTestPanel.vue'
import ConversationComposer from './components/ConversationComposer.vue'
import { useWebRTC } from './composables/useWebRTC'
import { useI18n } from './composables/useI18n'
import { useRuntimeSettings } from './composables/useRuntimeSettings'
import { avatarScenePreviewUrl } from './scenePreview.js'
import { presentationPlayer, exportSceneRecording } from './prerecordedPlayer.js'
import { downloadMedia } from './mediaDownload.js'
import { applyTurnCommitted } from './consoleTurnCommit.js'
import { applyConsoleBoardEvent, createConsoleBoardState } from './consoleBoardState.js'
import { fetchAdminAuthStatus, loginAdmin, logoutAdmin } from './adminAuth.js'
import { boardReopenPresentation, placeStageBoard, STAGE_BOARD_PREVIEW_ITEMS, STAGE_BOARD_PREVIEW_TITLE } from './stageBoardLayout.js'
import { LEGACY_STORAGE_KEYS, STORAGE_KEYS, readMigratedStorage } from './storageKeys.js'
import { renderSafeMarkdown } from './sanitizeHtml.js'

const { t, setLocale, loadLocale } = useI18n()
const { vad, vadDraft, loadVadSettings, applyVadSettings, runtime, isStageConfiguring, selectedBoardPreview } = useRuntimeSettings()
const handsFreeTalk = computed(() => Boolean(vad.enabled))

// 對話文字清理函式：過濾協定標記與 JSON 格式，避免 [speech 等符號洩漏到介面
const sanitizeChatText = (text) => {
  if (!text) return ''
  let clean = String(text)
  // Strip tool-call tags and reasoning
  clean = clean.replace(/<\|tool_call_start\|>[\s\S]*?<\|tool_call_end\|>/g, '')
  clean = clean.replace(/<\|tool_call_start\|>[\s\S]*/g, '')
  clean = clean.replace(/<\|tool_call_end\|>/g, '')
  clean = clean.replace(/\[(?:BOARD|think|thought|speech)\([\s\S]*?\)?\]/g, '')

  // Strip mode markers
  clean = clean.replace(/\[{1,2}\s*MODE:\s*(?:SIMPLE|BOARD)\s*\]{1,2}/gi, '')
  clean = clean.replace(/模式\s*[:：]\s*(?:簡答|看板)/g, '')

  // Strip speech markers
  clean = clean.replace(/\[{1,2}\s*\/?\s*(?:SPEECH|speech)(?::\s*)?\]{1,2}/gi, '')
  clean = clean.replace(/\[{1,2}\s*(?:SPEECH|speech)\s*:\s*/gi, '')
  clean = clean.replace(/(?:^|[\r\n]+)\s*SPEECH\s*:\s*/gi, '\n')
  clean = clean.replace(/(?:^|[\r\n]+)\s*口語\s*[:：]\s*/g, '\n')

  // Strip board markers
  clean = clean.replace(/\[{1,2}\s*\/?\s*BOARD(?:_JSON)?(?::\s*)?\]{1,2}/gi, '')
  clean = clean.replace(/\[{1,2}\s*BOARD(?:_JSON)?\s*:\s*/gi, '')
  clean = clean.replace(/(?:^|[\r\n]+)\s*BOARD(?:_JSON)?\s*:\s*/gi, '\n')
  clean = clean.replace(/看板(?:資料)?\s*[:：]/g, '')
  clean = clean.replace(/資料\s*[:：]/g, '')

  // Strip end markers
  clean = clean.replace(/\[{1,2}\s*\/?\s*END\s*\]{1,2}/gi, '')

  // Cut off before raw JSON or markdown JSON fence
  const jsonMatch = clean.match(/(?:```(?:json)?\s*)?[\r\n]+\s*\{(?:\s*"title"|\s*"items"|\s*"summary")/i)
  if (jsonMatch && jsonMatch.index !== undefined) {
    clean = clean.slice(0, jsonMatch.index)
  }

  // Strip trailing unclosed bracket if [speech: was stripped
  if (clean.endsWith(']') && clean.split(']').length > clean.split('[').length) {
    clean = clean.slice(0, -1)
  }

  return clean.trim()
}

// Markdown 渲染函式
const renderMarkdown = (text) => {
  if (!text) return ''
  const clean = sanitizeChatText(text)
  if (!clean) return ''
  return renderSafeMarkdown(clean)
}

const sessionId = ref(0)
const connectionStatus = ref('disconnected')
const isRecording = ref(false)
const recordExportProgress = ref(null)
const activeMode = ref('chat')
const chatInput = ref('')
const composerRef = ref(null)
const onComposerAccepted = ({ text }) => { addMessage(text, 'user'); isThinking.value = true }
let composerCaptureBefore = null
const onComposerEditing = (editing) => {
  if (editing) {
    if (composerCaptureBefore === null) composerCaptureBefore = getCaptureRequested()
    setCaptureEnabled(false)
  } else if (composerCaptureBefore !== null) {
    if (isConnected.value) setCaptureEnabled(composerCaptureBefore)
    composerCaptureBefore = null
  }
}
const ttsInput = ref('')
const isThinking = ref(false)
const isRecordingVoice = ref(false)
const handsFreePaused = ref(false)
const voiceState = ref('disconnected')
const avatarSpeaking = computed(() => voiceState.value === 'avatar_speaking')
const messagesRef = ref(null)
const notifications = ref([])
let notificationIdCounter = 0
const lastRecordFile = ref(null)  // 最後一次錄製的檔案資訊

// 設定中心與導航參照
const settingsPanelRef = ref(null)
const currentMainView = ref('console')
const currentTheme = ref('obsidian')

const isSettingsCenterActive = computed(() => {
  return currentMainView.value === 'settings'
})
const openStudioView = () => {
  currentMainView.value = 'console'
}
const openSettingsCenter = (subTab = null) => {
  currentMainView.value = 'settings'
  if (subTab && settingsPanelRef.value?.selectSettingsTab) {
    settingsPanelRef.value.selectSettingsTab(subTab)
  }
}
const switchMainView = (viewKey, subTabKey = null) => {
  currentMainView.value = viewKey
  if (viewKey === 'settings' && subTabKey && settingsPanelRef.value?.selectSettingsTab) {
    settingsPanelRef.value.selectSettingsTab(subTabKey)
  }
}
const openStageWindow = () => {
  window.open('stage.html', '_blank')
}
const setDesignSample = (sampleKey) => {
  const isWhite = (sampleKey === 'bento' || sampleKey === 'white' || sampleKey === 'light')
  const resolvedKey = isWhite ? 'bento' : 'obsidian'
  currentTheme.value = resolvedKey
  document.body.setAttribute('data-sample', resolvedKey)
  document.documentElement.setAttribute('data-theme', isWhite ? 'light' : 'dark')
  localStorage.setItem(STORAGE_KEYS.designSample, resolvedKey)
  updateTheme(isWhite ? 'white' : 'dark')
  if (settingsPanelRef.value?.syncTheme) {
    settingsPanelRef.value.syncTheme(resolvedKey)
  }
}
const stageCaptionText = computed(() => {
  const lastAi = [...chatMessages.value].reverse().find(m => m.type === 'ai')
  if (!lastAi || !lastAi.text) return ''
  const clean = sanitizeChatText(lastAi.text)
  return clean.length > 80 ? clean.slice(-80) : clean
})

const currentAvatar = computed(() => {
  const characters = Array.isArray(runtime.characters) ? runtime.characters : []
  return characters.find(character => character.id === runtime.avatar?.avatar_id) || null
})

const consoleScenePreviewUrl = computed(() => avatarScenePreviewUrl(
  currentAvatar.value,
  runtime.stage?.background_id
))

const currentAvatarMeta = computed(() => {
  const avatar = currentAvatar.value
  if (!avatar) {
    return runtime.avatar?.type
      ? [runtime.avatar.avatar_id || '目前角色', runtime.avatar.type].filter(Boolean).join(' · ')
      : '尚未載入角色'
  }
  return [
    avatar.label || avatar.name || avatar.id,
    avatar.resolution,
    avatar.fps ? `${avatar.fps} FPS` : '',
    avatar.type || runtime.avatar?.type,
  ].filter(Boolean).join(' · ')
})

// 語音引擎狀態摘要 Badge
const voiceEngineBadge = computed(() => {
  const tts = runtime?.tts?.type
  const stt = runtime?.stt?.type
  if (!tts && !stt) return ''
  return `${tts ? 'TTS: ' + tts : ''}${tts && stt ? ' · ' : ''}${stt ? 'STT: ' + stt : ''}`
})

const voiceBadgeText = computed(() => {
  if (isRecordingVoice.value) return '聆聽使用者發話中'
  if (voiceState.value === 'avatar_speaking') return '數位人說話中'
  if (voiceEngineBadge.value) return voiceEngineBadge.value
  return isConnected.value ? '全雙工待命' : ''
})

const backendReady = ref(false)  // 後端是否就緒
const modelReady = ref(false)    // 是否已套用數字人引擎
const stageBoard = reactive(createConsoleBoardState())
const showMaintenanceDrawer = ref(false)
const voiceTestPanelRef = ref(null)
const videoWrapperRef = ref(null)
const videoSizeBox = reactive({ w: 400, h: 400 })
const visibleBoard = computed(() => {
  if (stageBoard.items.length) {
    return { title: stageBoard.title || '回答看板', items: stageBoard.items, preview: false }
  }
  if (isStageConfiguring.value && (selectedBoardPreview.value || runtime.stage?.board_preview)) {
    return { title: STAGE_BOARD_PREVIEW_TITLE, items: STAGE_BOARD_PREVIEW_ITEMS, preview: true }
  }
  return { title: '', items: [], preview: false }
})
const consoleBoardStyle = computed(() => {
  const stage = runtime.stage || {}
  const alpha = 1 - Number(stage.board_transparency ?? 28) / 100
  const box = placeStageBoard({
    stageW: videoSizeBox.w || 400,
    stageH: videoSizeBox.h || 400,
    targetW: Number(stage.board_width || 252),
    targetH: Number(stage.board_height || 300),
    x: Number(stage.board_x ?? 100),
    y: Number(stage.board_y ?? 0),
    scale: 1
  })
  return {
    width: `${box.width}px`,
    height: `${box.height}px`,
    left: `${box.left}px`,
    top: `${box.top}px`,
    transform: 'none',
    '--board-alpha': alpha,
    '--board-blur': `${alpha * 12}px`
  }
})

const consoleBoardOpenPresentation = computed(() => boardReopenPresentation(
  runtime.stage?.board_open_x ?? 50,
  runtime.stage?.board_open_y ?? 8
))

// 應用設定
const appSettings = ref({
  useStun: false,
  stunServer: 'stun:stun.miwifi.com:3478',
  customStunServer: '',
  autoRecord: false,
  recordFormat: 'mp4',
  showDebugPanel: false,
  showTimestamp: true,
  theme: 'dark',
  uiLanguage: 'zh-TW',
  videoSize: 100
})

const chatMessages = ref([])
const ragByTurn = reactive({})

// 每個語音 turn 保留最後接受的 LLM delta 序號；晚到或重複事件不得污染文字預覽。
const assistantStreamState = new Map()

const isConnected = computed(() => connectionStatus.value === 'connected')
const canConnect = computed(() => (
  backendReady.value
  && modelReady.value
  && connectionStatus.value !== 'connecting'
))
const connectButtonLabel = computed(() => {
  if (!backendReady.value) return t('video.backendStarting')
  if (!modelReady.value) return t('video.selectAvatarFirst')
  return t('video.connect')
})
const connectDisabledTitle = computed(() => {
  if (!backendReady.value) return t('tooltips.connectDisabled')
  if (!modelReady.value) return t('tooltips.selectAvatarFirst')
  return ''
})

const statusClass = computed(() => {
  return {
    'status-connected': connectionStatus.value === 'connected',
    'status-connecting': connectionStatus.value === 'connecting',
    'status-disconnected': connectionStatus.value === 'disconnected'
  }
})

const statusText = computed(() => {
  const statusMap = {
    'connected': t('header.status.connected'),
    'connecting': t('header.status.connecting'),
    'disconnected': t('header.status.disconnected')
  }
  return statusMap[connectionStatus.value] || t('header.status.disconnected')
})

const getVoiceButtonTitle = computed(() => {
  if (!isConnected.value) {
    return t('tooltips.voiceDisabled')
  }
  if (avatarSpeaking.value) return t('tooltips.voiceInterrupt')
  if (handsFreeTalk.value) {
    return isRecordingVoice.value ? t('tooltips.voiceRecording') : t('tooltips.voiceContinuous')
  }
  return t('tooltips.voiceHold')
})

const voiceButtonLabel = computed(() => {
  if (avatarSpeaking.value) return t('chat.voiceButtonInterrupt')
  if (handsFreeTalk.value) {
    return isRecordingVoice.value
      ? t('chat.voiceButtonRecordingContinuous')
      : t('chat.voiceButtonContinuous')
  }
  return isRecordingVoice.value
    ? t('chat.voiceButtonRecording')
    : t('chat.voiceButton')
})

const voiceStateLabel = computed(() => {
  const known = new Set([
    'preparing', 'listening', 'speech_detected', 'stt', 'llm', 'tts_ready',
    'avatar_speaking', 'tail_guard', 'paused', 'degraded', 'reconnecting', 'error'
  ])
  const key = known.has(voiceState.value) ? voiceState.value : 'paused'
  return t(`voiceStates.${key}`)
})

function getCurrentTime() {
  const now = new Date()
  return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`
}

// 通知系統
const showNotification = (message, type = 'info') => {
  const id = notificationIdCounter++
  const notification = { id, message, type }
  notifications.value.push(notification)

  // 3秒後自動移除
  setTimeout(() => {
    const index = notifications.value.findIndex(n => n.id === id)
    if (index > -1) {
      notifications.value.splice(index, 1)
    }
  }, 3000)
}

const getNotificationIcon = (type) => {
  switch (type) {
    case 'success': return 'bi bi-check-circle-fill'
    case 'error': return 'bi bi-x-circle-fill'
    case 'warning': return 'bi bi-exclamation-triangle-fill'
    default: return 'bi bi-info-circle-fill'
  }
}

const handleVoiceEvent = (event) => {
  composerRef.value?.receive(event)
  voiceTestPanelRef.value?.handleVoiceEvent(event)
  if (event.type === 'state') {
    voiceState.value = event.state
    isRecordingVoice.value = ['listening', 'speech_detected'].includes(event.state)
    isThinking.value = ['stt', 'retrieving', 'llm', 'tts_ready'].includes(event.state)
    if (event.state === 'error' && event.error) {
      const errorKey = {
        tts_error_before_commit: 'notifications.ttsErrorBeforeCommit',
        tts_error_after_commit: 'notifications.ttsErrorAfterCommit',
        playback_error_before_commit: 'notifications.playbackErrorBeforeCommit',
        playback_error_after_commit: 'notifications.playbackErrorAfterCommit',
        pipeline_error: 'notifications.pipelineError',
      }[event.error]
      showNotification(errorKey ? t(errorKey) : event.error, 'error')
    }
    return
  }
  if (event.type === 'rag_retrieval' && event.turn_id) {
    ragByTurn[event.turn_id] = {
      status: event.status,
      strictRefusal: Boolean(event.strict_refusal),
      sources: Array.isArray(event.sources) ? event.sources : []
    }
  } else if (event.type === 'turn_cancelled' && event.turn_id) {
    delete ragByTurn[event.turn_id]
  } else if (event.type === 'user_transcript' && event.text) {
    addMessage(event.text, 'user')
  } else if (event.type === 'assistant_response_start') {
    isThinking.value = true
    if (event.turn_id) {
      assistantStreamState.set(event.turn_id, { lastSequence: -1, done: false })
    }
    const duplicate = chatMessages.value.some(
      message => message.type === 'ai' && message.voiceTurnId === event.turn_id
    )
    if (!duplicate) {
      addMessage('', 'ai', { voiceTurnId: event.turn_id, streamingPreview: true })
    }
  } else if (event.type === 'assistant_response_delta' && event.text_delta) {
    isThinking.value = false
    const stream = event.turn_id ? assistantStreamState.get(event.turn_id) : null
    const sequence = Number(event.sequence)
    if (!stream || !Number.isInteger(sequence) || sequence <= stream.lastSequence || stream.done) {
      return
    }
    stream.lastSequence = sequence
    const lastMessage = chatMessages.value[chatMessages.value.length - 1]
    if (lastMessage?.type === 'ai' && lastMessage.voiceTurnId === event.turn_id) {
      if (lastMessage.streamingPreview !== false) {
        lastMessage.text += event.text_delta
        scrollMessagesToEnd()
      }
    } else {
      addMessage(event.text_delta, 'ai', {
        voiceTurnId: event.turn_id,
        streamingPreview: true,
      })
    }
  } else if (event.type === 'assistant_response_done') {
    const stream = event.turn_id ? assistantStreamState.get(event.turn_id) : null
    if (stream) {
      stream.done = true
    }
    const message = chatMessages.value.find(
      item => item.type === 'ai' && item.voiceTurnId === event.turn_id
    )
    if (message && message.streamingPreview !== false) {
      message.streamingPreview = true
    }
    isThinking.value = false
  } else if (event.type === 'assistant_response' && event.text) {
    isThinking.value = false
    const duplicate = chatMessages.value.some(
      message => message.type === 'ai' && message.voiceTurnId === event.turn_id
    )
    if (!duplicate) {
      addMessage(event.text, 'ai', {
        voiceTurnId: event.turn_id,
        replyMode: event.mode || 'legacy',
      })
    }
  } else if (event.type === 'turn_committed') {
    isThinking.value = false
    if (event.turn_id) {
      const stream = assistantStreamState.get(event.turn_id) || {
        lastSequence: -1,
        done: false,
      }
      stream.done = true
      assistantStreamState.set(event.turn_id, stream)
    }
    const previousLength = chatMessages.value.length
    chatMessages.value = applyTurnCommitted(chatMessages.value, event)
    const lastMessage = chatMessages.value[chatMessages.value.length - 1]
    if (
      chatMessages.value.length > previousLength
      && lastMessage
      && !lastMessage.time
    ) {
      lastMessage.time = getCurrentTime()
    }
  } else if (applyConsoleBoardEvent(stageBoard, event)) {
    if (event.type === 'assistant_board') {
      acknowledgeRenderedBoardItems(event, stageBoard.items.length)
    } else if (event.type === 'board_item') {
      acknowledgeRenderedBoardItems(event, 1, Number(event.index))
    }
  } else if (event.type === 'assistant_fragment' && event.text) {
    isThinking.value = false
    const lastMessage = chatMessages.value[chatMessages.value.length - 1]
    if (lastMessage?.type === 'ai' && lastMessage.voiceTurnId === event.turn_id) {
      // Fragments remain the playback-commit signal and must not duplicate
      // either streamed previews or legacy complete transcripts.
      const alreadyRendered = (
        lastMessage.streamingPreview === true
        || lastMessage.replyMode === 'legacy'
      )
      if (!alreadyRendered || !lastMessage.text) {
        lastMessage.text += event.text
      }
      scrollMessagesToEnd()
    } else {
      addMessage(event.text, 'ai', { voiceTurnId: event.turn_id })
    }
  } else if (event.type === 'speaking_start') {
    voiceState.value = 'avatar_speaking'
    isRecordingVoice.value = false
  } else if (event.type === 'speaking_end') {
    voiceState.value = 'tail_guard'
  }
}

const handleVoiceTestStarted = ({ prompt, turnId }) => {
  addMessage(prompt, 'user', { voiceTurnId: turnId, testRun: true })
  voiceState.value = 'paused'
  isRecordingVoice.value = false
  isThinking.value = true
}

const handleVoiceTestFinished = (record) => {
  showNotification(
    record.passed ? '語音測試已通過並保存紀錄' : '語音測試完成，但有指標未通過',
    record.passed ? 'success' : 'warning'
  )
}

const replyPlaybackState = ref('idle')

const {
  clientId,
  startPlay,
  stopPlay,
  resumePlayback,
  setCaptureEnabled,
  getCaptureRequested,
  interruptVoice,
  acknowledgeBoardDisplay,
} = useWebRTC({
  onNotification: showNotification,
  onVoiceEvent: handleVoiceEvent,
  onPlaybackState: (state) => {
    replyPlaybackState.value = state
  },
  onSessionId: (id) => {
    sessionId.value = id
  },
  onConnectionState: (state) => {
    if (state === 'connected') connectionStatus.value = 'connected'
    if (state === 'failed') connectionStatus.value = 'disconnected'
    if (state === 'preparing' || state === 'reconnecting') {
      connectionStatus.value = 'connecting'
      voiceState.value = 'reconnecting'
    }
    if (state === 'text_only') voiceState.value = 'degraded'
  }
})

function acknowledgeRenderedBoardItems(event, count, onlyIndex = null) {
  const turnId = event.turn_id || ''
  const boardId = event.board_id || turnId
  if (!turnId || boardId !== turnId) return
  nextTick(() => {
    const indices = Number.isInteger(onlyIndex)
      ? [onlyIndex]
      : Array.from({ length: count }, (_item, index) => index)
    indices.forEach((itemIndex) => {
      acknowledgeBoardDisplay({ turnId, boardId, itemIndex })
    })
  })
}

// 設定變更處理
const onSettingsChanged = (newSettings) => {
  appSettings.value = { ...newSettings }
  console.log('設定已更新:', appSettings.value)
  
  // 更新影片大小
  updateVideoSize(newSettings.videoSize)
  
  // 更新主題
  updateTheme(newSettings.theme)
  
  // 更新介面語言
  if (newSettings.uiLanguage) {
    setLocale(newSettings.uiLanguage)
  }
}

const updateVideoSize = (size) => {
  const video = document.getElementById('video')
  if (video) {
    video.style.width = `${size}%`
  }
}

// 更新主題 (樣式 A: Obsidian Dark vs 樣式 C: Bento White)
const updateTheme = (theme) => {
  const root = document.documentElement

  if (theme === 'auto') {
    // 跟隨系統
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    theme = prefersDark ? 'dark' : 'white'
  }

  const isWhite = (theme === 'light' || theme === 'white' || theme === 'bento')
  currentTheme.value = isWhite ? 'white' : 'dark'
  const sampleKey = isWhite ? 'bento' : 'obsidian'

  if (typeof document !== 'undefined' && document.body) {
    document.body.setAttribute('data-theme', currentTheme.value)
    document.body.setAttribute('data-sample', sampleKey)
  }

  if (isWhite) {
    // 樣式 C：Bento 淺色模式 (純淨明亮、灰階微階層)
    root.style.setProperty('--primary', '#6366f1')
    root.style.setProperty('--primary-dark', '#4f46e5')
    root.style.setProperty('--primary-light', '#818cf8')
    root.style.setProperty('--brand', '#6366f1')
    root.style.setProperty('--brand-light', '#818cf8')
    root.style.setProperty('--brand-dark', '#4f46e5')
    root.style.setProperty('--brand-surface', 'rgba(99, 102, 241, 0.08)')
    root.style.setProperty('--success', '#059669')
    root.style.setProperty('--success-surface', 'rgba(5, 150, 105, 0.1)')
    root.style.setProperty('--warning', '#d97706')
    root.style.setProperty('--warning-surface', 'rgba(217, 119, 6, 0.1)')
    root.style.setProperty('--danger', '#dc2626')
    root.style.setProperty('--danger-surface', 'rgba(220, 38, 38, 0.1)')
    root.style.setProperty('--bg-primary', '#f8fafc')
    root.style.setProperty('--bg-secondary', '#ffffff')
    root.style.setProperty('--bg-tertiary', '#f1f5f9')
    root.style.setProperty('--bg-surface', '#ffffff')
    root.style.setProperty('--bg-surface-elevated', '#f1f5f9')
    root.style.setProperty('--bg-surface-hover', '#e2e8f0')
    root.style.setProperty('--bg-surface-active', '#cbd5e1')
    root.style.setProperty('--text-primary', '#0f172a')
    root.style.setProperty('--text-secondary', '#334155')
    root.style.setProperty('--text-tertiary', '#64748b')
    root.style.setProperty('--text-muted', '#94a3b8')
    root.style.setProperty('--border', 'rgba(0, 0, 0, 0.12)')
    root.style.setProperty('--border-subtle', 'rgba(0, 0, 0, 0.06)')
    root.style.setProperty('--border-emphasis', 'rgba(99, 102, 241, 0.5)')
    root.style.setProperty('--shadow-sm', '0 1px 2px rgba(0, 0, 0, 0.05)')
    root.style.setProperty('--shadow', '0 4px 12px rgba(0, 0, 0, 0.06)')
    root.style.setProperty('--shadow-lg', '0 12px 30px rgba(0, 0, 0, 0.08)')
    root.style.setProperty('--bg-gradient', 'linear-gradient(135deg, #f8fafc 0%, #edf2f7 100%)')
    root.style.setProperty('--surface', '#ffffff')
    root.style.setProperty('--surface-elevated', '#f1f5f9')
    root.style.setProperty('--surface-hover', '#e2e8f0')
    root.style.setProperty('--input-surface', '#ffffff')
    root.style.setProperty('--focus-ring', 'rgba(99, 102, 241, 0.25)')
  } else {
    // 樣式 A：Obsidian 深色模式（預設）
    root.style.setProperty('--primary', '#6366f1')
    root.style.setProperty('--primary-dark', '#4f46e5')
    root.style.setProperty('--primary-light', '#818cf8')
    root.style.setProperty('--brand', '#6366f1')
    root.style.setProperty('--brand-light', '#818cf8')
    root.style.setProperty('--brand-dark', '#4f46e5')
    root.style.setProperty('--brand-surface', 'rgba(99, 102, 241, 0.14)')
    root.style.setProperty('--success', '#10b981')
    root.style.setProperty('--success-surface', 'rgba(16, 185, 129, 0.14)')
    root.style.setProperty('--warning', '#f59e0b')
    root.style.setProperty('--warning-surface', 'rgba(245, 158, 11, 0.14)')
    root.style.setProperty('--danger', '#ef4444')
    root.style.setProperty('--danger-surface', 'rgba(239, 68, 68, 0.14)')
    root.style.setProperty('--bg-primary', '#080b11')
    root.style.setProperty('--bg-secondary', '#0e131f')
    root.style.setProperty('--bg-tertiary', '#151d2f')
    root.style.setProperty('--bg-surface', '#0e131f')
    root.style.setProperty('--bg-surface-elevated', '#151d2f')
    root.style.setProperty('--bg-surface-hover', '#1d273e')
    root.style.setProperty('--bg-surface-active', '#253350')
    root.style.setProperty('--text-primary', '#f8fafc')
    root.style.setProperty('--text-secondary', '#cbd5e1')
    root.style.setProperty('--text-tertiary', '#94a3b8')
    root.style.setProperty('--text-muted', '#64748b')
    root.style.setProperty('--border', 'rgba(255, 255, 255, 0.13)')
    root.style.setProperty('--border-subtle', 'rgba(255, 255, 255, 0.07)')
    root.style.setProperty('--border-emphasis', 'rgba(99, 102, 241, 0.55)')
    root.style.setProperty('--shadow-sm', '0 1px 3px rgba(0, 0, 0, 0.3)')
    root.style.setProperty('--shadow', '0 4px 14px rgba(0, 0, 0, 0.4)')
    root.style.setProperty('--shadow-lg', '0 12px 36px rgba(0, 0, 0, 0.6)')
    root.style.setProperty('--bg-gradient', 'linear-gradient(135deg, #080b11 0%, #0e131f 100%)')
    root.style.setProperty('--surface', '#0e131f')
    root.style.setProperty('--surface-elevated', '#151d2f')
    root.style.setProperty('--surface-hover', '#1d273e')
    root.style.setProperty('--input-surface', '#0a0e18')
    root.style.setProperty('--focus-ring', 'rgba(129, 140, 248, 0.34)')
  }
}

const toggleTheme = () => {
  const next = currentTheme.value === 'dark' ? 'white' : 'dark'
  appSettings.value.theme = next
  updateTheme(next)
  try {
    localStorage.setItem(STORAGE_KEYS.theme, next)
  } catch (e) {
    // Ignore storage issues
  }
}

// 檢查後端是否就緒
const checkBackendReady = async () => {
  try {
    const response = await fetch('/health')
    if (response.ok) {
      const data = await response.json()
      if (data.ready) {
        backendReady.value = true
        modelReady.value = Boolean(data.model_ready)
        console.log('✅ 後端已就緒, model_ready=', modelReady.value)
        return true
      }
    }
  } catch (error) {
    console.log('⏳ 等待後端啟動...')
  }
  return false
}

const onAvatarReady = async () => {
  modelReady.value = true
  await checkBackendReady()
}

let connectionAttempt = 0
const handleStartConnection = async () => {
  console.log('🚀 使用者點選"開始連線"按鈕')
  if (connectionStatus.value === 'connecting') return
  
  // 再次確認後端是否就緒
  if (!backendReady.value) {
    showNotification(t('notifications.backendNotReady'), 'warning')
    return
  }
  if (!modelReady.value) {
    showNotification(t('notifications.selectAvatarFirst'), 'warning')
    return
  }
  
  const attempt = ++connectionAttempt
  connectionStatus.value = 'connecting'
  // Establish A/V first. Even with Silero VAD enabled, the user must press
  // the microphone before the console transmits any microphone audio.
  handsFreePaused.value = true
  
  try {
    // 使用設定中的 STUN 配置
    const newSessionId = await startPlay(null, false)
    if (newSessionId) {
      sessionId.value = newSessionId
      showNotification(t('notifications.connectSuccess'), 'success')
    }
    
    if (attempt !== connectionAttempt) return
    if (appSettings.value.autoRecord) {
      setTimeout(() => {
        if (attempt === connectionAttempt && connectionStatus.value === 'connected') handleStartRecord()
      }, 1000)
    }
  } catch (error) {
    if (attempt !== connectionAttempt || error.name === 'AbortError') return
    console.error('連線失敗:', error)
    connectionStatus.value = 'disconnected'
    showNotification(t('notifications.connectFailed'), 'error')
  }
}

const handleStopConnection = () => {
  connectionAttempt++
  handsFreePaused.value = false
  stopPlay()
  sessionId.value = 0
  voiceState.value = 'disconnected'
  isRecordingVoice.value = false
  connectionStatus.value = 'disconnected'
  showNotification(t('notifications.disconnected'), 'info')
}

const handleStartRecord = async () => {
  const player = presentationPlayer(document.getElementById('video'))
  if (player) {
    try {
      player.startRecording(async (blob) => {
        isRecording.value = false
        recordExportProgress.value = 0
        showNotification('正在保存並匯出 MP4…', 'info')
        try {
          const result = await exportSceneRecording(blob, (job) => { recordExportProgress.value = job.progress })
          lastRecordFile.value = { filename: result.filename }
          showNotification('MP4 已完成，可以下載錄影', 'success')
        } catch (error) {
          const url = URL.createObjectURL(blob)
          lastRecordFile.value = { filename: `scene-original.${blob.type.includes('mp4') ? 'mp4' : 'webm'}`, url }
          showNotification(`匯出失敗，已保留原始錄影：${error.message}`, 'error')
        } finally { recordExportProgress.value = null }
      })
      isRecording.value = true
      showNotification('開始錄影，請保持這個頁面在前景', 'success')
    } catch (error) { showNotification(error.message, 'error') }
    return
  }
  if (!sessionId.value) {
    console.error('無法錄製：sessionId 為空')
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  
  console.log('🔴 開始錄製，sessionId:', sessionId.value)
  
  try {
    const response = await fetch('/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Id': clientId },
      body: JSON.stringify({
        type: 'start_record',
        sessionid: sessionId.value,
        client_id: clientId
      })
    })
    
    console.log('錄製請求響應狀態:', response.status)
    
    if (response.ok) {
      const data = await response.json()
      console.log('錄製開始成功:', data)
      isRecording.value = true
      showNotification(t('notifications.recordStart'), 'success')
    } else {
      const errorText = await response.text()
      console.error('錄製開始失敗:', response.status, errorText)
      showNotification(`${t('notifications.recordStartFailed')}: ${response.status}`, 'error')
    }
  } catch (error) {
    console.error('Failed to start recording:', error)
    showNotification(`${t('notifications.recordStartFailed')}: ${error.message}`, 'error')
  }
}

const handleStopRecord = async () => {
  const player = presentationPlayer(document.getElementById('video'))
  if (player) { player.stopRecording(); return }
  if (!sessionId.value) {
    console.error('無法停止錄製：sessionId 為空')
    return
  }
  
  console.log('⏹️ 停止錄製，sessionId:', sessionId.value)
  
  try {
    const response = await fetch('/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Id': clientId },
      body: JSON.stringify({
        type: 'end_record',
        sessionid: sessionId.value,
        client_id: clientId
      })
    })
    
    console.log('停止錄製響應狀態:', response.status)
    
    if (response.ok) {
      const data = await response.json()
      console.log('錄製停止成功:', data)
      isRecording.value = false
      
      // 儲存檔案資訊
      if (data.filename) {
        lastRecordFile.value = {
          filename: data.filename,
          filepath: data.filepath
        }
        showNotification(t('notifications.recordStop'), 'success')
      } else {
        showNotification(t('notifications.recordStopSimple'), 'success')
      }
    } else {
      const errorText = await response.text()
      console.error('停止錄製失敗:', response.status, errorText)
      showNotification(`${t('notifications.recordStopFailed')}: ${response.status}`, 'error')
    }
  } catch (error) {
    console.error('Failed to stop recording:', error)
    showNotification(`${t('notifications.recordStopFailed')}: ${error.message}`, 'error')
  }
}

const downloadRecord = async () => {
  if (!lastRecordFile.value) {
    showNotification(t('notifications.noRecordFile'), 'warning')
    return
  }
  
  const downloadUrl = lastRecordFile.value.url || `/download/${lastRecordFile.value.filename}`
  try {
    showNotification(t('notifications.downloading'), 'info')
    await downloadMedia(downloadUrl, lastRecordFile.value.filename)
  } catch (error) { showNotification(error.message, 'error') }
}

const scrollMessagesToEnd = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

const addMessage = (text, type = 'user', metadata = {}) => {
  chatMessages.value.push({
    text,
    type,
    time: getCurrentTime(),
    ...metadata,
  })
  scrollMessagesToEnd()
}

// 清空輸入框
const clearInput = () => {
  chatInput.value = ''
}

const sendChatMessage = async () => {
  await nextTick()
  return composerRef.value?.send()
}

const sendTTSMessage = async () => {
  if (!ttsInput.value.trim()) return
  
  // 檢查是否已連線
  if (!isConnected.value) {
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  
  const message = ttsInput.value
  
  try {
    const response = await fetch('/human', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Id': clientId },
      body: JSON.stringify({
        text: message,
        type: 'echo',
        interrupt: true,
        sessionid: sessionId.value,
        client_id: clientId
      })
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok || data.code === -1) {
      throw new Error(data.msg || `HTTP ${response.status}`)
    }
    
    addMessage(`已傳送朗讀請求：${message.substring(0, 50)}${message.length > 50 ? '...' : ''}`, 'system')
    ttsInput.value = ''
  } catch (error) {
    console.error('Failed to send TTS message:', error)
    showNotification(t('notifications.ttsFailed'), 'error')
  }
}

// WebRTC microphone controls; server-side Silero owns endpointing and STT.
const handleVoiceButtonPress = () => {
  if (handsFreeTalk.value || !isConnected.value) return
  handsFreePaused.value = false
  voiceState.value = 'listening'
  isRecordingVoice.value = true
  setCaptureEnabled(true)
}

const handleVoiceButtonRelease = () => {
  if (handsFreeTalk.value || !isConnected.value) return
  isRecordingVoice.value = false
  voiceState.value = 'paused'
  setCaptureEnabled(false, { finalize: true })
}

const handleVoiceButtonClick = () => {
  if (!handsFreeTalk.value || !isConnected.value) return
  if (avatarSpeaking.value) {
    handsFreePaused.value = false
    interruptVoice()
    return
  }
  handsFreePaused.value = !handsFreePaused.value
  setCaptureEnabled(!handsFreePaused.value)
}

watch(handsFreeTalk, (enabled) => {
  // Changing VAD mode changes endpointing only; it is not consent to begin
  // capture. A microphone-button click remains required after every change.
  handsFreePaused.value = true
  if (isConnected.value) setCaptureEnabled(false)
})

onUnmounted(() => {
  stopPlay()
  videoResizeObserver?.disconnect()
})

// 清空對話歷史
const resetChatMessages = () => {
  chatMessages.value = []
  Object.keys(ragByTurn).forEach(key => delete ragByTurn[key])
}

const clearChatHistory = async () => {
  if (!isConnected.value) {
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }

  try {
    const response = await fetch('/clear_history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Id': clientId },
      body: JSON.stringify({
        sessionid: sessionId.value,
        client_id: clientId
      })
    })

    let payload = {}
    try {
      payload = await response.json()
    } catch (error) {
      payload = {}
    }

    if (!response.ok || payload.code === -1) {
      throw new Error(payload.msg || `HTTP ${response.status}`)
    }

    resetChatMessages()
    showNotification(t('notifications.historyCleared'), 'success')
  } catch (error) {
    console.error('Failed to clear history:', error)
    showNotification(`${t('notifications.historyClearFailed')}: ${error.message}`, 'error')
  }
}

let videoResizeObserver = null
let backendCheckInterval = null
let backendTimeoutTimer = null
let authRetryTimer = null
let consoleSessionStarted = false

const adminAuthReady = ref(false)
const adminAuthEnabled = ref(false)
const adminAuthenticated = ref(false)
const adminPasswordInput = ref('')
const adminLoginError = ref('')
const adminLoggingIn = ref(false)

const canRenderConsole = computed(() => (
  adminAuthReady.value && (!adminAuthEnabled.value || adminAuthenticated.value)
))

const stopBackendReadinessPolling = () => {
  if (backendCheckInterval) {
    clearInterval(backendCheckInterval)
    backendCheckInterval = null
  }
  if (backendTimeoutTimer) {
    clearTimeout(backendTimeoutTimer)
    backendTimeoutTimer = null
  }
}

const startConsoleSession = () => {
  if (consoleSessionStarted || !canRenderConsole.value) return
  consoleSessionStarted = true

  // 拉一次 VAD / 識別來源，決定錄音走瀏覽器識別還是後端（後端才過 VAD）
  loadVadSettings().then(async () => {
    vadDraft.type = 'silero'
    if (vad.type !== 'silero' || (vad.enabled && vad.asr_mode !== 'server')) {
      await applyVadSettings()
    }
  }).catch((error) => {
    console.warn('讀取 VAD 設定失敗，按瀏覽器識別處理:', error.message)
  })

  // 開始輪詢檢查後端是否就緒
  console.log('🔍 開始檢查後端狀態...')
  stopBackendReadinessPolling()
  backendCheckInterval = setInterval(async () => {
    const ready = await checkBackendReady()
    if (ready) {
      stopBackendReadinessPolling()
      showNotification(t('notifications.backendReady'), 'success')
    }
  }, 2000)

  // 最多檢查60秒
  backendTimeoutTimer = setTimeout(() => {
    if (!backendReady.value) {
      stopBackendReadinessPolling()
      showNotification(t('notifications.backendTimeout'), 'error')
    }
  }, 60000)
}

const refreshAdminAuth = async () => {
  const status = await fetchAdminAuthStatus()
  if (!status.ok) {
    if (authRetryTimer) clearTimeout(authRetryTimer)
    authRetryTimer = setTimeout(() => { void refreshAdminAuth() }, 1500)
    return false
  }
  adminAuthEnabled.value = status.auth_enabled
  adminAuthenticated.value = status.authenticated
  adminAuthReady.value = true
  if (canRenderConsole.value) {
    startConsoleSession()
  }
  return true
}

const handleAdminLogin = async () => {
  if (adminLoggingIn.value || !adminPasswordInput.value) return
  adminLoggingIn.value = true
  adminLoginError.value = ''
  try {
    const result = await loginAdmin(adminPasswordInput.value)
    if (!result.ok) {
      adminLoginError.value = result.message || '密碼錯誤'
      return
    }
    adminAuthEnabled.value = result.auth_enabled
    adminAuthenticated.value = result.authenticated
    adminPasswordInput.value = ''
    adminLoginError.value = ''
    startConsoleSession()
  } finally {
    adminLoggingIn.value = false
  }
}

const handleAdminLogout = async () => {
  if (isConnected.value || connectionStatus.value === 'connecting') {
    await handleStopConnection()
  }
  stopBackendReadinessPolling()
  consoleSessionStarted = false
  const result = await logoutAdmin()
  adminAuthEnabled.value = result.auth_enabled
  adminAuthenticated.value = result.authenticated
  adminPasswordInput.value = ''
  adminLoginError.value = ''
}

watch(videoWrapperRef, (wrap) => {
  videoResizeObserver?.disconnect()
  videoResizeObserver = null
  if (wrap && window.ResizeObserver) {
    const measure = () => {
      videoSizeBox.w = wrap.clientWidth
      videoSizeBox.h = wrap.clientHeight
    }
    videoResizeObserver = new ResizeObserver(measure)
    videoResizeObserver.observe(wrap)
    measure()
  }
})

onMounted(async () => {
  console.log('✅ Vue 應用已掛載')
  console.log('後端 API 地址: /offer (通過 Vite proxy 轉發到 localhost:8010)')

  // 載入語言設定
  loadLocale()

  // 應用初始主題
  const savedSample = readMigratedStorage(
    localStorage,
    STORAGE_KEYS.designSample,
    LEGACY_STORAGE_KEYS.designSample
  ) || 'obsidian'
  setDesignSample(savedSample)

  await refreshAdminAuth()
})

onUnmounted(() => {
  if (authRetryTimer) clearTimeout(authRetryTimer)
  stopBackendReadinessPolling()
  videoResizeObserver?.disconnect()
})
</script>

<style>
@import 'highlight.js/styles/atom-one-dark.css';

.app-root-shell {
  height: 100vh;
  width: 100vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.admin-auth-gate {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--bg-app, #0b0f17);
}

.admin-auth-card {
  width: min(420px, 100%);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 28px;
  border-radius: 18px;
  background: var(--bg-surface-elevated, #141a24);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.12));
  box-shadow: var(--shadow-lg, 0 20px 50px rgba(0, 0, 0, 0.45));
}

.admin-auth-header {
  display: flex;
  align-items: center;
  gap: 14px;
}

.admin-auth-header h2 {
  margin: 0;
  font-size: 18px;
  color: var(--text-primary);
}

.admin-auth-header p {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.admin-auth-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.admin-auth-input {
  width: 100%;
  padding: 10px 14px;
  border-radius: var(--radius-sm, 10px);
  border: 1px solid var(--border-default, rgba(255, 255, 255, 0.16));
  background: var(--bg-surface, #0f141d);
  color: var(--text-primary);
  font-size: 14px;
}

.admin-auth-error {
  margin: 0;
  font-size: 13px;
  color: var(--danger, #f87171);
}

.admin-auth-submit {
  padding: 11px 16px;
  border: 0;
  border-radius: var(--radius-sm, 10px);
  background: var(--brand, #4f7cff);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.admin-auth-submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.admin-logout-btn {
  padding: 5px 12px;
  white-space: nowrap;
}

.stage-ratio-box video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  z-index: 1;
}

.video-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(8, 11, 17, 0.75);
  backdrop-filter: blur(8px);
  z-index: 5;
  text-align: center;
  padding: 20px;
}

.notification-container {
  position: fixed;
  top: 48px;
  right: 24px;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.notification {
  pointer-events: auto;
  padding: 10px 18px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-lg);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--text-primary);
  animation: slideIn 0.2s ease-out;
}

.notification.success {
  border-color: var(--success);
}
.notification.success i {
  color: var(--success);
}

.notification.warning {
  border-color: var(--warning);
}
.notification.warning i {
  color: var(--warning);
}

.notification.error {
  border-color: var(--danger);
}
.notification.error i {
  color: var(--danger);
}

.rag-turn-status { margin-top: 12px; border-top: 1px solid var(--border-subtle); padding-top: 10px; font-size: 12px; }
.rag-turn-warning { color: var(--warning); display: flex; align-items: center; gap: 6px; }
.rag-turn-references summary { cursor: pointer; color: var(--brand-light); font-weight: 700; }
.rag-turn-references summary:focus-visible { outline: 2px solid var(--brand-light); outline-offset: 2px; }
.rag-turn-references ol { padding-left: 20px; display: grid; gap: 8px; max-height: 240px; overflow: auto; }
.rag-turn-references li { overflow-wrap: anywhere; }
.rag-turn-references p { white-space: pre-wrap; color: var(--text-secondary); margin: 3px 0 0; line-height: 1.45; }

@keyframes slideIn {
  from {
    transform: translateX(100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.maintenance-drawer {
  position: fixed;
  top: 56px;
  right: 16px;
  bottom: 16px;
  width: min(440px, calc(100vw - 32px));
  z-index: 9000;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md, 12px);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.maintenance-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
  font-weight: 700;
}

.maintenance-drawer-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.maintenance-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.maintenance-debug-section {
  border-top: 1px solid var(--border-subtle);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.maintenance-debug-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  cursor: pointer;
}
</style>
