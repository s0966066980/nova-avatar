<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 控制台 Markdown 淨化
Status: resolved

依[規格](../spec.md)。`web/src/App.vue:183` 以 `v-html` 渲染 `marked.parse()`（`:563-571`），無 sanitizer；`sanitizeChatText`（`:520`）只剝協定標記。LLM 輸出可被 RAGFlow 文件、附件 OCR 操控 → 控制台 XSS。`marked` 的 `highlight` 選項自 v5 已移除（`:488`），highlight.js 從未生效卻被打包。

- 抽出 markdown 渲染為獨立模組（便於 `node --test`）：`marked` renderer 丟棄原始 HTML token，輸出再經 `DOMPurify.sanitize()`。
- `sanitizeChatText` 改名為 `stripProtocolMarkers`（全部呼叫點）。
- 移除 highlight.js 依賴與設定。
- ESLint：`vue/no-v-html: error`；唯一 sink 加單行 disable 註解並說明已淨化。
- 測試：`<img src=x onerror=…>`、`<script>`、`[x](javascript:…)`、`<a href="javascript:…">` 輸出皆無害；一般 Markdown（粗體、清單、連結）仍正常。

完成：`npm run lint`、`npm test`、`npm run build` 通過。

## Comments

### 2026-10-29 實作結果
- 新增 `web/src/markdown.js`：`stripProtocolMarkers`（原 `sanitizeChatText`，全部呼叫點已改名）與 `createMarkdownRenderer(purifier)`；`marked` renderer 丟棄原始 HTML token，輸出經 `DOMPurify.sanitize()`。無 DOM（`isSupported` 為假）或解析失敗時改輸出跳脫後純文字（原本解析失敗會把未淨化字串送進 `v-html`）。
- 移除 highlight.js 依賴、`marked.setOptions` 的無效 `highlight` 與其 CSS。
- 新依賴（固定版本）：`dompurify@3.4.17`；devDependency `jsdom@30.1.3`，供 `node --test` 建立 DOMPurify 實例。
- ESLint：`src/**` 啟用 `vue/no-v-html: error`；`App.vue` 唯一 sink 加單行 disable 註解。
- 測試：`web/tests/markdown.test.js`（5 項）涵蓋 `<img onerror>`、`<script>`、`javascript:` 連結、一般 Markdown 與無 DOM 失效關閉。`npm run lint`、`npm test`（174 通過）、`npm run build` 通過。
- 後續：Markdown 圖片仍會載入外部 URL，可能被提示注入用來外洩資料，未在本票處理。
- Python：ruff、check-integration 通過；pytest 798 通過、2 失敗（`test_real_pdf_pages_are_validated_rendered_and_released`、`test_greeting_only_profile_apply_keeps_playing_media_and_avoids_rebinding`），與本票無關（未改動 Python）。
