<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 第 3 階段：來源聲明、離線整合與治理測試

執行狀態：passed
理解確認：pending
日期：2026-11-17；命令時間為 UTC

## 目的

確認既有品牌、來源聲明與限制標示沒有退步，離線檢查入口與依賴約束符合
既有契約，並確認 Ruff 規則確實能拒絕代表性的壞程式範例。

這不是商業授權審查結論，也沒有呼叫真實 LLM／TTS 或執行模型推理。

## 來源與環境

- 來源 commit：`b1afdce7429eb166d3d36f6e233a07a14fbc2d52`，沿用乾淨 git archive 快照。
- Python 3.11.16、PyTorch 2.5.0+cu124、CUDA 12.4；開始前確認 CUDA 可用。
- 使用第 1 階段 lock frozen 建立的隔離環境，命令均加 `--no-sync`。
- 快照不含忽略的 runtime overrides、場域資料、模型與秘密設定。本次讀取的是
  已追蹤預設 config，不是實際場域的有效設定驗收。
- 原專案及快照的 lock、設定、來源聲明與受驗測試檔 hash 在執行前後一致。
- 來源識別、時間、選取條件與結果：[manifest.json](manifest.json)。
- 每項精確命令、cwd、環境覆寫與退出碼：[commands.json](commands.json)。

## 三個執行步驟

| 步驟 | 命令 | 實際結果 |
| --- | --- | --- |
| 離線稽核 | `uv run --no-sync python scripts/check-integration.py` | 退出碼 0 |
| 先列案例 | `uv run --no-sync pytest --collect-only -q -m governance` | 選取 19 個案例 |
| 執行案例 | `uv run --no-sync pytest -v -ra --durations=0 -m governance --junitxml=紀錄目錄/governance.xml` | 退出碼 0；19 passed、0 failed、0 error、0 skipped |

共收集 1529 個案例，其中 1510 個不屬於 governance，本輪 deselected。
**deselected 是本輪未選取，不是 skipped，也不能當成通過。**

本次 pytest 另外顯示 26 subtests passed，屬於上述案例內的子檢查，不能再把它們
加成 45 個獨立案例。功能群組總數仍是 19。

## 19 個案例保護什麼

| 測試檔 | 案例數 | 具體保護內容 |
| --- | ---: | --- |
| test_branding_compliance.py | 6 | Nova Avatar metadata 與使用者介面名稱；保留來源聲明；Wav2Lip 的 Research / Non-commercial 標示；受限制語音引擎在目錄、介面與 notices 的標示；商業審查設定檔與稽核文件存在 |
| test_dependency_lock.py | 5 | lock 存在與特定 ignore 條目檢查；CI 先檢查 lock 再安裝；正式依賴 audit 保持 advisory；lock 與 pyproject 相容；暫存專案改依賴卻不更新 lock 時檢查應失敗 |
| test_integration_check.py | 4 | 離線稽核為預設；法律／稽核文件列在必要契約中；可選引擎列在模組檢查表；商業審查設定檔選用支援的 avatar 路徑 |
| test_ruff_security.py | 4 | 代表性壞範例會被指定規則拒絕；requests 無 timeout 失敗／有 timeout 通過；規則適用 tests 與 scripts；額外啟用 S101 時測試用 assert 的指定例外行為 |
| 合計 | 19 | 來源與檢查契約的回歸保護 |

逐案 ID、狀態與耗時：[case-results.md](case-results.md)、[cases.json](cases.json)。
機器報告：[governance.xml](governance.xml)。

## 離線稽核實際做了什麼

本次腳本成功載入已追蹤的預設設定，檢查品牌、來源與 release 文件契約，檢查核心
與選定 avatar 的模組是否可找到，並檢查商業審查設定檔的 avatar 選擇。
完整輸出：[offline-integration.log](offline-integration.log)。

腳本雖輸出「依賴可匯入」，實作使用 `importlib.util.find_spec` 檢查可發現性，
並沒有完整 import／初始化這些模型。因此不能據此宣稱所有原生依賴都可載入、
CUDA 模型可推理或模型權重已備妥。

此外，4 個 integration-check 測試主要驗證檢查器本身的契約，沒有代替完整腳本；
所以本次兩者都分別執行並記錄。

## 與新版 CUDA-only 設計的已知差異

`test_python_ci_checks_the_lock_before_installing` 還要求既有 workflow 保留
`--torch-backend cpu`。本次測試的是尚未修改的舊 workflow，因此該案例通過，
**不代表新版 CUDA-only CI 已完成**。落實 CUDA workflow 時，必須同步更新這項
契約，驗證新的 frozen 安裝與 GPU 執行要求，不能為維持綠燈而保留 CPU 選項。

Ruff assert 案例額外使用 `--extend-select S101`，不代表一般 Ruff 命令已全域
啟用 S101。其餘負向 Ruff 範例只經 stdin 送入 lint，不執行危險程式；lock 負向
測試只修改 TemporaryDirectory 複本。

## 本階段沒有證明的事

- 聲明或關鍵字存在，不代表模型、聲音、資料或外部服務都已取得商業授權。
- lock 測試通過，不代表安裝器必定使用 lock。第 1 階段 CUDA 環境另外透過
  frozen 安裝建立版本證據，兩種責任分開記錄。
- `test_lock_is_present_and_not_ignored_by_git` 名稱較廣，實際只檢查檔案存在與
  `.gitignore` 沒有特定 `uv.lock` 條目；不是確認檔案已被 Git 追蹤的完整證明。
- Ruff 規則測試驗證選定壞範例可被擋下；不代表所有安全問題都可被靜態工具發現。
- 沒有執行其他功能群組、前端測試、建置或 `--smoke` 真實服務測試。
- config loader 具有 legacy 資料遷移行為，不能泛稱此工具在任意場域設定下都
  完全唯讀；本次使用不含現場覆寫／資產的預設快照，避免套用場域設定。

## 通過條件與下一步

離線腳本退出碼 0，且選取的 19 案例皆通過、沒有失敗或跳過。本次符合。
沒有修改產品程式、法律聲明、lock 或 workflow，也沒有以修正後結果覆蓋失敗。

原始測試日誌：[governance-tests.log](governance-tests.log)。
證據 hash：[evidence-sha256.json](evidence-sha256.json)。

等待使用者確認理解後，進入第 4 階段後端功能驗證，建議先從 runtime 群組
（伺服器狀態、設定與權限等 242 個盤點案例）開始；其餘功能群組依序分開記錄。
