// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// kiosk 標記只由場域啟動腳本帶上；一般開啟舞台時保持原本的點擊進入。
const RECONNECT_DELAYS_MS = [2000, 3000, 5000, 8000, 10000]

export const KIOSK_UNAVAILABLE_TITLE = '數字人暫時無法使用'
export const KIOSK_UNAVAILABLE_TEXT = '正在重新連線，請稍候。'

export function isKioskMode(search) {
  return new URLSearchParams(String(search || '')).get('kiosk') === '1'
}

export function kioskReconnectDelayMs(attempt) {
  const index = Math.min(Math.max(Number(attempt) || 0, 0), RECONNECT_DELAYS_MS.length - 1)
  return RECONNECT_DELAYS_MS[index]
}
