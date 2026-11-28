// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import { composerDefaults, composerSettings } from '../conversationAttachments.js'
import { computed, reactive, ref, watch } from 'vue'
import { hooks, parseJson, runtime } from '../settings/shared.js'
import {
  ollama,
  llamacpp,
  selectedProvider,
  loadingModels,
  applyingLlm,
  modelsError,
  selectedLlm,
  selectedSystemPrompt,
  selectedRestrictionPrompt,
  selectedAssistantName,
  selectedOutputLocale,
  selectedEnforceOutputLocale,
  selectedForbiddenSelfNames,
  selectedResponseMaxChars,
  selectedBoardMaxItems,
  selectedReplyMode,
  selectedSemanticWaitSeconds,
  rulesDraft,
  rulesApplied,
  rulesDefaults,
  rulesLimits,
  rulesLoading,
  rulesSaving,
  rulesError,
  rulesNotice,
  rulesDirty,
  responseLengthError,
  boardItemsError,
  currentProviderModels,
  promptDirty,
  llmDirty,
  loadReplyRules,
  restoreDefaultRules,
  applyReplyRules,
  applyLlmBehavior,
  loadOllamaModels,
  applyLlmModel,
  selectProvider
} from '../settings/llm.js'
import {
  applyingStage,
  backgrounds,
  stageError,
  selectedStageCaptionMaxChars,
  selectedVisitorResetSeconds,
  selectedClearDisplaySeconds,
  composerDraft,
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
  stageCaptionLengthError,
  visitorResetError,
  applyingVisitor,
  visitorError,
  visitorDirty,
  applyVisitorSettings,
  boardSizeError,
  stageDirty,
  selectBoardPreset,
  markBoardPositionCustom,
  selectMicPreset,
  markMicPositionCustom,
  applyStageSettings,
  loadBackgrounds,
  deleteBackground,
  restoreBackground,
  uploadBackground,
  selectBackground
} from '../settings/stage.js'
import {
  applyingAvatar,
  archivedCharacters,
  selectedEngine,
  selectedAvatarId,
  filteredCharacters,
  avatarDirty,
  selectedEngineInfo,
  mergeQuality,
  qualityDraft,
  applyingQuality,
  qualityError,
  selectedOutputHeight,
  applyingVideo,
  videoError,
  videoDirty,
  outputHeightOptions,
  outputDimensions,
  assignQualityDraft,
  qualityDirty,
  applyVideoSettings,
  applyMouthQuality,
  importing,
  importJob,
  importError,
  importCharacter,
  deleteCharacter,
  loadArchivedCharacters,
  restoreCharacter,
  permanentlyDeleteCharacter,
  applyAvatar,
  selectEngine,
  selectCharacter
} from '../settings/avatar.js'
import {
  SILERO_ENGINE,
  vad,
  vadDraft,
  speech,
  sttDraft,
  applyingStt,
  speechError,
  voiceLibraryBusy,
  applyingVad,
  comparingVad,
  vadError,
  vadCompareError,
  vadCompareResult,
  vadDirty,
  sttDirty,
  STT_ENGINE_FALLBACK,
  sttEngineOptions,
  selectedSttEngine,
  sttModelOptions,
  ttsVoiceOptions,
  selectedVadEngine,
  applyVadSnapshot,
  applySpeechSnapshot,
  loadSpeechSettings,
  applySttSettings,
  refreshTtsVoices,
  uploadTtsVoice,
  deleteTtsVoice,
  previewVoiceFields,
  breezyVoiceServerReady,
  previewProfileVoice,
  loadVadSettings,
  compareVadEngines,
  applyVadSettings
} from '../settings/speech.js'

const loadingSettings = ref(false)
const settingsError = ref('')
watch(() => sttDraft.type, () => {
  if (sttModelOptions.value.length && !sttModelOptions.value.includes(sttDraft.model_size)) {
    sttDraft.model_size = sttModelOptions.value[0]
  }
})

