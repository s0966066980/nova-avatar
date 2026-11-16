<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 跨裝置 HTTPS 多 SAN 憑證與 Root CA 信任指引

遠端裝置（桌機／筆電、iOS Safari、Android Chrome）必須信任伺服器憑證且連線主機名稱／IP 符合憑證 SAN，瀏覽器才會正常開放 `navigator.mediaDevices.getUserMedia()` 麥克風存取。

## 1. 產生多 SAN 憑證與 Root CA

在 Nova Avatar 專案根目錄執行：

```bash
bash scripts/create_ssl_certs.sh
```

腳本行為說明：
- 若系統已安裝 `mkcert`，優先使用 `mkcert` 簽發並匯出 Root CA；若未安裝 `mkcert`，自動改用 `openssl` 建立本機 Root CA 並簽發多 SAN 伺服器憑證。
- 預設自動納入 `localhost`、`127.0.0.1`、`::1`、本機區網 IPv4、`<hostname>.local`（mDNS），以及（若已登入 Tailscale）Tailscale IP 與 MagicDNS 名稱。
- 可透過參數或環境變數追加主機名稱／IP，或指定輸出路徑（與 `config/*.yaml` 的 `app.ssl_cert`、`app.ssl_key` 對齊）：

```bash
NOVA_SSL_HOSTS="192.168.1.50,orin.local,orin.tailnet.ts.net" \
  bash scripts/create_ssl_certs.sh --cert ssl_certs/localhost.crt --key ssl_certs/localhost.key
```

產出檔案預設位於 `ssl_certs/`（已由 `.gitignore` 排除，不進版控）：
- `ssl_certs/localhost.crt`、`ssl_certs/localhost.key`：伺服器憑證與私鑰。
- `ssl_certs/rootCA.pem`、`ssl_certs/rootCA.crt`：給其他裝置匯入的 **Root CA 公鑰**（兩者內容相同，依裝置副檔名需求擇一即可）。
- `ssl_certs/rootCA-key.pem`（OpenSSL 模式）：本機 CA 私鑰。**絕對不可傳給任何遠端裝置**；保留此檔可在後續新增 IP 時沿用同一張 Root CA，免去裝置端重新匯入。

## 2. 各裝置匯入 Root CA 步驟

> 僅傳送 `rootCA.pem` 或 `rootCA.crt` 到目標裝置（AirDrop、區域網路暫時傳輸、USB 或通訊軟體檔案傳輸皆可），切勿外洩 `*.key` 或 `rootCA-key.pem`。

### Windows

1. 將 `rootCA.crt` 複製到 Windows 電腦。
2. 雙擊 `rootCA.crt` →「**安裝憑證…**」→ 選「**本機電腦**」（或「目前使用者」）→「**將所有憑證放入以下的存放區**」→ 瀏覽選擇「**受信任的根憑證授權單位**」→ 完成匯入。
   - 或以系統管理員權限執行：
     ```powershell
     certutil -addstore -f "ROOT" rootCA.crt
     ```
3. 重新啟動 Chrome / Edge 後，連線 `https://<orin-ip>:8010/stage.html`。

### macOS

1. 將 `rootCA.crt`（或 `rootCA.pem`）傳到 Mac。
2. 雙擊檔案以「鑰匙圈存取（Keychain Access）」開啟，將憑證加入「**系統**」或「**登入**」鑰匙圈。
3. 在鑰匙圈中雙擊剛匯入的 `Nova Avatar Local CA`（或 `mkcert` CA），展開「**信任**」，將「**使用此憑證時**」設為「**永遠信任**」。
   - 或使用終端機指令：
     ```bash
     sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain rootCA.crt
     ```
4. 重新開啟 Safari / Chrome。

### iOS / iPadOS（Safari 必須完成兩步驟）

1. 將 `rootCA.crt`（或 `rootCA.pem`）透過 AirDrop 或檔案傳送到 iPhone / iPad，選擇「允許」下載描述檔。
2. **步驟一（安裝描述檔）**：打開「**設定 → 一般 → VPN 與裝置管理**」（或舊版「設定 → 描述檔」），點選已下載的 CA 描述檔並完成「**安裝**」。
3. **步驟二（啟用憑證完全信任）**：打開「**設定 → 一般 → 關於本機 → 憑證信任設定**」，開啟該 Root CA 的「**針對根憑證啟用完全信任**」開關。
4. 重新開啟 Safari 連線 `https://<orin-ip>:8010/stage.html`，確認網址列無安全警告且麥克風可正常授權。

### Android

1. 將 `rootCA.crt` 傳送到 Android 手機的「下載」資料夾。
2. 打開「**設定 → 安全性與隱私權**（或「安全性和位置／加密與憑證」）→ **更多安全設定 → 從儲存空間安裝 → CA 憑證**」，若出現風險提示選「仍要安裝」，選取 `rootCA.crt` 完成匯入。
   - 部分廠牌手機路徑為「設定 → 搜尋『CA 憑證』／『安裝憑證』」。
3. 重新開啟 Chrome 連線 `https://<orin-ip>:8010/stage.html`。
