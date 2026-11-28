// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Stage settings: captions, boards, microphone and visitor timing, and the stage backgrounds.
// The store in composables/useRuntimeSettings.js composes this with the other settings.

import { computed, reactive, ref } from 'vue'
import { parseJson, runtime } from './shared.js'
import { composerDefaults, composerSettings } from '../conversationAttachments.js'

export const applyingStage = ref(false)

export const backgrounds = reactive({ items: [], archivedItems: [], background_id: '', loading: false, busy: false, error: '' })

export const stageError = ref('')

export const selectedStageCaptionMaxChars = ref(120)

export const selectedVisitorResetSeconds = ref(60)

export const selectedClearDisplaySeconds = ref(15)

export const composerDraft = reactive({ ...composerDefaults })

export const selectedCaptionX = ref(50)

export const selectedCaptionY = ref(90)

export const selectedCaptionWidth = ref(100)

export const selectedBoardStyle = ref('glass')

export const selectedBoardWidth = ref(252)

export const selectedBoardHeight = ref(300)

export const selectedBoardTransparency = ref(28)

export const selectedBoardX = ref(100)

export const selectedBoardY = ref(0)

export const selectedBoardPreset = ref('tr')

export const selectedBoardPreview = ref(false)

export const isStageConfiguring = ref(false)

export const selectedBoardOpenX = ref(50)

export const selectedBoardOpenY = ref(8)

export const selectedMicX = ref(50)

export const selectedMicY = ref(62)

export const selectedMicPreset = ref('custom')

export const BOARD_PRESETS = {
  tl: [0, 0],
  tc: [50, 0],
  tr: [100, 0],
  ml: [0, 50],
  mc: [50, 50],
  mr: [100, 50],
  bl: [0, 100],
  bc: [50, 100],
  br: [100, 100]
}

export const stageCaptionLengthError = computed(() => {
  const value = Number(selectedStageCaptionMaxChars.value)
  return !Number.isInteger(value) || value < 20 || value > 2000
})

export const visitorResetError = computed(() => {
  const value = Number(selectedVisitorResetSeconds.value)
  return !Number.isInteger(value) || value < 3 || value > 300 || !Number.isInteger(selectedClearDisplaySeconds.value) || selectedClearDisplaySeconds.value < 1 || selectedClearDisplaySeconds.value > value
})

export const applyingVisitor = ref(false)

export const visitorError = ref('')

export const visitorDirty = computed(() => !visitorResetError.value && (selectedVisitorResetSeconds.value !== runtime.stage.idle_reset_seconds || selectedClearDisplaySeconds.value !== runtime.stage.clear_display_seconds))

export async function applyVisitorSettings() {
  if (visitorResetError.value) throw new Error('訪客對話重置時間必須介於 3–300 秒。')
  applyingVisitor.value = true
  visitorError.value = ''
  try {
    const data = await parseJson(await fetch('/api/stage', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ idle_reset_seconds: selectedVisitorResetSeconds.value, clear_display_seconds: selectedClearDisplaySeconds.value })
    }))
    runtime.stage.clear_display_seconds = Number(data.clear_display_seconds)
    runtime.stage.idle_reset_seconds = Number(data.idle_reset_seconds)
    selectedVisitorResetSeconds.value = runtime.stage.idle_reset_seconds
    selectedClearDisplaySeconds.value = Number(data.clear_display_seconds ?? 15)
    return data
  } catch (error) { visitorError.value = error.message; throw error }
  finally { applyingVisitor.value = false }
}

export const boardSizeError = computed(() => {
  const width = Number(selectedBoardWidth.value)
  const height = Number(selectedBoardHeight.value)
  const transparency = Number(selectedBoardTransparency.value)
  const x = Number(selectedBoardX.value)
  const y = Number(selectedBoardY.value)
  const captionX = Number(selectedCaptionX.value)
  const captionY = Number(selectedCaptionY.value)
  const captionWidth = Number(selectedCaptionWidth.value)
  return (
    !Number.isInteger(width) || width < 200 || width > 720 ||
    !Number.isInteger(height) || height < 180 || height > 720 ||
    !Number.isInteger(transparency) || transparency < 0 || transparency > 100 ||
    !Number.isInteger(x) || x < 0 || x > 100 ||
    !Number.isInteger(y) || y < 0 || y > 100 ||
    !Number.isInteger(captionX) || captionX < 0 || captionX > 100 ||
    !Number.isInteger(captionY) || captionY < 0 || captionY > 100 ||
    !Number.isInteger(captionWidth) || captionWidth < 40 || captionWidth > 100
  )
})

