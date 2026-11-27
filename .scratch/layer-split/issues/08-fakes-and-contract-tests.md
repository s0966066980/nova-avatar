<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 各層的 fake 引擎與契約測試
Status: ready-for-agent
Blocked by: 07

依規格決定 15。

- 每一層都提供一個 `fake` 引擎：
  - STT 回傳固定文字；
  - LLM 回傳固定的口語文字增量與看板事件；
  - TTS 回傳指定長度的靜音 PCM；
  - 數位人渲染輸出固定畫面。
  - 透過設定即可選用，但不出現在控制台的引擎清單中。
- 每一層各有一組契約測試，驗證 adapter 的輸入輸出符合 `contracts/` 的模型與事件順序，包括取消時的行為。
- 核心的輪次、插話、交接測試改用 fake 引擎，不再各自手寫假物件。
- 需要 GPU 或真實模型的測試，統一用 pytest marker（例如 `gpu`）標記；GitHub CI 預設排除它們。
- 驗收：
  - 在沒有 GPU、沒有模型權重的機器上，`uv run --no-sync pytest` 全部通過；
  - 測試數量與覆蓋率不低於修改前，若有減少要說明原因。

## Comments

### 2026-11-27 STT 層

分支 `ls/08-stt`，只涵蓋 STT 層；LLM、TTS、數位人渲染由各自分支處理，工單仍維持開啟。

- `fake` 引擎：`src/asr/engines/fake.py` 的 `FakeASR`，註冊在 `src/asr/factory.py`。不需要 GPU 或權重，也不解碼音訊，對每段語音回傳固定文字。
- 選用方式：設定檔 `asr.type: fake`，並以 `asr.model_size` 當作要回傳的文字（例如 `model_size: 歡迎光臨`；空字串代表無聲）。為了不改契約，沒有新增欄位。語言依請求回報，`auto` 一律回 `zh`；信心分數為 1.0。
- 不出現在控制台：`STT_ENGINE_META` 沒有它，所以引擎清單看不到，也無法從控制台套用（會回「不支援的 STT 引擎」）。
- 契約測試（`tests/test_stt_contract.py`）新增：以真正的 adapter 與 factory 搭配 fake 引擎，檢查輸出符合 `nova_contracts.stt` 的模型，涵蓋語言、`prepare`／`health`、切換引擎、切換失敗（載入失敗與未知引擎）保留目前引擎，以及切換載入期間的請求仍由目前的辨識器回答；另有設定檔選用與控制台不列出的測試。STT 契約測試由 12 增為 22；全部測試 2342 passed、2 skipped。
- 順手修正：`InProcessSttService.apply_engine` 對未知引擎原本丟出 `ValueError`，現在與載入失敗一致，轉成 `ServiceError` 並保留目前的辨識器（契約規定的行為）。
- 取消：STT 在同一行程內沒有可取消的長時間呼叫（loopback 時由核心關閉連線取消），所以以「切換中放棄／失敗不影響目前辨識器」驗證；沒有為 fake 加入假的取消行為。
- 核心的輪次、插話、交接測試改用 fake 引擎，屬後續整合工作，本次未動。
