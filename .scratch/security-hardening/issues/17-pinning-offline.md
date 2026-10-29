<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 固定版本與離線資源
Status: resolved

依[規格](../spec.md)。

- `scripts/setup-env.sh:74` `curl -LsSf https://astral.sh/uv/install.sh | sh` 未釘版本：改為指定版本並驗證 checksum（或改用固定版本的官方 release 檔）。`:216-222` 在 lock 之外安裝的套件釘版本。
- `scripts/download_musetalk_weights.sh:17-25,38-39`：`snapshot_download` 加 `revision`（commit hash），檔案以 sha256 驗證，不符即失敗。
- `web/index.html:11-13` 從 jsDelivr 載入 Bootstrap 與 bootstrap-icons、無 integrity；兩者已在 `web/package.json`，改由 npm 套件引入，場域斷網時圖示正常。
- `scripts/create_ssl_certs.sh`：支援 mkcert 建本地 CA（偵測到 mkcert 時優先），README 說明管理者裝置如何信任一次；保留自簽後備。
- `scripts/ragflow.sh:240` 的 `bge-m3` 與 RAGFlow 映像（`scripts/ragflow_prepare.py:66`）改釘 digest，或在 Comments 說明無法釘的理由。

完成：`npm run build` 產物不再引用 CDN；腳本測試與完整 CI 通過。

## Comments

### 2026-10-29 實作結果

- uv：`setup-env.sh` 改下載 `uv 0.11.21`（與 CI 同版）官方 release 壓縮檔，以內建 x86_64／aarch64 SHA-256 驗證後才安裝到 `~/.local/bin`，不再 `curl | sh`；不符即中止。主流程改為僅直接執行時啟動，測試可 source 單獨呼叫 `install_uv`。lock 之外的套件改釘 `ninja==1.13.0`、`mmengine==0.10.7`（其餘原本已釘）。
- MuseTalk 權重：清單移至 `scripts/musetalk_weights.py`，五個 Hub repo 皆釘 commit（`snapshot_download(revision=...)`），十個檔案逐一 SHA-256 驗證（`--check` 亦同），缺檔或不符即非零結束。commit 與雜湊以 Hub API 唯讀查詢取得，小型 JSON 於 scratchpad 下載後計算。
- 前端：`index.html` 移除 jsDelivr 的 Bootstrap／bootstrap-icons 與 Google Fonts 連結，改由 `main.js` 匯入 npm 套件；`npm run build` 產物無 CDN 引用，圖示字型打包於 `dist/assets`。Google Fonts 未改為自帶，改用 CSS 既有的本機字型後備（Noto Sans CJK TC 等）；若要保留 Plus Jakarta Sans／JetBrains Mono 外觀需另加 OFL 字型套件與聲明。
- SSL：`create_ssl_certs.sh` 偵測到 mkcert 時優先以本機 CA 簽發，涵蓋 localhost、主機名稱、區網 IP 與額外參數；`NOVA_SSL_SELF_SIGNED=1` 或無 mkcert 時沿用自簽（SAN 同步擴充）。README 新增「管理者裝置信任本機 CA」步驟，`docs/installation.md` 同步。
- RAGFlow：映像釘為 `infiniflow/ragflow:v0.27.2@sha256:e6b3f1a1…27ab`（registry 查詢與本機映像 RepoDigest 一致），`ragflow_validate.py` 拒絕僅有 tag 者；既有受管 `.env` 重跑 `prepare` 只改寫映像欄位，不動密碼。
- bge-m3：Ollama 不支援以 digest 拉取，改為拉取後（或沿用既有時）以 `ollama show --modelfile` 的權重 blob `sha256-daec91ff…062c` 驗證，不符即失敗（對應 registry manifest `sha256:79076464…6bab`，與本機 ID 一致）。
- npm audit（協調者追加範圍）：`npm audit fix`（未用 `--force`）前 9 項（8 high、1 moderate），後 2 項（vite 1 high、esbuild 1 moderate）；剩餘兩項需升級 vite 8（破壞性變更），未處理。Vue 升至 3.5.44 後 v-model 改用 `el.getRootNode()`，已在 `tests/helpers/componentHarness.js` 補上假節點方法與 `Document`／`ShadowRoot` stub。
- 未處理：RAGFlow 上游原始碼仍以 tag `v0.27.2` clone（對應 commit `a024bea0cd93f39e6652a42bf84dd20c55bc560b`，可另行加驗）；RAGFlow compose 的其他映像（mysql、es、minio、redis）未釘 digest。
- 測試：新增 `tests/test_pinned_resources.py`（17 項）與 `web/tests/offline-assets.test.js`（3 項）。pytest 815 passed、3 skipped、2 failed（`test_real_pdf_pages_are_validated_rendered_and_released` 需本機 OCR、`test_greeting_only_profile_apply_keeps_playing_media_and_avoids_rebinding` 需 `models/musetalk`，皆為 worktree 缺少執行期檔案，與本票無關）；ruff、check-integration、npm lint／test（172）／build 通過。
- 合併 security-hardening 後（lock 自動合併，`npm install --package-lock-only` 無差異）：pytest 850 passed、3 skipped、同上 2 項環境性失敗；npm test 202 通過；lint、build（無 CDN 引用）、ruff、check-integration 通過；npm audit 仍為 2 項（vite／esbuild）。
