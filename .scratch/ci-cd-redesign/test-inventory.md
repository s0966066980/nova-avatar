<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 歷史測試盤點

本表是清理前的 1529 案例盤點。現版已移除退場行為並建立新的主要基準，
請以 [目前版本測試指南](../../docs/current-version-testing.md) 與最新完整執行結果為準。

盤點日期：2026-11-17。這份文件說明測試範圍，不宣告新的產品驗收通過。
來源是目前測試程式、現有分類、收集結果，以及上一輪保存的原始日誌。

## 先讀懂「通過」

一個案例通過，表示它設定的條件下，程式輸出符合該案例的斷言。
例如用假的模型回答驗證取消輪次，不等於真實模型、GPU、網路與喇叭都驗收通過。
案例數量也不是程式碼行／分支覆蓋率，不能算成「系統已驗證百分比」。

## Python：85 個檔案，1529 個收集案例

現有分類在 [tests/conftest.py](../../tests/conftest.py)，說明在
[tests/README.md](../../tests/README.md)。七個領域互斥，可相加；
`live`、`slow` 是重疊的額外屬性，不能再加進總數。

| 領域 | 收集案例 | 歷史基線通過／跳過 | 保護的行為 | 不能據此宣稱 |
| --- | ---: | ---: | --- | --- |
| `governance`：來源與契約 | 19 | 19／0 | 品牌、聲明、metadata、lock、整合稽核與 lint 規則 | 所有模型、聲音、資料與服務都已獲商業授權 |
| `runtime`：伺服器運作 | 242 | 242／0 | 健康狀態、設定保存、數位人設定與匯入、每條路由權限、靜態檔、啟停與依賴 | 真實場域可長時間穩定運作 |
| `speech`：語音 | 279 | 279／0 | VAD、STT/TTS 接合、音訊解碼、Edge 連線恢復、音訊庫與聲音預覽 | 真實中文辨識準確、場域沒有迴音、選定 TTS 必定可連線出聲 |
| `llm`：回答模型 | 117 | 116／1 | 端點與金鑰邊界、設定檔、路由、回覆規則、文字清理、llama.cpp 程序管理 | 真模型回答品質與正確性已驗收 |
| `conversation`：對話流程 | 740 | 738／2 | 輪次、串流、插話取消、已播回覆提交、媒體隔離、WebRTC 生命週期、角色交接、看板、附件、招呼、天氣與搜尋 | 實際瀏覽器至 GPU 的完整影音流程已驗收 |
| `avatar`：人物與畫面 | 99 | 99／0 | 安全載入、角色影格、嘴型銜接、背景合成、MuseTalk 暖機／加速接合 | 真實人物素材嘴型品質或 GPU 推理效能達標 |
| `ragflow`：知識檢索 | 33 | 33／0 | 檢索範圍、client、連線池、錯誤取消、部署限制與 embedding 接合 | 真實 RAGFlow 文件解析與檢索品質達標 |
| **合計** | **1529** | **1526／3** | 現有測試保護的已知行為 | 完整產品驗收 |

### 有些是真運算，有些是模擬

- Whisper 測試會解碼音訊並檢查參數，但辨識模型是 mock；見
  [test_whisper_asr.py](../../tests/test_whisper_asr.py)。
- Silero VAD 有使用套件內真實 CPU 模型處理合成音訊／靜音的測試；仍未測現場
  麥克風與喇叭迴音；見 [test_vad.py](../../tests/test_vad.py)。
- MuseTalk 加速接合用假的 UNet/VAE 與 CPU tensors；影像合成則有真正處理合成
  pixels。見 [test_musetalk_acceleration.py](../../tests/test_musetalk_acceleration.py)、
  [test_scene_background.py](../../tests/test_scene_background.py)。
- RAGFlow client 有對假的 aiohttp 服務發送真實 loopback HTTP；沒有因此啟動
  真實 RAGFlow。見 [test_ragflow_integration.py](../../tests/test_ragflow_integration.py)。
- 對話測試透過假模型、假 avatar、假時鐘驗證協定與順序；例如插話後只提交已播
  內容。見 [test_playback_commit.py](../../tests/test_playback_commit.py)。
- 路由安全測試有實際註冊應用並驗證請求權限；llama.cpp 部分案例會呼叫已安裝
  程式的 `--help`。因此離線測試也可能受本機安裝狀態影響。

### 3 個跳過案例

| 案例 | 跳過理由 | 實際缺少的證據 |
| --- | --- | --- |
| `tests/test_live_llm_board_contract.py::LiveLLMBoardContractTests::test_explicit_board_request_emits_renderable_items` | 沒有設定 `NOVA_AVATAR_LIVE_LLM_CONTRACT=1` | 真模型面對明確看板要求時能產生可呈現項目 |
| `tests/test_live_llm_board_contract.py::LiveLLMBoardContractTests::test_history_analysis_uses_a_board_without_an_explicit_list_request` | 同上 | 真模型能依既定規則自行選用看板 |
| `tests/test_llamacpp.py::GpuLayerPlanningTests::test_reads_qwen_block_count` | 沒有安裝 `Qwen3.8-27B-Q4_K_M.gguf` | 讀取該實際模型檔層數；不是模型推理測試 |

