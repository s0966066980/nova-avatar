// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

/** 9:16 舞台上，看板與麥克風的共用定位。控制台對照與獨立舞台必須用同一套公式。 */

export const STAGE_LAYOUT_REF_WIDTH = 405
export const STAGE_LAYOUT_REF_HEIGHT = 720
export const STAGE_BOARD_PAD = 12
export const STAGE_CAPTION_RATIO = 0.2

export const STAGE_BOARD_PREVIEW_ITEMS = [
  { title: '先定義展示目標', body: '選定一個主要情境，例如接待、導覽或常見問題。' },
  { title: '確認人物與聲音', body: '檢查數字人構圖、音量與嘴型，用一段短句試播。' },
  { title: '安排互動與看板', body: '調整看板與麥克風位置，讓人物、字幕和條列都能閱讀。' },
  { title: '彩排異常情境', body: '試一次關閉再開看板，下一輪對話應清掉舊項目。' }
]

export const STAGE_BOARD_PREVIEW_TITLE = '第一次展示，準備這四件事'

export function placeStageBoard({
  stageW,
  stageH,
  targetW,
  targetH,
  x,
  y,
  scale = 1,
  pad = STAGE_BOARD_PAD,
  captionRatio = STAGE_CAPTION_RATIO
}) {
  const captionH = Math.max(24 * scale, stageH * captionRatio)
  const inset = Math.max(4, pad * scale)
  const maxW = Math.max(16, stageW - inset * 2)
  const maxH = Math.max(16, stageH - inset - captionH)
  const width = Math.min(Math.max(16, targetW * scale), maxW)
  const height = Math.min(Math.max(16, targetH * scale), maxH)
  const dx = Math.max(0, maxW - width)
  const dy = Math.max(0, maxH - height)
  return {
    width,
    height,
    left: inset + dx * clampPercent(x) / 100,
    top: inset + dy * clampPercent(y) / 100,
    captionH,
    inset
  }
}

export function previewScale(previewW, previewH) {
  return Math.min(previewW / STAGE_LAYOUT_REF_WIDTH, previewH / STAGE_LAYOUT_REF_HEIGHT)
}

export function micStyle(x, y) {
  return {
    left: `${clampPercent(x)}%`,
    top: `${clampPercent(y)}%`,
    transform: 'translate(-50%, -50%)'
  }
}

export function boardReopenPresentation(x, y) {
  const horizontal = clampPercent(x)
  const vertical = clampPercent(y)
  const edge = horizontal <= 8 ? 'left' : horizontal >= 92 ? 'right' : 'center'
  return {
    edge,
    icon: edge === 'left' ? '›' : edge === 'right' ? '‹' : '▣',
    style: {
      left: `${horizontal}%`,
      top: `${vertical}%`,
      transform: edge === 'left'
        ? 'translate(0, -50%)'
        : edge === 'right'
          ? 'translate(-100%, -50%)'
          : 'translate(-50%, -50%)'
    }
  }
}

export function captionStyle(x, y, width) {
  const safeWidth = Math.max(40, Math.min(100, Number(width) || 100))
  const halfWidth = safeWidth / 2
  const horizontal = Math.max(halfWidth, Math.min(100 - halfWidth, clampPercent(x)))
  return {
    left: `${horizontal}%`,
    top: `${clampPercent(y)}%`,
    width: `${safeWidth}%`,
    transform: 'translate(-50%, -50%)'
  }
}

function clampPercent(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(100, n))
}
