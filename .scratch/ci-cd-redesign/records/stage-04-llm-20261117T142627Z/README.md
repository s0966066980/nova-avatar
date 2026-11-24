<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 第 4 階段之三：llm 回答模型接合

執行狀態：執行完成，待確認一個 skip 的政策；不記為全數通過
理解確認：pending
日期：2026-11-17；命令時間為 UTC

## 目的與來源

驗證模型設定、Prompt 與回覆協定、端點安全、程序啟動政策及評測工具。
本組不是 117 次真實 GPU 模型推理。

來源 commit `b1afdce7429eb166d3d36f6e233a07a14fbc2d52`，沿用有 Git metadata 的
乾淨來源快照與 frozen 安裝的 CUDA 環境。Python 3.11.16、PyTorch 2.5.0+cu124、
CUDA 12.4；開始前確認 CUDA 可用，沒有重新安裝套件。

來源、時間、輸入 hash 與結果：[manifest.json](manifest.json)。
精確命令、cwd、環境覆寫與退出碼：[commands.json](commands.json)。

## 執行結果怎麼讀

先以 `uv run --no-sync pytest --collect-only -q -m llm` 列出案例，再執行
`uv run --no-sync pytest -v -ra --durations=0 -m llm --junitxml=紀錄目錄/llm.xml`。

實際為 **116 passed、1 skipped、0 failed、0 error**；1412 deselected、16 subtests passed，
pytest 耗時 6.99 秒。子檢查與未選取案例不能加進通過數。

pytest 本身退出碼是 0，因為其預設允許 skip；但本階段先前採「選取案例全執行且
無跳過」門檻，尚未符合。不能由退出碼 0 宣稱 117 全部通過。

紀錄工具第一版把任何非全數通過結果統稱 failed，已另存
[原始分類](manifest-initial-classification.json)，目前分類改為 awaiting_skip_policy。
這是結果分類的澄清，不是產品測試失敗；JUnit／日誌／實際數量未更動。

## 功能與檔案

| 測試檔 | 案例 | 保護內容 | 實際執行界線 |
| --- | ---: | --- | --- |
| test_assistant_profile.py | 4 | 身分 Prompt、歷史清理與設定 snapshot／保存 | 真 Prompt 與 tmp YAML，未問真模型是否遵循身分 |
| test_default_llm_endpoint.py | 6 | 預設 managed llama-server、明確 Ollama 選擇與舊設定相容 | 讀設定與文件，不執行文件中的 sudo/systemctl |
| test_editable_llm_rules.py | 6 | 回覆規則預設／驗證、revision 與過期寫入拒絕 | 真 validation／tmp 保存，不生成回答 |
| test_first_sentence_rule.py | 10 | 首句指令、中文／英文長度、自訂規則與看板摘要例外 | Prompt 與算法；不證明模型真的生成合格首句 |
| test_gemma_e2b.py | 7 | thinking／grammar／JSON schema 請求與路由結果解析 | 固定 client／completion，不載入 Gemma／LFM |
| test_llamacpp.py | 23 | CUDA library、GPU 層數、程序所有權、GPU 啟動拒絕與先後順序 | 多數 Popen／kill／VRAM 為替身；真 binary help 通過，真 Qwen 檔 metadata 檢查跳過 |
| test_llm_endpoints.py | 25 | 伺服器端點白名單、key 隔離、拒絕任意 URL 與安全遷移 | 真 tmp 設定與管理 HTTP；模型 client 記錄請求但不發外網 |
| test_llm_quality_eval.py | 20 | 計分、題集、SSE／parser 接合、路由與雙模型報告 | 假 loopback server 固定回答；不代表真模型品質或延遲已比較 |
| test_llm_router.py | 11 | SIMPLE／BOARD 呈現模式、強制模式與分類失敗處理 | 規則邏輯真執行，LLM classifier 為 mock；不是角色交接／endpoint 路由 |
| test_llm_text_normalizer.py | 5 | 繁體／臺灣用詞、英文與 code 保留、身分文字、口語／看板／歷史正規化 | 真文字處理與 pipeline，模型 stream 固定 |
| 合計 | 117 | 模型接合與安全規則 | 116 通過、1 跳過 |

## 唯一跳過的案例

`tests/test_llamacpp.py::GpuLayerPlanningTests::test_reads_qwen_block_count`

原因：`Qwen3.8-27B-Q4_K_M.gguf is not installed`。
它讀指定實體 GGUF 的 metadata，斷言層數為 65；不生成回答，也不執行 GPU 推理。
此跳過不是 CUDA 不可用，不能由它判定顯示卡或 PyTorch 失敗。
本次沒有為了消除 skip 下載該模型，也沒有刪除或改寫這項測試。

建議把這個「特定本機權重檔的檢查」列為選用，保留缺檔理由，並把實際部署模型
載入與 CUDA 推理列為發布前必測。提案尚未獲使用者確認；其他未知 skip 不自動接受。
精確提案：[proposed-skip-policy.json](proposed-skip-policy.json)。

## 真實 binary 與假模型的差別

`test_llama_server_loads_with_discovered_cuda_libs` 實際執行找到的 llama-server `-h`，
本次通過；它只證明執行檔可進入 help 路徑、沒有 CUDA 動態庫載入錯誤，不證明
權重能載入、GPU 完成推理或模型服務可回答。

FullGpuStartupTests 使用 fake process、偽造 VRAM／CUDA capability 與稀疏假 GGUF。
即使案例名稱提到 full GPU／console reachable，也沒有真的載入大模型或以 HTTP
驗證控制台可用；相關案例主要檢查呼叫參數、順序與狀態。

明確允許 partial offload 的既有契約，及無顯存時計算層數為 0 的函式測試，不代表
本版 CUDA-only CI 會自動以 CPU fallback 通過。

## 評測與副作用

quality eval 使用真 loopback HTTP／SSE，但 FakeLlamaServer 回固定內容，知識與
天氣來自 fixture，不呼叫真 RAG／CWA。CLI 接收假 server URL，不啟動真模型。

router 的平均 2 ms 檢查只量測規則分類，不是模型回答或感知首音延遲。
大部分檔案保存都在 tmp；Gemma helper 可能留下少量 mkdtemp YAML。
程序 kill／啟動與服務 health 探測大多已 patch，沒有停止或替換場域模型服務。

本次不證明模型回答品質、實際角色路由正確率、語音／首音延遲或完整訪客對話。

## 證據與下一步

逐項結果：[case-results.md](case-results.md)、[cases.json](cases.json)。
原始日誌：[llm-tests.log](llm-tests.log)、[收集清單](llm-collection.log)。
JUnit：[llm.xml](llm.xml)；完整性：[evidence-sha256.json](evidence-sha256.json)。

先確認此 skip 的分類與本階段理解，再進 avatar 群組（盤點 99 案例）。
這個待決項未確認前，不把 llm 加進已完成群組，也不進入後續驗收。
