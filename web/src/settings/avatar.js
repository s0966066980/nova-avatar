// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Avatar settings: the character library and import, mouth quality and the output size.
// The store in composables/useRuntimeSettings.js composes this with the other settings.

import { computed, reactive, ref } from 'vue'
import { parseJson, runtime, hooks } from './shared.js'

export const applyingAvatar = ref(false)

export const archivedCharacters = reactive({ items: [] })

export const selectedEngine = ref('')

export const selectedAvatarId = ref('')

export const filteredCharacters = computed(() => {
  if (!selectedEngine.value) return runtime.characters
  return runtime.characters.filter((item) => item.type === selectedEngine.value)
})

export const avatarDirty = computed(() => {
  const changed = (
    selectedEngine.value !== runtime.avatar.type ||
    selectedAvatarId.value !== runtime.avatar.avatar_id
  )
  return changed || !runtime.model_ready
})

export const selectedEngineInfo = computed(() => {
  return runtime.engines.find((item) => item.id === selectedEngine.value) || null
})

export const QUALITY_DEFAULTS = {
  mouth_sharpen: 0.5,
  paste_interpolation: 'lanczos',
  musetalk: {
    bbox_shift: 0,
    extra_margin: 10,
    parsing_mode: 'jaw',
    left_cheek_width: 90,
    right_cheek_width: 90,
    upper_boundary_ratio: 0.5,
    expand: 1.5,
    mask_blur_ratio: 0.05
  }
}

export function mergeQuality(raw) {
  const value = raw || {}
  return {
    mouth_sharpen: Number(value.mouth_sharpen ?? QUALITY_DEFAULTS.mouth_sharpen),
    paste_interpolation: value.paste_interpolation || QUALITY_DEFAULTS.paste_interpolation,
    musetalk: { ...QUALITY_DEFAULTS.musetalk, ...(value.musetalk || {}) }
  }
}

export const qualityDraft = reactive(mergeQuality())

export const applyingQuality = ref(false)

export const qualityError = ref('')

export const selectedOutputHeight = ref(0)

export const applyingVideo = ref(false)

export const videoError = ref('')

export const videoDirty = computed(() => selectedOutputHeight.value !== runtime.video.max_height)

export const outputHeightOptions = computed(() => {
  const values = [...runtime.video.height_options]
  for (const height of [runtime.video.max_height, selectedOutputHeight.value]) {
    if (!values.includes(height)) values.unshift(height)
  }
  return values
})

export const outputDimensions = computed(() => {
  const { source_width: width, source_height: height } = runtime.video
  if (!width || !height) return ''
  const limit = selectedOutputHeight.value
  if (!limit || limit >= height) return `${width} × ${height}`
  const outputHeight = Math.max(2, Math.floor(limit / 2) * 2)
  const outputWidth = Math.max(2, Math.floor(Math.round(width * outputHeight / height) / 2) * 2)
  return `${outputWidth} × ${outputHeight}`
})

export function assignQualityDraft(value) {
  const merged = mergeQuality(value)
  qualityDraft.mouth_sharpen = merged.mouth_sharpen
  qualityDraft.paste_interpolation = merged.paste_interpolation
  Object.assign(qualityDraft.musetalk, merged.musetalk)
}

export const qualityDirty = computed(() => (
  JSON.stringify(mergeQuality(qualityDraft)) !== JSON.stringify(mergeQuality(runtime.avatar_quality))
))

export async function applyVideoSettings() {
  applyingVideo.value = true
  videoError.value = ''
  try {
    const data = await parseJson(await fetch('/api/avatar/output', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_height: selectedOutputHeight.value })
    }))
    Object.assign(runtime.video, data)
    selectedOutputHeight.value = data.max_height
    return data
  } catch (error) {
    videoError.value = error.message
    throw error
  } finally {
    applyingVideo.value = false
  }
}

