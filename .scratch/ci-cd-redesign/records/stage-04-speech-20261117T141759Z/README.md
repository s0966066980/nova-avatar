<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 第 4 階段之二：speech 語音功能

執行狀態：passed
理解確認：pending
日期：2026-11-17；命令時間為 UTC

## 目的與來源

驗證語音輸入切段、STT／TTS 接合、連線與取消規則、音訊庫及相關測試工具。
這是後端群組驗證的一部分，不是現場收音、辨識準確度與發聲品質的驗收。

來源 commit `b1afdce7429eb166d3d36f6e233a07a14fbc2d52`，沿用乾淨快照與
已初始化的隔離 Git metadata。Python 3.11.16、PyTorch 2.5.0+cu124、CUDA 12.4；
開始前確認 CUDA build 與 GPU 可用，沒有重新安裝套件。

來源、選取條件、時間、設定與測試檔 hash：[manifest.json](manifest.json)。
精確命令、cwd、環境覆寫、退出碼：[commands.json](commands.json)。

## 執行與結果

先 `uv run --no-sync pytest --collect-only -q -m speech`，再執行
`uv run --no-sync pytest -v -ra --durations=0 -m speech --junitxml=紀錄目錄/speech.xml`。
工作目錄為來源快照 root，使用已記錄的 UV_PROJECT_ENVIRONMENT。

結果：**279 passed、0 failed、0 error、0 skipped**；1250 deselected、8 subtests passed，
pytest 耗時 15.29 秒。1250 是本輪未選取，8 是案例內的子檢查，都不加進 279。

通過條件是選取的 279 案例全部通過、沒有失敗或跳過，本次符合。沒有產品修正或重跑。

## 功能分類

| 功能 | 案例 | 保護的內容 |
| --- | ---: | --- |
| STT 接合與比較工具 | 61 | Whisper／FunASR 輸入處理、參數、服務生命週期與比較工具契約 |
| TTS 引擎、連線與清理 | 84 | 合成 worker、Edge 連線／重試／取消、BreezyVoice 接合與已移除引擎遷移 |
| 音訊庫與聲音設定 | 70 | 聲音檔保存與參考逐字稿、主角色聲音、預覽與設定套用 |
| VAD 發話判定 | 43 | 有效語音／靜音、片段邊界、設定與服務處理 |
| TTS 比較工具 | 21 | 比較工具設定與測量／報告處理，不是本次實際 benchmark |
| 合計 | 279 | 語音處理與接合的回歸保護 |

## 逐檔追查

| 測試檔 | 案例 | 驗證重點與界線 |
| --- | ---: | --- |
| [test_asr_comparison.py](../../../../tests/test_asr_comparison.py) | 11 | 辨識錯誤計分、繁簡正規化、語系統計與延遲報告；recognizer／clock 為替身 |
| [test_whisper_asr.py](../../../../tests/test_whisper_asr.py) | 13 | 音訊解碼、單聲道處理、模型建構參數、語系重試與共享引擎；Whisper 模型為替身 |
| [test_funasr.py](../../../../tests/test_funasr.py) | 37 | 權重來源約束、文字正規化、16 kHz PCM、HTTP 限制與服務控制；模型／下載／Popen 為替身 |
| [test_breezyvoice_tts.py](../../../../tests/test_breezyvoice_tts.py) | 22 | checksum、ZIP 安全、文字前處理、top-k、取樣率、參考逐字稿與錯誤處理；真 CPU tensor，模型為替身 |
| [test_edge_connection.py](../../../../tests/test_edge_connection.py) | 14 | 暖連線、重用／到期／取消、ready 與共享 cooldown；真 loopback WebSocket 與 MP3，但遠端是假服務 |
| [test_edge_endpoint.py](../../../../tests/test_edge_endpoint.py) | 6 | 主備 host、指定握手錯誤切換、URL 遷移與暖機／首輪重試；不連正式 host |
| [test_edge_resilience.py](../../../../tests/test_edge_resilience.py) | 2 | 429 cooldown 與重試預算；使用 FakeEdge，不對真服務施壓 |
| [test_edge_tts_worker.py](../../../../tests/test_edge_tts_worker.py) | 22 | 預取、背壓、取消、順序、event loop 與 worker 關閉；真 thread／codec，合成資料流為替身 |
| [test_tts_engine_cleanup.py](../../../../tests/test_tts_engine_cleanup.py) | 18 | 移除引擎不能新增、舊設定明確遷移至 Edge、通知與保存；不是 CUDA 不可用的 CPU fallback |
| [test_default_voice.py](../../../../tests/test_default_voice.py) | 9 | 主數位人聲音來源、舊全域 TTS 清理、啟動與 pending 設定；服務／預覽為替身，沒有真發聲 |
| [test_profile_voice_preview.py](../../../../tests/test_profile_voice_preview.py) | 13 | 管理路由、預覽資料、URL／參考聲音限制、服務重用與啟動競爭；假 Engine 產生零樣本 |
| [test_voice_library.py](../../../../tests/test_voice_library.py) | 48 | 轉 WAV、hash ID／去重、逐字稿、上傳限制、回收與安全遷移；真 tmp 檔案／HTTP，不是音色授權審查 |
| [test_vad.py](../../../../tests/test_vad.py) | 43 | 切段、padding、靜音等待、最大發話與設定；多數簡化 VAD，三項使用真 Silero CPU 模型 |
| [test_tts_bakeoff.py](../../../../tests/test_tts_bakeoff.py) | 21 | 句集、計分、截斷與空音訊判定、報告／短 soak 輸出；假服務與 VRAM runner，不是真實長時 benchmark |

