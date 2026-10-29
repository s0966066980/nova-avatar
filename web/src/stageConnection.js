// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// 舞台是無人看管的公開畫面：任何請求或連線步驟都必須有上限，
// 卡住時要能露出重試並自動重連，而不是永遠停在「連線中」。

// 設定輪詢每 5 秒一次，逾時要短於週期才不會堆積請求。
export const STAGE_POLL_TIMEOUT_MS = 4000
// /offer 需要後端建立會話，給較長時間。
export const STAGE_OFFER_TIMEOUT_MS = 15000
// 從開始連線到 WebRTC connected 的整體看門狗。
export const STAGE_CONNECT_TIMEOUT_MS = 25000

export class StageTimeoutError extends Error {
  constructor(url, timeoutMs) {
    super('連線逾時')
    this.name = 'TimeoutError'
    this.url = url
    this.timeoutMs = timeoutMs
  }
}

// fetch 並讀取 JSON，整段（含回應內容）都受同一個逾時限制。
// 非 JSON 回應不算錯誤，data 為 null，由呼叫端依 ok/status 判斷。
export async function fetchJsonWithTimeout(url, options = {}, timeoutMs = STAGE_POLL_TIMEOUT_MS, {
  fetchImpl = globalThis.fetch,
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
} = {}) {
  const controller = new AbortController()
  let timer = null
  // 不只依賴 fetch 尊重 signal：逾時一到就以競賽結果拋出，保證有上限。
  const expired = new Promise((_resolve, reject) => {
    timer = setTimer(() => {
      const error = new StageTimeoutError(url, timeoutMs)
      controller.abort(error)
      reject(error)
    }, timeoutMs)
  })
  const request = (async () => {
    const response = await fetchImpl(url, { ...options, signal: controller.signal })
    let data = null
    try {
      data = await response.json()
    } catch (error) {
      if (controller.signal.aborted) throw controller.signal.reason
    }
    return { ok: Boolean(response.ok), status: response.status, data }
  })()
  try {
    return await Promise.race([request, expired])
  } catch (error) {
    if (controller.signal.aborted) throw controller.signal.reason
    throw error
  } finally {
    clearTimer(timer)
    request.catch(() => {})
    expired.catch(() => {})
  }
}
