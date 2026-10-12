// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// 訪客只看得到簡短提示；後端錯誤代碼與例外文字不上舞台。
export const STAGE_TURN_ERROR_MESSAGE = '剛才出了點狀況，請再說一次'
export const STAGE_UNAVAILABLE_MESSAGE = '數字人暫時無法使用，請稍候'

export function stageErrorMessage(event) {
  if (!event || event.type !== 'state' || !event.error) return null
  if (event.state === 'error') return STAGE_TURN_ERROR_MESSAGE
  if (event.state === 'degraded') return STAGE_UNAVAILABLE_MESSAGE
  return null
}
