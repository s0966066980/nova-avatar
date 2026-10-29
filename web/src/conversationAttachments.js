// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import { previewScale } from './stageBoardLayout.js'

export const composerDefaults = {
  composer_enabled: false, composer_x: 50, composer_y: 78, composer_width: 90,
  composer_height: 220, composer_font_size: 16, composer_opacity: 92,
  composer_placeholder_zh: '輸入問題，或附上 PDF／圖片',
  composer_placeholder_en: 'Ask a question or attach a PDF / image'
}

export function composerSettings(values = {}) {
  return Object.fromEntries(Object.entries(composerDefaults).map(([key, fallback]) => [key, values[key] ?? fallback]))
}

export function composerGeometry(settings, width, height, { availableHeight = height } = {}) {
  const scale = previewScale(width, height)
  const pad = 12 * scale
  const w = Math.max(0, width - pad * 2) * Math.min(100, Math.max(40, settings.composer_width)) / 100
  const maxHeight = Math.max(40, availableHeight - pad * 2)
  const h = Math.min((settings.composer_height ?? composerDefaults.composer_height) * scale, maxHeight)
  return { width: w, height: h, pad, maxHeight,
    left: pad + Math.max(0, width - w - pad * 2) * settings.composer_x / 100,
    top: pad + Math.max(0, availableHeight - h - pad * 2) * settings.composer_y / 100,
    fontSize: Math.max(12, settings.composer_font_size * scale) }
}

export function composerPlacement(settings, width, height, options) {
  const box = composerGeometry(settings, width, height, options)
  return { width: `${box.width}px`, height: `${box.height}px`,
    left: `${box.left}px`, top: `${box.top}px`,
    fontSize: `${box.fontSize}px`, maxHeight: `${box.maxHeight}px`,
    '--composer-pad': `${box.pad}px`,
    background: `rgba(19, 27, 42, ${settings.composer_opacity / 100})` }
}

export function validateDraft(files, referenceCount) {
  if (files.length + referenceCount > 4) throw new Error('reference_limit')
  for (const file of files) {
    if (!/\.(pdf|jpe?g|png|webp)$/i.test(file.name)) throw new Error('unsupported_file')
    if (!file.size || file.size > 20_000_000) throw new Error('file_size')
  }
}

export function shouldSend(event) {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229
}

export async function attachmentRequest(url, options = {}) {
  const response = await fetch(url, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok || data.code === -1) throw new Error(data.msg || `HTTP ${response.status}`)
  return data.data ?? data
}