`test_tts_bakeoff.py` 的 soak 只跑極短測試時長，VRAM probe 使用固定替身輸出，
不能宣稱真實長時間 soak 或 GPU 記憶體實測已完成。Edge worker 的首片時序也只是
fixture 的交付條件，不是場域感知首音延遲。

## 真實運算與模擬的界線

- Whisper 辨識模型使用 mock，不能由通過判定真實中文辨識準確。
- FunASR／BreezyVoice 的服務、載入器與模型下載多由替身提供；沒有下載真權重或
  啟動真實模型服務。包含測試工具的案例也不代表這輪已做音質／速度比較。
- Silero 有使用套件內真實模型處理合成音訊／靜音的案例；不是現場真人麥克風、
  喇叭迴音或嘈雜環境驗收。
- Edge 有本機假 WebSocket 服務，以及真實 MP3 編解碼與 PyAV 處理；沒有因此
  連線 Microsoft，也不證明 Edge 外部服務目前可用。
- 音訊庫有真實暫存檔保存、移轉、回收與音訊轉換；fixture 指定 tmp 路徑。
  開發聲音匯入 CLI 也在 tmp 目錄執行，不匯入場域實際音訊庫。
- 不能把「啟動」或「預覽」案例名稱解讀為已讓真實模型發聲；需看對應 mock 與
  assertion。完整現場播放仍留在後續實機驗收。

## CUDA-only 的意思

本版只建立 CUDA PyTorch 驗證環境；不要求語音流程每一個內部操作都在 GPU 上。
例如 BreezyVoice 前處理的 G2PW ONNX 有指定 CPUExecutionProvider 的契約，
Whisper 的 CPU-int8 案例則只驗證 mock 建構參數。這些不代表建立了另一條
CPU-only CI，也不能當成真實 CPU／CUDA 模型效能測量。

本組沒有以「安裝了 CUDA」取代真 GPU 推理證據。PyTorch GPU 運算能力引用
第 1 階段的獨立探針，真實語音模型的 CUDA 推理仍須另做實機驗收。

## 警告與不可忽略的前置

本次有 5 個 DeprecationWarning，均來自 Silero 套件使用已棄用的
`importlib.resources.path`。不是 skipped 或 failed，已保留原始日誌，未改第三方程式。

若沒有 silero_vad 或 torch，部分案例會 skip；本輪相應依賴齊全，實際 0 skipped。
PyAV／libmp3lame 也是實際音訊案例的前置，本輪已能完成。

不要在測試外全域強制關閉 runtime overrides：某些聲音設定測試刻意使用臨時
覆寫檔驗證行為。隔離快照排除的是場域秘密／資產，測試自己的 tmp 設定仍須生效。

## 證據與下一步

逐項結果：[case-results.md](case-results.md)、[cases.json](cases.json)。
原始日誌：[speech-tests.log](speech-tests.log)、[收集清單](speech-collection.log)。
JUnit：[speech.xml](speech.xml)；完整性：[evidence-sha256.json](evidence-sha256.json)。

等待使用者確認理解，再進 llm 回答模型群組（盤點 117 案例）。runtime 與 speech
只是目前已完成的後端群組，其餘未因此自動算通過。