function applySnapshot(data) {
  runtime.pending_settings = data.pending_settings || { items: [], error: '' }
  runtime.llm = data.llm
  const snapshotRules = data.llm?.reply_rules
  if (snapshotRules) {
    Object.assign(rulesApplied, snapshotRules)
    Object.assign(rulesDraft, {
      activation: snapshotRules.activation || '',
      speech: snapshotRules.speech || '',
      board: snapshotRules.board || ''
    })
  }
  Object.assign(composerDraft, composerSettings(data.stage))
  runtime.stage = {
    ...composerSettings(data.stage),
    background_id: data.stage?.background_id || '',
    caption_max_chars: Number(data.stage?.caption_max_chars || 120),
    idle_reset_seconds: Number(data.stage?.idle_reset_seconds || 60),
    idle_greeting_enabled: Boolean(data.stage?.idle_greeting_enabled),
    idle_greeting_seconds: Number(data.stage?.idle_greeting_seconds ?? 30),
    caption_x: Number(data.stage?.caption_x ?? 50),
    caption_y: Number(data.stage?.caption_y ?? 90),
    caption_width: Number(data.stage?.caption_width ?? 100),
    board_style: data.stage?.board_style || 'glass',
    board_width: Number(data.stage?.board_width || 252),
    board_height: Number(data.stage?.board_height || 300),
    board_transparency: Number(data.stage?.board_transparency ?? 28),
    board_x: Number(data.stage?.board_x ?? 100),
    board_y: Number(data.stage?.board_y ?? 0),
    board_preset: data.stage?.board_preset || 'tr',
    board_preview: Boolean(data.stage?.board_preview),
    board_open_x: Number(data.stage?.board_open_x ?? 50),
    board_open_y: Number(data.stage?.board_open_y ?? 8),
    mic_x: Number(data.stage?.mic_x ?? 50),
    mic_y: Number(data.stage?.mic_y ?? 62),
    mic_preset: data.stage?.mic_preset || 'custom'
  }
  runtime.avatar = data.avatar
  Object.assign(runtime.video, data.video || {})
  selectedOutputHeight.value = runtime.video.max_height
  runtime.avatar_quality = mergeQuality(data.avatar_quality)
  assignQualityDraft(runtime.avatar_quality)
  runtime.engines = data.engines || []
  runtime.characters = data.characters || []
  runtime.session_count = data.session_count || 0
  runtime.switching = Boolean(data.switching)
  runtime.ready = Boolean(data.ready)
  runtime.model_ready = Boolean(data.model_ready)
  applyVadSnapshot(data.vad)
  applySpeechSnapshot(data.speech)
  selectedEngine.value = data.avatar?.type || ''
  selectedAvatarId.value = data.avatar?.avatar_id || ''
  selectedProvider.value = data.llm?.provider || selectedProvider.value || 'ollama'
  if (!selectedLlm.value || selectedLlm.value === runtime.llm.model) {
    selectedLlm.value = data.llm?.model || ''
  }
  selectedSystemPrompt.value = data.llm?.system_prompt || ''
  selectedRestrictionPrompt.value = data.llm?.assistant_profile?.restriction_prompt || ''
  selectedAssistantName.value = data.llm?.assistant_profile?.assistant_name || ''
  selectedOutputLocale.value = data.llm?.assistant_profile?.output_locale || 'zh-TW'
  selectedEnforceOutputLocale.value = Boolean(data.llm?.assistant_profile?.enforce_output_locale ?? true)
  selectedForbiddenSelfNames.value = (data.llm?.assistant_profile?.forbidden_self_names || []).join('\n')
  selectedResponseMaxChars.value = Number(data.llm?.response_max_chars || 120)
  selectedBoardMaxItems.value = Number(data.llm?.board_max_items || 8)
  selectedReplyMode.value = data.llm?.reply_mode || 'legacy'
  selectedSemanticWaitSeconds.value = Number(data.llm?.semantic_wait_seconds || 0.5)
  selectedStageCaptionMaxChars.value = runtime.stage.caption_max_chars
  selectedVisitorResetSeconds.value = runtime.stage.idle_reset_seconds
  selectedClearDisplaySeconds.value = Number(data.stage?.clear_display_seconds ?? 15)
  selectedCaptionX.value = runtime.stage.caption_x
  selectedCaptionY.value = runtime.stage.caption_y
  selectedCaptionWidth.value = runtime.stage.caption_width
  selectedBoardStyle.value = runtime.stage.board_style
  selectedBoardWidth.value = runtime.stage.board_width
  selectedBoardHeight.value = runtime.stage.board_height
  selectedBoardTransparency.value = runtime.stage.board_transparency
  selectedBoardX.value = runtime.stage.board_x
  selectedBoardY.value = runtime.stage.board_y
  selectedBoardPreset.value = runtime.stage.board_preset
  selectedBoardPreview.value = runtime.stage.board_preview
  selectedBoardOpenX.value = runtime.stage.board_open_x
  selectedBoardOpenY.value = runtime.stage.board_open_y
  selectedMicX.value = runtime.stage.mic_x
  selectedMicY.value = runtime.stage.mic_y
  selectedMicPreset.value = runtime.stage.mic_preset
}

