<!--
Derived from Kedreamix/Linly-Talker-Stream.
Copyright [Linly-talker-stream@kedreamix].
Licensed under the Apache License, Version 2.0.

Substantially modified by HongXian0903, 2026.
See LICENSE and NOTICE.
-->
<template>
  <div class="app-root-shell">

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
          <span class="nav-version-pill">v2.0</span>
        </div>
      </div>

      <!-- 主頁面 Tabs 切換：即時演播控制台 vs 滿板系統設定中心 -->
      <nav class="nav-main-tabs" aria-label="主要視圖切換">
        <button
          class="main-tab-link"
          id="btnViewConsole"
          aria-label="即時演播控制台"
          :class="{ active: currentMainView === 'console' }"
          @click="switchMainView('console')"
        >
          <i class="bi bi-broadcast"></i>
          <span>即時演播控制台</span>
        </button>
        <button
          class="main-tab-link"
          id="btnViewSettings"
          aria-label="系統設定中心"
          :class="{ active: currentMainView === 'settings' }"
          @click="switchMainView('settings')"
        >
          <i class="bi bi-sliders2"></i>
          <span>系統設定中心</span>
        </button>
      </nav>

      <div class="nav-status-group">
        <div class="webrtc-chip" :class="{ 'is-ok': isConnected, 'is-busy': connectionStatus === 'connecting' }" role="status">
          <span class="live-dot" :class="{ 'connected': isConnected }" aria-hidden="true"></span>
          <span>{{ isConnected ? 'WebRTC 已連線' : (connectionStatus === 'connecting' ? '連線中...' : 'WebRTC 未連線') }}</span>
          <span class="webrtc-session-id">{{ sessionId > 0 ? '#' + sessionId : '—' }}</span>
        </div>
        <div class="voice-badge-pill" id="voiceStatusBadge">
          <i :class="isRecordingVoice ? 'bi bi-mic-fill' : 'bi bi-soundwave'"></i>
          <span>{{ voiceBadgeText || '語音待命' }}</span>
        </div>
        <button type="button" class="nav-logout-btn" aria-label="登出控制台" title="登出控制台" @click="logout">
          <i class="bi bi-box-arrow-right"></i>
        </button>
      </div>
    </header>

    <!-- ══════════════════════════════════════════════════════════════
         2. 頁面視圖容器 (Page Views)
         ══════════════════════════════════════════════════════════════ -->
    <div class="app-viewport">
      <div v-if="llmPartialGpu" class="llm-gpu-warning status-banner is-warn" role="alert">
        <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
        <span>{{ t('notifications.llmPartialGpu') }}</span>
      </div>

      <!-- ──────────────────────────────────────────────────────────
           頁面 A：即時演播控制台 (Studio Console View)
           ────────────────────────────────────────────────────────── -->
      <div class="page-view" :class="{ active: currentMainView === 'console' }" id="viewConsole">
        <div class="studio-layout">

          <!-- 左側：對話調度與互動區 (studio-chat-panel) -->
          <div class="studio-chat-panel">
            <div class="chat-sub-toolbar">
              <div class="mode-pills-wrap" role="group" aria-label="控制台操作模式">
                <button
                  class="mode-pill-btn"
                  :class="{ active: activeMode === 'chat' }"
                  :aria-pressed="activeMode === 'chat'"
                  @click="selectMode('chat')"
                >
                  <i class="bi bi-chat-text"></i> 對話模式
                </button>
                <button
                  class="mode-pill-btn"
                  :class="{ active: activeMode === 'tts' }"
                  :aria-pressed="activeMode === 'tts'"
                  @click="selectMode('tts')"
                >
                  <i class="bi bi-volume-up"></i> 朗讀模式
                </button>
                <button
                  class="mode-pill-btn"
                  :class="{ active: activeMode === 'validation' }"
                  :aria-pressed="activeMode === 'validation'"
                  @click="selectMode('validation')"
                >
                  <i class="bi bi-speedometer2"></i> 語音驗證
                </button>
              </div>
              <div class="console-toolbar-actions">
                <button
                  v-show="activeMode === 'chat'"
                  class="sample-btn"
                  @click="clearChatHistory"
                  :disabled="!isConnected || !roleInputAllowed"
                  :title="isConnected ? t('chat.clearHistory') : t('notifications.connectFirst')"
                  style="padding: 4px 10px;"
                >
                  <i class="bi bi-trash"></i> 清空紀錄
                </button>
                <button
                  class="sample-btn"
                  @click="switchMainView('settings', 'conversation')"
                  style="padding: 4px 10px;"
                >
                  <i class="bi bi-sliders" aria-hidden="true"></i> 對話設定
                </button>
              </div>
            </div>

            <div class="role-console-controls" role="group" aria-label="目前控制台對話的角色操作">
              <span>{{ activeRoleName }}<template v-if="roleRuntime.enabled"> · {{ rolePhaseLabel(roleRuntime.phase) }}</template></span>
              <span class="console-locale-summary">回覆語系：{{ consoleLocaleLabel }}</span>
              <button v-if="roleRuntime.can_return" type="button" class="sample-btn" :disabled="roleBusy || !canRoleReturn(roleRuntime)" @click="roleAction('/return')">返回主數位人</button>
              <button v-if="roleRuntime.enabled" type="button" class="sample-btn" :disabled="roleBusy || roleRuntime.phase === 'transition'" @click="roleAction('/stop')">停止回答</button>
              <label v-if="roleRuntime.enabled && activeMode === 'chat'">對話紀錄
                <select v-model="historyProfile" aria-label="查看角色對話紀錄">
                  <option value="">全部角色</option>
                  <option v-for="p in roleLibrary?.profiles || []" :key="p.id" :value="p.id">{{ p.name }}</option>
                </select>
              </label>
              <p v-if="!roleInputAllowed">角色準備或轉場中，請稍候。</p>
            </div>

            <!-- 快捷提問膠囊列 -->
            <div v-show="activeMode === 'chat'" class="quick-chips-row">
              <span class="quick-chips-label"><i class="bi bi-lightning-charge" aria-hidden="true"></i> 快捷指令:</span>
              <button class="chip-item board-chip" @click="quickSend('請整理 Nova Avatar 三大核心技術優勢並輸出看板')">
                <i class="bi bi-layout-text-sidebar" aria-hidden="true"></i> 核心技術優勢 (BOARD)
              </button>
              <button class="chip-item board-chip" @click="quickSend('請列出系統安裝部署四步驟')">
                <i class="bi bi-layout-text-sidebar" aria-hidden="true"></i> 部署步驟 (BOARD)
              </button>
              <button class="chip-item" @click="quickSend('你好！請簡短自我介紹')">
                <i class="bi bi-chat-dots" aria-hidden="true"></i> 自我介紹 (SIMPLE)
              </button>
              <button class="chip-item" @click="quickSend('今天台北天氣如何？')">
                <i class="bi bi-chat-dots" aria-hidden="true"></i> 日常天氣問候
              </button>
            </div>

            <VoiceTestPanel
              v-if="voiceTestVisited"
              v-show="activeMode === 'validation'"
              ref="voiceTestPanelRef"
              :session-id="sessionId"
              :connected="isConnected && roleInputAllowed"
              :busy="isThinking || ['avatar_speaking', 'tail_guard'].includes(voiceState)"
              :voice-state="voiceState"
              @close="selectMode('chat')"
              @started="handleVoiceTestStarted"
              @finished="handleVoiceTestFinished"
              @notification="showNotification"
            />

            <!-- 對話模式：對話訊息瀑布流 -->
            <div v-if="activeMode === 'chat'" class="chat-flow-container" id="chatFlowBox" ref="messagesRef">
              <div
                v-for="(msg, index) in visibleChatMessages"
                :key="index"
                class="bubble-row"
                :class="msg.type === 'user' ? 'user' : 'ai'"
              >
                <div class="bubble-avatar">
                  <i :class="msg.type === 'user' ? 'bi bi-person-fill' : 'bi bi-robot'"></i>
                </div>
                <div class="bubble-card">
                  <div v-if="msg.profileId" class="role-message-label">{{ profileName(msg.profileId) }}<span v-if="msg.handoffId"> · 交接 {{ msg.handoffId.slice(0, 8) }}</span></div>
                  <div v-if="appSettings.showTimestamp && msg.time" style="font-size: 10.5px; opacity: 0.6; margin-bottom: 4px; font-family: var(--font-mono);">{{ msg.time }}</div>
                  <!-- eslint-disable-next-line vue/no-v-html -- renderMarkdown drops raw HTML and runs DOMPurify -->
                  <div v-html="renderMarkdown(msg.text)"></div>
                  <div v-if="msg.pending" role="status" aria-live="polite" style="font-size: 12px; color: var(--text-muted);">傳送中…</div>
                  <div
                    v-if="msg.type === 'ai' && msg.voiceTurnId && ragByTurn[msg.voiceTurnId]
                      && (ragByTurn[msg.voiceTurnId].status === 'unavailable'
                        || ragByTurn[msg.voiceTurnId].status === 'timeout'
                        || ragByTurn[msg.voiceTurnId].sources.length)"
                    class="rag-turn-status"
                  >
                    <div v-if="ragByTurn[msg.voiceTurnId].status === 'unavailable'" class="rag-turn-warning" role="status">
                      <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
                      知識庫暫時無法連線，本輪沿用一般回答。
                    </div>
                    <div v-else-if="ragByTurn[msg.voiceTurnId].status === 'timeout'" class="rag-turn-warning" role="status">
                      <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
                      本輪未取得檢索：知識庫回應逾時，本輪沿用一般回答。
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
            <div v-else-if="activeMode === 'tts'" class="tts-mode-workspace">
              <div style="font-size: 14px; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
                <i class="bi bi-file-text" style="color: var(--brand-light);"></i> {{ t('chat.ttsTitle') }}
              </div>
              <textarea
                v-model="ttsInput"
                class="std-textarea"
                :placeholder="isConnected ? t('chat.ttsInputPlaceholder') : t('chat.inputPlaceholderDisconnected')"
                :disabled="!isConnected || !roleInputAllowed"
                rows="10"
                style="flex: 1; resize: none;"
              ></textarea>
              <button
                class="btn-send-main"
                @click="sendTTSMessage"
                :disabled="!isConnected || !roleInputAllowed || !ttsInput.trim()"
                style="align-self: flex-end; padding: 10px 24px;"
              >
                <i class="bi bi-play-circle-fill"></i>
                <span>{{ t('chat.ttsButton') }}</span>
              </button>
            </div>

            <!-- 底部輸入操作塢 -->
            <div class="studio-input-dock" v-show="activeMode === 'chat'">
              <ConversationComposer ref="composerRef" v-model="chatInput" :session-id="sessionId" :connected="isConnected && roleInputAllowed"
                @submitting="onComposerSubmitting" @accepted="onComposerAccepted"
                @submission-finished="onComposerSubmissionFinished" @editing="onComposerEditing" />
              <div class="input-actions-bar">
                <div class="vad-status-label">
                  <i class="bi bi-check-circle-fill" :style="{ color: isConnected ? 'var(--success)' : 'var(--text-muted)' }"></i>
                  <span>{{ isConnected ? (handsFreeTalk ? 'Silero VAD 免持聆聽就緒 · 靜音 650ms 自動送出' : '文字模式就緒 · 點選按住說話或輸入') : '等待 WebRTC 連線就緒...' }}</span>
                </div>
                <div class="dock-buttons-wrap">
                  <button
                    class="btn-voice-push"
                    id="btnPushVoice"
                    :class="{ 'active-listening': isRecordingVoice }"
                    :disabled="!isConnected || !roleInputAllowed"
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
                <span>數位人預覽</span>
              </div>
              <div class="console-toolbar-actions">
                <span style="font-size: 11.5px; color: var(--text-tertiary);">{{ currentAvatarMeta }}</span>
                <button type="button" class="sample-btn" @click="switchMainView('settings', 'stage')">看板設定</button>
              </div>
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
                    <span class="board-window-title"><i class="bi bi-layout-sidebar-reverse"></i> {{ visibleBoard.title || '核心優勢看板' }}</span>
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
                  :disabled="!isConnected"
                >
                  <i class="bi bi-record-circle" :style="{ color: isRecording ? 'var(--danger)' : '' }"></i>
                  {{ isRecording ? '停止錄影' : '開始錄影' }}
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
          :theme-preference="themePreference"
          :connection-status="connectionStatus"
          :llm-partial-gpu="llmPartialGpu"
          :session-id="sessionId"
          @conversation-summary="conversationSummary = $event"
          @settings-changed="onSettingsChanged"
          @notification="showNotification"
          @request-disconnect="handleStopConnection"
          @avatar-ready="onAvatarReady"
          @close-settings="switchMainView('console')"
        />
      </div>

    </div>

    <input type="hidden" id="sessionid" :value="sessionId">

    <!-- 除錯面板 -->
    <DebugPanel
      v-if="appSettings.showDebugPanel"
      :connection-status="connectionStatus"
      :session-id="sessionId"
    />

    <!-- 通知提示（狀態第四層）：圖示＋文字，左側色條依語氣 -->
    <div class="notification-container" role="status" aria-live="polite">
      <transition-group name="notification">
        <div
          v-for="notification in notifications"
          :key="notification.id"
          class="notification"
          :class="notification.type"
        >
          <i :class="getNotificationIcon(notification.type)" aria-hidden="true"></i>
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
import { useRoles } from './composables/useRoles.js'
import { canRoleInput, canRoleReturn, rolePhaseLabel } from './roleState.js'
import { downloadMedia } from './mediaDownload.js'
import { logout } from './adminSession.js'
import { avatarScenePreviewUrl } from './scenePreview.js'
import { applyTurnCommitted } from './consoleTurnCommit.js'
import { applyConsoleBoardEvent, createConsoleBoardState } from './consoleBoardState.js'
import { boardReopenPresentation, placeStageBoard, STAGE_BOARD_PREVIEW_ITEMS, STAGE_BOARD_PREVIEW_TITLE } from './stageBoardLayout.js'
import { applyThemePreference, readThemePreference, saveThemePreference } from './consoleTheme.js'
import { renderMarkdown, stripProtocolMarkers } from './markdown.js'
import { readBackendHealth } from './backendHealth.js'

