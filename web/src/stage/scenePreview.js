// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

export function avatarScenePreviewUrl(character, backgroundId) {
  if (!character) return ''
  const original = character.preview_url || character.thumbnail || ''
  if (!character.green_screen || !backgroundId || !character.id) return original
  return `/api/avatars/${encodeURIComponent(character.id)}/scene-preview?background_id=${encodeURIComponent(backgroundId)}`
}