export async function applyMouthQuality() {
  applyingQuality.value = true
  qualityError.value = ''
  try {
    const data = await parseJson(await fetch('/api/avatar/quality', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mergeQuality(qualityDraft))
    }))
    runtime.avatar_quality = mergeQuality(data)
    assignQualityDraft(data)
    return data
  } catch (error) {
    qualityError.value = error.message
    throw error
  } finally {
    applyingQuality.value = false
  }
}

export const importing = ref(false)

export const importJob = ref(null)

export const importError = ref('')

export async function importCharacter({ file, engine, avatarId, overwrite = false, greenScreen = true }) {
  if (!file) {
    throw new Error('請選擇影片檔案')
  }
  importing.value = true
  importError.value = ''
  importJob.value = { status: 'queued', progress: 0, message: '正在上傳影片' }
  try {
    const form = new FormData()
    form.append('type', engine)
    form.append('green_screen', engine === 'musetalk' && greenScreen ? 'true' : 'false')
    if (avatarId) form.append('avatar_id', avatarId)
    if (overwrite) form.append('overwrite', 'true')
    form.append('quality', JSON.stringify(mergeQuality(qualityDraft)))
    // The server validates every field before storing the upload, so the video goes last.
    form.append('video', file)

    const started = await parseJson(await fetch('/api/avatars/import', {
      method: 'POST',
      body: form
    }))
    importJob.value = started
    return await pollImportJob(started.id)
  } catch (error) {
    importError.value = error.message
    throw error
  } finally {
    importing.value = false
  }
}

export async function deleteCharacter(avatarId) {
  const data = await parseJson(await fetch(`/api/avatars/${encodeURIComponent(avatarId)}`, { method: 'DELETE' }))
  await hooks.reload()
  await loadArchivedCharacters()
  return data
}

export async function loadArchivedCharacters() {
  const data = await parseJson(await fetch('/api/avatars/deleted'))
  archivedCharacters.items = data.items || []
  return data
}

export async function restoreCharacter(archiveName) {
  const data = await parseJson(await fetch(`/api/avatars/deleted/${encodeURIComponent(archiveName)}/restore`, {
    method: 'POST'
  }))
  await Promise.all([hooks.reload(), loadArchivedCharacters()])
  return data
}

export async function permanentlyDeleteCharacter(archiveName) {
  const data = await parseJson(await fetch(`/api/avatars/deleted/${encodeURIComponent(archiveName)}`, {
    method: 'DELETE'
  }))
  await loadArchivedCharacters()
  return data
}

export async function pollImportJob(jobId) {
  const started = Date.now()
  while (Date.now() - started < 30 * 60 * 1000) {
    const data = await parseJson(await fetch(`/api/avatars/import/${jobId}`))
    importJob.value = data
    if (data.status === 'done') {
      return data
    }
    if (data.status === 'failed') {
      throw new Error(data.error || data.message || '製作失敗')
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error('製作超時，請檢視後端日誌')
}

export async function applyAvatar(engine = selectedEngine.value, avatarId = selectedAvatarId.value) {
  applyingAvatar.value = true
  try {
    const data = await parseJson(await fetch('/api/avatar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: engine, avatar_id: avatarId })
    }))
    if (data.pending) return data
    runtime.avatar.type = data.type
    runtime.avatar.avatar_id = data.avatar_id
    runtime.model_ready = true
    selectedEngine.value = data.type
    selectedAvatarId.value = data.avatar_id
    return data
  } finally {
    applyingAvatar.value = false
  }
}

export function selectEngine(engineId) {
  const engine = runtime.engines.find((item) => item.id === engineId)
  if (!engine || (!engine.available && !engine.can_import)) return
  selectedEngine.value = engineId
  const stillValid = filteredCharacters.value.some((item) => item.id === selectedAvatarId.value)
  if (!stillValid) {
    const first = filteredCharacters.value[0]
    selectedAvatarId.value = first ? first.id : ''
  }
}

export function selectCharacter(avatarId) {
  const character = runtime.characters.find((item) => item.id === avatarId)
  if (!character) return
  selectedEngine.value = character.type
  selectedAvatarId.value = character.id
}