const { t, setLocale, loadLocale } = useI18n()
const { roleRuntime, roleLibrary, roleRequest, roleEvent } = useRoles()
const roleBusy = ref(false)
const historyProfile = ref('')
const roleInputAllowed = computed(() => canRoleInput(roleRuntime, 'console'))
const activeRoleName = computed(() => profileName(roleRuntime.active_profile_id))
function profileName(id) { return roleLibrary.value?.profiles.find(p => p.id === id)?.name || id || '目前角色' }
async function roleAction(path, body) {
  roleBusy.value = true
  try { await roleRequest(path, 'POST', { ...body, sessionid: sessionId.value }) }
  catch (error) { showNotification(error.message, 'error') }
  finally { roleBusy.value = false }
}
const { vad, vadDraft, loadVadSettings, applyVadSettings, runtime, isStageConfiguring, selectedBoardPreview } = useRuntimeSettings()
const handsFreeTalk = computed(() => Boolean(vad.enabled))

const sessionId = ref(0)
const connectionStatus = ref('disconnected')
const isRecording = ref(false)
const activeMode = ref('chat')
const voiceTestVisited = ref(false)
const selectMode = (mode) => {
  if (mode === 'validation') voiceTestVisited.value = true
  activeMode.value = mode
}
const conversationSummary = ref(null)
const consoleLocaleLabel = computed(() => {
  if (!sessionId.value) return '待連線'
  if (conversationSummary.value?.sessionId !== sessionId.value) return '讀取中'
  return conversationSummary.value.locale === 'en-US' ? 'English' : '繁體中文'
})
const chatInput = ref('')
const composerRef = ref(null)
const onComposerSubmitting = ({ text, requestId }) => {
  addMessage(text, 'user', { requestId, pending: true })
}
const onComposerAccepted = ({ text, requestId, turnId }) => {
  const message = chatMessages.value.find(item => item.requestId === requestId && item.pending)
  if (message) Object.assign(message, { text, pending: false, voiceTurnId: turnId })
  else addMessage(text, 'user', { voiceTurnId: turnId })
  isThinking.value = true
}
const onComposerSubmissionFinished = ({ requestId, error }) => {
  chatMessages.value = chatMessages.value.filter(item => !(item.requestId === requestId && item.pending))
  if (error) showNotification(error, 'error')
}
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
// 跟隨系統、淺色或深色；配色全在 console-prototype.css 的 token
const themePreference = ref(readThemePreference(globalThis.localStorage))
const setThemePreference = (preference) => {
  themePreference.value = applyThemePreference(preference)
  saveThemePreference(globalThis.localStorage, themePreference.value)
}

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
const quickSend = (txt) => {
  selectMode('chat')
  chatInput.value = txt
  return sendChatMessage(txt)
}
const openStageWindow = () => {
  window.open('stage.html', '_blank')
}
const stageCaptionText = computed(() => {
  const lastAi = [...chatMessages.value].reverse().find(m => m.type === 'ai' && m.captionEpoch === captionEpoch.value)
  if (!lastAi || !lastAi.text) return ''
  const clean = stripProtocolMarkers(lastAi.text)
  return clean.length > 80 ? clean.slice(-80) : clean
})

