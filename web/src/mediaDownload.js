// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Same-origin fetch uses the page's accepted HTTPS connection. A direct
// navigation download can be cancelled by Chromium's certificate checks.
export async function downloadMedia(url, filename = 'avatar.mp4') {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`下載失敗（HTTP ${response.status}）`)
  const blob = await response.blob()
  if (!blob.size) throw new Error('下載的影片是空檔案')
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  document.body.appendChild(link)
  try { link.click() }
  finally {
    link.remove()
    // Browsers need time to hand the Blob to the download manager.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000)
  }
}
