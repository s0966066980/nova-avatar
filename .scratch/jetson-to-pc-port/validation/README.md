<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# PC 移植驗證

日期：2026-10-28。PC 基線 `412fedf`，來源 Jetson `1b61a21`；工作分支
`feat/jetson-pc-port`。本次保留 MuseTalk、角色交接、天氣、單一輸入來源及
兩端同步展示，沒有引入預錄模式或 ARM64 建置。

## 自動化驗證

- Python：751 passed、3 skipped、59 subtests passed，74.82 秒。
- Web：144 passed。
- Ruff、整合／品牌授權檢查、前端 lint 與 production build 通過。
- Production build 同時產出控制台與 `stage.html`，保留既有 bundle 大小提醒。
- PC 專用測試包含 15／60 秒清除邊界、角色記憶與 Context 分開、附件與草稿
  阻擋招呼、無麥克風的文字舞台、跨角色英文聲音、手動清除隔離、不相容
  附件交接拒絕、設定遷移備份與 RAGFlow 同步的新增／重複執行保證。

完整測試由本次工作執行，並非引用 Jetson 的測試數字。

## Whisper 實測

RTX 4090，CUDA FP16。使用公開的四句中英文測試文字，由現有 Edge TTS
產生合成語音，每個模型暖測兩輪，共八筆；不含 VAD、LLM、嘴型或喇叭延遲。

| 模型 | 載入及推論預熱 | 暖測辨識中位數 | 程序峰值 RSS |
| --- | ---: | ---: | ---: |
| small | 1.254 秒 | 0.167 秒 | 1,025 MiB |
| large-v3-turbo | 1.457 秒 | 0.228 秒 | 2,435 MiB |

兩者均辨識出本批問題的內容；turbo 中文輸出有簡體字，未將字形差異視為內容誤辨。
採 small 作本次 PC 雙語預設，保留 turbo 與 FunASR 中文選項。
RSS 是同一測試程序依序載入模型的累計高水位，不是模型獨立增量；這批合成
語音不能當作真人口音、混說、現場噪音或與即時嘴型共同負載的品質驗收。

[逐字與時間](asr-benchmark.json)、[來源與轉換雜湊](model-manifest.json)、
[官方 Whisper MIT 許可](licenses/openai-whisper-LICENSE)。
可用 `uv run python .scratch/jetson-to-pc-port/validation/benchmark_asr.py` 重跑。
small／turbo 從固定 OpenAI 權重轉為 CTranslate2 FP16；轉換時以暫時的參數
相容處理銜接既有 Transformers，未升級產品依賴或修改第三方套件原始碼。

## 本機附件視覺與 OCR

Gemma 與投影權重使用來源已驗證的固定 Google revision，下載至本機模型
目錄；沒有替換原 Qwen 設定。以獨立的 `127.0.0.1:8092` llama-server 測試，
實際 `/props` 回報視覺可用與 8,192 token 容量，測完關閉本次建立的程序。

- 英文圖片與掃描 PDF 都正確回答單號 `NOVA42` 及金額 `1500 TWD`。
- 繁中圖片的本機 Tesseract 5.5.0 正確擷取單號與金額，模型中文回答正確。
- 同一模型對話可追問先前單號；另驗證有文字層的 PDF 與英文回答。

[圖片／掃描頁結果](vision-check.json)、[繁中 OCR／追問／文字 PDF](vision-additional-check.json)。
這些是代表性文件測試，不保證任意文件、圖表或多頁加總正確。
PDFium 5.14.0 與本次 x86 wheel 的 notices 已保留；OCR 優先使用系統工具，
本機另準備 `.local/ocr-packages/root/usr` 的工具及繁中／英文語言包作 fallback。

## 設定與部署

執行 `scripts/migrate-pc-conversations.py` 前已保存原 runtime overrides 至
忽略版控的 `.local/jetson-to-pc-port/backups/`，備份與新設定皆為 0600。
只更新指定的 15／60／30 秒與 Whisper small／auto，保留既有模型、角色、
文案及啟用開關。重跑符合新設定的檔案不會重寫或重複備份。

RAGFlow 統一模型服務保持選用，沒有啟用共用標記、修改使用者工作區或
切換現有嵌入服務。本次以自動化測試驗證同步新增及重複執行；沒有在使用者
正式知識庫執行服務切換，也不把測試視為正式資料遷移已完成。

## 未完成的實機驗收範圍

本次瀏覽器工具未提供任何可用瀏覽器或電腦表面，因此沒有實際瀏覽器截圖、
麥克風／喇叭或跨角色即時嘴型的整場現場驗收。介面操作、輸入來源、媒體
取消、角色交接與計時由 Vue／舞台腳本及後端測試驗證；本機 ASR 與附件
視覺則另有上述實際模型結果。真人現場噪音與同負載延遲仍須部署後量測。