const currentAvatar = computed(() => {
  const characters = Array.isArray(runtime.characters) ? runtime.characters : []
  const roleAvatar = roleRuntime.active_avatar_id
  return characters.find(character => character.id === (roleAvatar || runtime.avatar?.avatar_id)) || null
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
    roleRuntime.enabled ? '720×1280' : avatar.resolution,
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

// 快速指令選單狀態
const showQuickCommands = ref(false)
const quickCommands = [
  '你好，請介紹一下自己',
  '請用看板列出三個健康飲食原則',
  '今天天氣如何？',
  '講一個有趣的笑話',
  '如何學習程式設計？'
]

// 插入快速指令
const insertQuickCommand = (cmd) => {
  chatInput.value = cmd
  showQuickCommands.value = false
  // 自動聚焦輸入框
  nextTick(() => {
    const textarea = document.querySelector('.textarea-wrapper textarea')
    if (textarea) textarea.focus()
  })
}

// 點擊外部關閉快速指令選單
const closeQuickCommandsOnOutsideClick = (e) => {
  if (showQuickCommands.value && !e.target.closest('.quick-commands-menu') && !e.target.closest('.btn-quick-cmd')) {
    showQuickCommands.value = false
  }
}

function askPreset(query) {
  chatInput.value = query
  return sendChatMessage(query)
}
const backendReady = ref(false)  // 後端是否就緒
const modelReady = ref(false)    // 是否已套用數字人引擎
const llmPartialGpu = ref(false) // 本機 LLM 未全 GPU 執行（回覆會明顯變慢）
let healthRefresh = null
const stageBoard = reactive(createConsoleBoardState())
const voiceTestPanelRef = ref(null)
const videoWrapperRef = ref(null)
const videoSizeBox = reactive({ w: 400, h: 400 })
const visibleBoard = computed(() => {
  if (stageBoard.items.length) {
    return { title: stageBoard.title || '核心優勢看板', items: stageBoard.items, preview: false }
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
  theme: 'system',
  uiLanguage: 'zh-TW',
  videoSize: 100
})

const chatMessages = ref([])
const captionEpoch = ref(0)
const visibleChatMessages = computed(() => historyProfile.value
  ? chatMessages.value.filter(m => m.profileId === historyProfile.value) : chatMessages.value)
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
  if (event.mirrored) return
  composerRef.value?.receive(event)
  if (event.type === 'answer_clear') { captionEpoch.value += 1; return }
  if (event.type === 'presentation_reset' || event.type === 'conversation_reset') {
    chatMessages.value = []
    assistantStreamState.clear()
    for (const key of Object.keys(ragByTurn)) delete ragByTurn[key]
    captionEpoch.value += 1
    applyConsoleBoardEvent(stageBoard, { type: 'board_clear' })
    isThinking.value = false
    isRecordingVoice.value = false
    return
  }
  roleEvent(event)
  if (event.type === 'role_state' && event.error) showNotification(event.error, 'error')
  if (event.type === 'role_clear') {
    captionEpoch.value += 1
    applyConsoleBoardEvent(stageBoard, { type: 'board_clear' })
    isThinking.value = false
    return
  }
  if (event.type === 'role_history_reset') {
    chatMessages.value = chatMessages.value.filter(m => m.profileId !== event.reset_profile_id)
    return
  }
  if (event.type === 'role_error') { showNotification(event.message, 'error'); return }
  if (event.type === 'role_handoff') {
    for (const message of chatMessages.value) {
      if ([event.source_turn_id, event.target_turn_id].includes(message.voiceTurnId)) message.handoffId = event.handoff_id
    }
    return
  }
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
      sources: Array.isArray(event.sources) ? event.sources : []
    }
  } else if (event.type === 'turn_cancelled' && event.turn_id) {
    delete ragByTurn[event.turn_id]
  } else if (event.type === 'user_transcript' && event.text) {
    addMessage(event.text, 'user', { profileId: event.profile_id, voiceTurnId: event.turn_id })
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
  if (newSettings.theme) setThemePreference(newSettings.theme)
  
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

// 檢查後端是否就緒
const checkBackendReady = async () => {
  try {
    const response = await fetch('/health')
    if (response.ok) {
      const health = readBackendHealth(await response.json())
      llmPartialGpu.value = health.llmPartialGpu
      if (health.ready) {
        backendReady.value = true
        modelReady.value = health.modelReady
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
  if (!sessionId.value) {
    console.error('無法錄製：sessionId 為空')
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  
  console.log('🔴 開始錄製，sessionId:', sessionId.value)
  
  try {
    const response = await fetch('/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'start_record',
        sessionid: sessionId.value
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
  if (!sessionId.value) {
    console.error('無法停止錄製：sessionId 為空')
    return
  }
  
  console.log('⏹️ 停止錄製，sessionId:', sessionId.value)
  
  try {
    const response = await fetch('/record', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'end_record',
        sessionid: sessionId.value
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
    profileId: roleRuntime.enabled ? roleRuntime.active_profile_id : '',
    captionEpoch: captionEpoch.value,
    ...metadata,
  })
  scrollMessagesToEnd()
}

// 清空輸入框
const clearInput = () => {
  chatInput.value = ''
}

const sendChatMessage = async (message) => {
  // Let the connection/mode props settle; the question itself is passed
  // explicitly instead of being read back through the v-model watchers.
  await nextTick()
  if (!isConnected.value) {
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  if (!roleInputAllowed.value) {
    showNotification('角色準備或轉場中，請稍候再送出。', 'warning')
    return
  }
  const composer = composerRef.value
  if (!composer) {
    showNotification('對話輸入尚未就緒，請稍後再試。', 'warning')
    return
  }
  return composer.send(message)
}

const sendTTSMessage = async () => {
  if (!ttsInput.value.trim()) return
  if (!roleInputAllowed.value) return
  
  // 檢查是否已連線
  if (!isConnected.value) {
    showNotification(t('notifications.connectFirst'), 'warning')
    return
  }
  
  const message = ttsInput.value
  
  try {
    const response = await fetch('/human', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: message,
        type: 'echo',
        interrupt: true,
        sessionid: sessionId.value
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
  if (!roleInputAllowed.value) return
  if (handsFreeTalk.value || !isConnected.value) return
  handsFreePaused.value = false
  voiceState.value = 'listening'
  isRecordingVoice.value = true
  setCaptureEnabled(true)
}

const handleVoiceButtonRelease = () => {
  if (!roleInputAllowed.value) return
  if (handsFreeTalk.value || !isConnected.value) return
  isRecordingVoice.value = false
  voiceState.value = 'paused'
  setCaptureEnabled(false, { finalize: true })
}

const handleVoiceButtonClick = () => {
  if (!roleInputAllowed.value) return
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
  clearInterval(healthRefresh)
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sessionid: sessionId.value
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

onMounted(async () => {
  roleRequest().catch(error => showNotification(error.message, 'error'))
  console.log('✅ Vue 應用已掛載')
  console.log('後端 API 地址: /offer (通過 Vite proxy 轉發到 localhost:8010)')
  
  // 載入語言設定
  loadLocale()
  
  
  const wrap = videoWrapperRef.value
  if (wrap && window.ResizeObserver) {
    const measure = () => {
      videoSizeBox.w = wrap.clientWidth
      videoSizeBox.h = wrap.clientHeight
    }
    videoResizeObserver = new ResizeObserver(measure)
    videoResizeObserver.observe(wrap)
    measure()
  }

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
  const checkInterval = setInterval(async () => {
    const ready = await checkBackendReady()
    if (ready) {
      clearInterval(checkInterval)
      showNotification(t('notifications.backendReady'), 'success')
      // A model switch can move the LLM off the GPU; keep the warning current.
      healthRefresh = setInterval(checkBackendReady, 30000)
    }
  }, 2000)  // 每2秒檢查一次
  
  // 最多檢查60秒
  setTimeout(() => {
    if (!backendReady.value) {
      clearInterval(checkInterval)
      showNotification(t('notifications.backendTimeout'), 'error')
    }
  }, 60000)
})
</script>

<style>
.llm-gpu-warning { margin: 12px 24px 0; }
.quick-chips-label { font-size: 12px; color: var(--text-3); font-weight: 700; white-space: nowrap; display: inline-flex; align-items: center; gap: 4px; }

.role-console-controls {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
}
.role-console-controls label { display: flex; align-items: center; gap: 6px; }
.console-locale-summary { color: var(--text-secondary); }
.console-toolbar-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tts-mode-workspace { flex: 1; min-height: 0; min-width: 0; display: flex; flex-direction: column; padding: 18px; gap: 12px; overflow: auto; }
.tts-mode-workspace .std-textarea { min-height: 100px; }
.studio-input-dock > .conversation-composer { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.studio-input-dock .composer-body { min-height: 0; overflow: auto; }
.studio-input-dock .composer-label, .studio-input-dock .composer-actions, .studio-input-dock .input-actions-bar { flex-shrink: 0; }
.bubble-card pre, .bubble-card table { display: block; max-width: 100%; overflow-x: auto; }
.bubble-card pre { white-space: pre; }
.bubble-card img { max-width: 100%; height: auto; }
.role-console-controls p { width: 100%; margin: 0; color: var(--text-secondary); }
.role-console-controls select {
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  padding: 6px;
}
.role-message-label { font-size: 11px; color: var(--text-secondary); margin-bottom: 6px; }
.nav-logout-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 999px; cursor: pointer;
  background: transparent; border: 1px solid var(--border-default); color: var(--text-secondary);
}
.nav-logout-btn:hover { color: var(--text-primary); background: var(--bg-surface-hover); }

.app-root-shell {
  height: 100dvh;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

@media (max-width: 820px) {
  .app-root-shell { height: auto; min-height: 100dvh; overflow: visible; }
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
  top: 68px;
  right: 24px;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.notification {
  pointer-events: auto;
  width: min(26rem, calc(100vw - 2rem));
  padding: 12px 16px;
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-left: 4px solid var(--brand);
  box-shadow: var(--shadow-2);
  display: flex;
  align-items: flex-start;
  gap: 12px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  animation: slideIn 0.22s cubic-bezier(0.2, 0.8, 0.2, 1);
}
.notification i { font-size: 18px; line-height: 1.2; color: var(--brand); flex: none; }

.notification.success { border-left-color: var(--ok); }
.notification.success i { color: var(--ok); }

.notification.warning { border-left-color: var(--warn-bar); }
.notification.warning i { color: var(--warn); }

.notification.error { border-left-color: var(--danger); background: var(--danger-surface); border-color: var(--danger-border); border-left-color: var(--danger); }
.notification.error i { color: var(--danger); }

.rag-turn-status { margin-top: 12px; border-top: 1px solid var(--border-subtle); padding-top: 10px; font-size: 12px; }
.rag-turn-warning { color: var(--warning); display: flex; align-items: center; gap: 6px; }
.rag-turn-references summary { cursor: pointer; color: var(--brand-ink); font-weight: 700; }
.rag-turn-references ol { padding-left: 20px; display: grid; gap: 8px; max-height: 240px; overflow: auto; }
.rag-turn-references li { overflow-wrap: anywhere; }
.rag-turn-references p { white-space: pre-wrap; color: var(--text-secondary); margin: 3px 0 0; line-height: 1.45; }

@keyframes slideIn {
  from {
    transform: translateY(8px);
    opacity: 0;
  }
  to {
    transform: none;
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
</style>