async function loadRuntimeSettings() {
  loadingSettings.value = true
  settingsError.value = ''
  try {
    const data = await parseJson(await fetch('/api/settings'))
    applySnapshot(data)
    await loadReplyRules()
    return data
  } catch (error) {
    settingsError.value = error.message
    throw error
  } finally {
    loadingSettings.value = false
  }
}

// Characters are deleted and restored by the avatar settings; they reload everything afterwards.
hooks.reload = loadRuntimeSettings

export function useRuntimeSettings() {
  return {
    runtime,
    ollama,
    llamacpp,
    selectedProvider,
    currentProviderModels,
    loadingSettings,
    loadingModels,
    applyingLlm,
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
    settingsError,
    modelsError,
    stageError,
    selectedEngine,
    selectedAvatarId,
    selectedLlm,
  selectedSystemPrompt,
  selectedRestrictionPrompt,
  selectedAssistantName,
  selectedOutputLocale,
  selectedEnforceOutputLocale,
  selectedForbiddenSelfNames,
    selectedResponseMaxChars,
    selectedBoardMaxItems,
    selectedReplyMode,
    selectedSemanticWaitSeconds,
    rulesDraft,
    rulesApplied,
    rulesDefaults,
    rulesLimits,
    rulesLoading,
    rulesSaving,
    rulesError,
    rulesNotice,
    rulesDirty,
    loadReplyRules,
    restoreDefaultRules,
    applyReplyRules,
    applyLlmBehavior,
    promptDirty,
    selectedStageCaptionMaxChars,
    selectedVisitorResetSeconds,
    selectedClearDisplaySeconds,
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
    responseLengthError,
    boardItemsError,
    stageCaptionLengthError,
    filteredCharacters,
    llmDirty,
    stageDirty,
    composerDraft,
    avatarDirty,
    selectedEngineInfo,
    loadRuntimeSettings,
    loadOllamaModels,
    applyLlmModel,
    applyStageSettings,
    applyAvatar,
    applyMouthQuality,
    selectedOutputHeight,
    outputHeightOptions,
    outputDimensions,
    videoDirty,
    applyingVideo,
    videoError,
    applyVideoSettings,
    qualityDraft,
    qualityDirty,
    applyingQuality,
    qualityError,
    importCharacter,
    importing,
    importJob,
    importError,
    selectProvider,
    selectEngine,
    selectCharacter,
    vad,
    vadDraft,
    vadDirty,
    vadError,
    applyingVad,
    comparingVad,
    selectedVadEngine,
    vadCompareError,
    vadCompareResult,
    loadVadSettings,
    applyVadSettings,
    compareVadEngines,
    speech,
    sttDraft,
    sttDirty,
    sttEngineOptions,
    selectedSttEngine,
    sttModelOptions,
    ttsVoiceOptions,
    voiceLibraryBusy,
    refreshTtsVoices,
    uploadTtsVoice,
    deleteTtsVoice,
    breezyVoiceServerReady,
    previewProfileVoice,
    applyingStt,
    speechError,
    loadSpeechSettings,
    applySttSettings
  }
}
