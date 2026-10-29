<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 控制台 Markdown 淨化
Status: ready-for-agent

依[規格](../spec.md)。`web/src/App.vue:183` 以 `v-html` 渲染 `marked.parse()`（`:563-571`），無 sanitizer；`sanitizeChatText`（`:520`）只剝協定標記。LLM 輸出可被 RAGFlow 文件、附件 OCR 操控 → 控制台 XSS。`marked` 的 `highlight` 選項自 v5 已移除（`:488`），highlight.js 從未生效卻被打包。

- 抽出 markdown 渲染為獨立模組（便於 `node --test`）：`marked` renderer 丟棄原始 HTML token，輸出再經 `DOMPurify.sanitize()`。
- `sanitizeChatText` 改名為 `stripProtocolMarkers`（全部呼叫點）。
- 移除 highlight.js 依賴與設定。
- ESLint：`vue/no-v-html: error`；唯一 sink 加單行 disable 註解並說明已淨化。
- 測試：`<img src=x onerror=…>`、`<script>`、`[x](javascript:…)`、`<a href="javascript:…">` 輸出皆無害；一般 Markdown（粗體、清單、連結）仍正常。

完成：`npm run lint`、`npm test`、`npm run build` 通過。

## Comments