本次盤點只額外選取這 3 個案例，以 `-rs` 確認目前跳過理由，得到 3 skipped。
這是局部診斷，不是重新跑過 1529 個案例，也不是接受這些 skip 的政策決定。
第三個案例沒有 `live` 標記，因此 `-m "not live"` 仍可能跳過它。

### 如何逐組執行（後續階段使用）

前提是先完成並記錄指定驗證環境。下列以 `speech` 為例，工作目錄是 repository root，
並設定 `UV_PROJECT_ENVIRONMENT` 指向隔離環境；其他群組替換 marker 即可。

```bash
# 僅收集：看這一組會包含哪些案例，不執行案例。
uv run --no-sync pytest --collect-only -q -m speech

# 實際執行：保留逐案狀態、跳過原因、耗時與 JUnit。
# 先建立本次獨立紀錄目錄；report-directory 是待替換的路徑。
uv run --no-sync pytest -v -ra --durations=0 -m speech --junitxml=report-directory/speech.xml
```

這些命令是後續操作說明，本階段未執行整組。`not slow` 不保證短時間完成：
目前 `slow` 只手動列出 5 個案例，尚不是依全套耗時量測得出的分類。

完整檔案、數量、node ID： [Python JSON 清單](inventory/python-tests.json)、
[收集輸出](inventory/python-collection.txt)。

## 前端：46 個檔案，歷史基線 261 通過

以下五組是本次提出的說明與紀錄分組，尚未新增 npm scripts。
它們由原始日誌的 261 個測試名稱，逐一對照目前檔案中的 `test()` 定義而得。
名稱對得上不等於當時執行已有完整的 commit 追溯。

| 建議紀錄分組 | 案例 | 保護的行為 |
| --- | ---: | --- |
| 登入、安全與交付契約 | 29 | 登入／401 回登入、Markdown 清理、入口角色、CDN 限制、儲存鍵遷移、授權標示、健康顯示 |
| 對話狀態與輸入 | 48 | 插話、草稿、附件重試、舊請求隔離、控制台已播回覆提交、看板事件 |
| 舞台連線、收音與呈現 | 64 | 麥克風允許／拒絕、kiosk 重連、連線逾時、角色轉場收音、字幕、看板位置與音畫軌綁定 |
| 管理設定 | 105 | Prompt、模型端點、設定檔、角色組合衝突、知識範圍、搜尋來源、聲音、招呼、背景與語音測試面板 |
| 主題、排版與可及性 | 15 | 主題保存、對比、焦點、減少動態與兩種畫面尺寸的排版 |
| **合計** | **261** | 不等同於 261 個真實瀏覽器全系統案例 |

### 四種不同的驗證層級

1. **原始碼契約**：以字串或正規表達式確認接線存在。例如
   [voice-test-panel.test.js](../../web/tests/voice-test-panel.test.js) 中名稱提到
   「真實 API」的案例，實際只查程式字串，沒有發出真實請求。
2. **函式／狀態／元件**：執行程式邏輯、Vue 記憶體 renderer 或 jsdom；HTTP 等
   依賴由測試模擬。Markdown 則有使用真正 DOMPurify 清理 jsdom 內容。
3. **舞台模擬環境**：執行 stage script，但 DOM、WebRTC、麥克風與時間由 fake 提供。
4. **真 Chrome 畫面檢查**：`console-visual.test.js` 4 項與 `settings-layout.test.js`
   1 項，共 5 項。後端仍由 fixtures 模擬；它們檢查排版／對比等量化條件，
   不是以截圖基線作像素比對，也沒有驗證實際聲音與 GPU。

依據見 [browserHarness.js](../../web/tests/helpers/browserHarness.js)、
[stageHarness.js](../../web/tests/helpers/stageHarness.js)、
[componentHarness.js](../../web/tests/helpers/componentHarness.js)。

### 如何逐步執行（後續階段使用）

工作目錄 `web/`，先確認 Node.js 22 與依賴環境。

```bash
# 先選一個已解說的功能檔執行。
node --test tests/admin-session.test.js

# 要求真 Chrome：缺瀏覽器必須失敗，不能靜默跳過。
CI=1 node --test tests/console-visual.test.js tests/settings-layout.test.js

# 分組執行方案確認後，仍須核對完整集合，防止漏跑。
CI=1 npm test
```

`playwright-core` 不附帶瀏覽器；需有 Google Chrome 或設定 `CHROME_PATH`。
一般本機缺瀏覽器會 skip；`CI` 為非空值則失敗。既有 261 通過／0 skip 的
原始日誌包含前述 5 項；後續每次仍須記錄實際瀏覽器版本與結果。

ESLint 只保證已啟用的規則通過；Vite build 只證明兩個正式入口可產生 `web/dist`。
兩者均不啟動真實 Python 後端、STT／LLM／TTS 或 GPU。

完整逐檔數量、測試名稱與對照來源行號： [前端 JSON 清單](inventory/frontend-tests.json)。
逐檔速查表見 [附表](inventory/by-file.md)。
