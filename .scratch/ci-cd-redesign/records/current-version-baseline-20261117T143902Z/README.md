<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 目前版本的本機主要測試基準：完整執行

結果：passed。此紀錄取代舊的 Qwen3.8 optional-skip 提案，沒有新增該項豁免。
來源為 HEAD 加未提交變更；不是已發布版本或已完成的 GitHub-hosted run。

基準定義：[JSON](../../../../tests/current-version-baseline.json)。
說明：[目前版本測試指南](../../../../docs/current-version-testing.md)。
入口：[check-current-version.py](../../../../scripts/check-current-version.py)。

## 本次結果

- Python：1515 passed、0 failed、0 skipped；另 3 項 live 檢查由主要回歸明確 deselect。
- 前端：261 passed、0 failed、0 skipped；CI=1，瀏覽器缺失不可靜默略過。
- lock／frozen 環境、真 CUDA tensor 運算、Ruff／Pyright／ESLint、離線整合、npm ci、
  正式依賴 audit、正式建置均通過。audit 仍維持 advisory 政策。
- Python 有 5 個 Silero 棄用警告，原樣保留；63 個 subtests 不加進案例總數。

| Python 領域 | 主要回歸通過 |
| --- | ---: |
| governance | 19 |
| runtime | 242 |
| speech | 279 |
| llm | 105 |
| avatar | 99 |
| ragflow | 33 |
| conversation | 738 |

## 為何數量改變

完整收集由 1529 改為 1518：刪除 11 個已退場的關鍵字／灰區路由案例。
Qwen3.8 檔案案例以自足 GGUF parser fixture 替換，LFM thinking 案例以現版 Qwen3.5
請求契約替換，這兩項保留通用或現版能力而不靠刪除檢查消除 skip。

1518 中的 3 項現行實機檢查為 llama-server help，以及兩個已配置模型的看板契約。
它們保留為 live 發行前置，不屬主要回歸；本輪沒有執行，不是 skipped 或 passed。
真實選定模型的 CUDA 推理、WebRTC 與場域視聽驗收也尚未執行。

## 證據

- [result.json](result.json)：每項 argv、cwd、時間、退出碼及基準範圍。
- [Python JUnit](python.xml)、[原始日誌](python-tests.log)、[領域與逐案結果](coverage-by-area.json)。
- [前端日誌](web-tests.log)、[建置](web-build.log)、[CUDA 實際運算](cuda.log)。
- [來源 HEAD](source-head.log)、[來源差異](source-diff.log)、[來源 hash](source-sha256.json)。
- [原始執行 hash](run-sha256.json)、[含本紀錄的完整 hash](sha256.json)。

執行後另完成說明文件及 live 測試 SPDX 檔頭；未再修改可執行測試邏輯。
來源 hash／diff 保留執行當下內容，不冒充這些後續純文件修改也已參與該輪。

另以系統 Node 24 執行 environment 階段作負向驗證，確認入口拒絕錯誤版本，沒有
繼續執行測試。失敗是預期的守門結果，不能混入本次成功數量。

GitHub workflow 仍待 GPU runner 設定與後續整合，本次只交付已確認範圍的本機基準。
