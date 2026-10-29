<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 固定版本與離線資源
Status: ready-for-agent

依[規格](../spec.md)。

- `scripts/setup-env.sh:74` `curl -LsSf https://astral.sh/uv/install.sh | sh` 未釘版本：改為指定版本並驗證 checksum（或改用固定版本的官方 release 檔）。`:216-222` 在 lock 之外安裝的套件釘版本。
- `scripts/download_musetalk_weights.sh:17-25,38-39`：`snapshot_download` 加 `revision`（commit hash），檔案以 sha256 驗證，不符即失敗。
- `web/index.html:11-13` 從 jsDelivr 載入 Bootstrap 與 bootstrap-icons、無 integrity；兩者已在 `web/package.json`，改由 npm 套件引入，場域斷網時圖示正常。
- `scripts/create_ssl_certs.sh`：支援 mkcert 建本地 CA（偵測到 mkcert 時優先），README 說明管理者裝置如何信任一次；保留自簽後備。
- `scripts/ragflow.sh:240` 的 `bge-m3` 與 RAGFlow 映像（`scripts/ragflow_prepare.py:66`）改釘 digest，或在 Comments 說明無法釘的理由。

完成：`npm run build` 產物不再引用 CDN；腳本測試與完整 CI 通過。

## Comments