export const stageDirty = computed(() => (
    Object.keys(composerDefaults).some(key => composerDraft[key] !== (runtime.stage[key] ?? composerDefaults[key])) ||
  !stageCaptionLengthError.value &&
  !boardSizeError.value &&
  (
    Number(selectedStageCaptionMaxChars.value) !== Number(runtime.stage.caption_max_chars || 120) ||
    Number(selectedCaptionX.value) !== Number(runtime.stage.caption_x ?? 50) ||
    Number(selectedCaptionY.value) !== Number(runtime.stage.caption_y ?? 90) ||
    Number(selectedCaptionWidth.value) !== Number(runtime.stage.caption_width ?? 100) ||
    selectedBoardStyle.value !== (runtime.stage.board_style || 'glass') ||
    Number(selectedBoardWidth.value) !== Number(runtime.stage.board_width || 252) ||
    Number(selectedBoardHeight.value) !== Number(runtime.stage.board_height || 300) ||
    Number(selectedBoardTransparency.value) !== Number(runtime.stage.board_transparency || 28) ||
    Number(selectedBoardX.value) !== Number(runtime.stage.board_x || 100) ||
    Number(selectedBoardY.value) !== Number(runtime.stage.board_y || 0) ||
    selectedBoardPreset.value !== (runtime.stage.board_preset || 'tr') ||
    Boolean(selectedBoardPreview.value) !== Boolean(runtime.stage.board_preview) ||
    Number(selectedBoardOpenX.value) !== Number(runtime.stage.board_open_x ?? 50) ||
    Number(selectedBoardOpenY.value) !== Number(runtime.stage.board_open_y ?? 8) ||
    Number(selectedMicX.value) !== Number(runtime.stage.mic_x ?? 50) ||
    Number(selectedMicY.value) !== Number(runtime.stage.mic_y ?? 62) ||
    selectedMicPreset.value !== (runtime.stage.mic_preset || 'custom')
  )
))

export function selectBoardPreset(preset) {
  selectedBoardPreset.value = preset
  const point = BOARD_PRESETS[preset]
  if (point) {
    selectedBoardX.value = point[0]
    selectedBoardY.value = point[1]
  }
}

export function markBoardPositionCustom() {
  selectedBoardPreset.value = 'custom'
}

export function selectMicPreset(preset) {
  selectedMicPreset.value = preset
  const point = BOARD_PRESETS[preset]
  if (point) {
    selectedMicX.value = point[0]
    selectedMicY.value = point[1]
  }
}

export function markMicPositionCustom() {
  selectedMicPreset.value = 'custom'
}

