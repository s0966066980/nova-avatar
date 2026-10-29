<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# LLM 全 GPU 啟動
Status: ready-for-agent

依[規格](../spec.md)。`src/llm/llamacpp.py:266` 依啟動當下剩餘顯存決定 `-ngl`；llama-server 在 MuseTalk 載入後才啟動，10/29 21:29 只得到 31 層（生成約 35 tok/s，全 GPU 時 107–124）。最新 `logs/llama-server.log` 首行為「no usable GPU found」，一併查明。

- 啟動順序改為 llama-server 先於數位人模型載入。
- 算出的層數小於模型全部層數時，啟動失敗並說明需要的顯存與目前占用者；設定可明確允許部分卸載（預設不允許）。
- 非全 GPU 執行時，`/health` 與控制台顯示警告。

完成：模擬顯存不足的測試；實機啟動日誌顯示 `-ngl 99`。

## Comments