export async function applyStageSettings(
  captionMaxChars = selectedStageCaptionMaxChars.value
) {
  applyingStage.value = true
  stageError.value = ''
  try {
    const data = await parseJson(await fetch('/api/stage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...composerDraft,
        caption_max_chars: Number(captionMaxChars),
        caption_x: Number(selectedCaptionX.value),
        caption_y: Number(selectedCaptionY.value),
        caption_width: Number(selectedCaptionWidth.value),
        board_style: selectedBoardStyle.value,
        board_width: Number(selectedBoardWidth.value),
        board_height: Number(selectedBoardHeight.value),
        board_transparency: Number(selectedBoardTransparency.value),
        board_x: Number(selectedBoardX.value),
        board_y: Number(selectedBoardY.value),
        board_preset: selectedBoardPreset.value,
        board_preview: Boolean(selectedBoardPreview.value),
        board_open_x: Number(selectedBoardOpenX.value),
        board_open_y: Number(selectedBoardOpenY.value),
        mic_x: Number(selectedMicX.value),
        mic_y: Number(selectedMicY.value),
        mic_preset: selectedMicPreset.value
      })
    }))
    Object.assign(runtime.stage, composerSettings(data))
    Object.assign(composerDraft, composerSettings(data))
    runtime.stage.caption_max_chars = Number(data.caption_max_chars)
    runtime.stage.idle_reset_seconds = Number(data.idle_reset_seconds ?? selectedVisitorResetSeconds.value)
    runtime.stage.caption_x = Number(data.caption_x ?? selectedCaptionX.value)
    runtime.stage.caption_y = Number(data.caption_y ?? selectedCaptionY.value)
    runtime.stage.caption_width = Number(data.caption_width ?? selectedCaptionWidth.value)
    runtime.stage.board_style = data.board_style
    runtime.stage.board_width = Number(data.board_width)
    runtime.stage.board_height = Number(data.board_height)
    runtime.stage.board_transparency = Number(data.board_transparency)
    runtime.stage.board_x = Number(data.board_x)
    runtime.stage.board_y = Number(data.board_y)
    runtime.stage.board_preset = data.board_preset
    runtime.stage.board_preview = Boolean(data.board_preview)
    runtime.stage.board_open_x = Number(data.board_open_x)
    runtime.stage.board_open_y = Number(data.board_open_y)
    selectedStageCaptionMaxChars.value = runtime.stage.caption_max_chars
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
    runtime.stage.mic_x = Number(data.mic_x)
    runtime.stage.mic_y = Number(data.mic_y)
    runtime.stage.mic_preset = data.mic_preset
    selectedMicX.value = runtime.stage.mic_x
    selectedMicY.value = runtime.stage.mic_y
    selectedMicPreset.value = runtime.stage.mic_preset
    return data
  } catch (error) {
    stageError.value = error.message
    throw error
  } finally {
    applyingStage.value = false
  }
}

export async function loadBackgrounds() {
  backgrounds.loading = true
  backgrounds.error = ''
  try {
    const [activeResponse, archivedResponse] = await Promise.all([
      fetch('/api/backgrounds'),
      fetch('/api/backgrounds/deleted')
    ])
    const [data, archived] = await Promise.all([
      parseJson(activeResponse),
      parseJson(archivedResponse)
    ])
    backgrounds.items = data.items || []
    backgrounds.archivedItems = archived.items || []
    backgrounds.background_id = data.background_id || ''
    return data
  } catch (error) {
    backgrounds.error = error.message
    throw error
  } finally {
    backgrounds.loading = false
  }
}

export async function deleteBackground(backgroundId) {
  backgrounds.busy = true
  backgrounds.error = ''
  try {
    const result = await parseJson(await fetch(`/api/backgrounds/${encodeURIComponent(backgroundId)}`, {
      method: 'DELETE'
    }))
    await loadBackgrounds()
    return result
  } catch (error) {
    backgrounds.error = error.message
    throw error
  } finally {
    backgrounds.busy = false
  }
}

export async function restoreBackground(archiveName) {
  backgrounds.busy = true
  backgrounds.error = ''
  try {
    const result = await parseJson(await fetch(`/api/backgrounds/deleted/${encodeURIComponent(archiveName)}/restore`, {
      method: 'POST'
    }))
    await loadBackgrounds()
    return result
  } catch (error) {
    backgrounds.error = error.message
    throw error
  } finally {
    backgrounds.busy = false
  }
}

export async function uploadBackground(file) {
  if (!file) throw new Error('請先選擇背景檔案')
  backgrounds.busy = true
  backgrounds.error = ''
  try {
    const form = new FormData()
    form.append('background', file)
    const item = await parseJson(await fetch('/api/backgrounds', { method: 'POST', body: form }))
    await loadBackgrounds()
    return item
  } catch (error) {
    backgrounds.error = error.message
    throw error
  } finally {
    backgrounds.busy = false
  }
}

export async function selectBackground(backgroundId) {
  backgrounds.busy = true
  backgrounds.error = ''
  try {
    const data = await parseJson(await fetch('/api/background', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ background_id: backgroundId })
    }))
    backgrounds.background_id = data.background_id || ''
    runtime.stage.background_id = backgrounds.background_id
    return data
  } catch (error) {
    backgrounds.error = error.message
    throw error
  } finally {
    backgrounds.busy = false
  }
}
