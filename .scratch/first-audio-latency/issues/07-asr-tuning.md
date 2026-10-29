<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 語音辨識加速與 FunASR 對照
Status: ready-for-agent
Blocked by: 01

依[規格](../spec.md)。Whisper small 在應用中 0.42–0.59 s（benchmark 暖機中位 0.167 s）：語系 auto、beam 5、經暫存檔。FunASR 10/22 實際輪次 0.04–0.13 s；`docs/project-status.md` 寫場域用 FunASR，實際跑的是 Whisper。

- Whisper：依目前對話語系固定語言、beam 1、記憶體直傳（不寫暫存檔）。
- 以 issue 01 的錄音集比較 Whisper（調整後）與 FunASR 的延遲 P50／P95 與中英文字錯率，結果寫入 Comments，選擇較快且字錯率可接受者為預設，並修正文件。

## Comments

### 2026-10-30 實作（分支 `fal/07-asr-tuning`）

- Whisper（`src/asr/engines/whisper.py`）：`beam_size=1`；改為記憶體直傳：16 kHz WAV 以 soundfile 解成 mono float32 直接交給 faster-whisper，其他取樣率或容器以 `BytesIO` 交由 faster-whisper（PyAV）在記憶體解碼重取樣，不再寫暫存檔。`BaseASR.transcribe` 改經 `_transcribe_bytes`，FunASR 仍走暫存檔（行為不變）。
- 語系：新增 `src.asr.base.asr_language`（zh-TW→zh、en-US→en）；`voice_session` 依目前對話語系固定辨識語言，不再每輪 `language='auto'` 偵測。`/asr` 上傳路由仍用設定的 `asr.language`（未變更）。
- 對照工具 `scripts/compare_asr.py`：以 issue 01 錄音集（或 `--fixtures`）經 Edge TTS 記憶體合成，切到人聲結束＋320 ms（VAD 端點），依語音輪次相同方式編碼後計時單次 `transcribe`；引擎依序載入、用完釋放。輸出各引擎各語系延遲 P50／P95、語料層級 CER（zh-TW）／WER（en-US）；`error_rate` 忽略繁簡字形，`raw_error_rate` 計入（字幕直接顯示辨識文字）。FunASR 英文標 `supported_in_app: false`（`english_requires_whisper`），不計入其 `all`。不存音訊（ADR 0004）。
- CPU 冒煙（3 句、2 輪、僅驗證工具可跑，非決策數據）：Whisper small CPU int8 約 1.0 s、CER／WER 0，但中文輸出為簡體（raw CER 0.125）；FunASR CPU 0.09–0.19 s，「Nova Avatar」誤為「novactor」。
- 測試：`tests/test_whisper_asr.py`（記憶體直傳、beam 1、混音、非 16 kHz、auto）、`tests/test_voice_session.py`（依語系固定語言）、`tests/test_asr_comparison.py` 9 項。全套 1148 passed，僅已知 2 項 worktree 基準失敗；ruff、pyright、`check-integration.py` 通過。

### 待實機驗證

依實作指南不得在共用 GPU 載入模型，對照數據尚未量測，`Status` 維持 `ready-for-agent`；預設引擎選擇與文件修正（`docs/project-status.md` 寫 FunASR、實跑 Whisper）待數據後進行。

1. 確認 GPU 至少約 1.5 GB 可用（`nvidia-smi`；兩引擎依序載入，Whisper small FP16 與 Paraformer 各約 1 GB 以內），且可連 Edge TTS。
2. 於合併後的主工作區執行：
   ```
   cd /home/oliver/nova-avatar
   .venv/bin/python scripts/compare_asr.py --rounds 3 \
     --note "whisper small 固定語系 beam1 記憶體直傳 vs paraformer-zh" \
     --output .scratch/first-audio-latency/asr-comparison-2026-10-30.json
   ```
   32 句 × 3 輪 × 2 引擎，約 2–4 分鐘。結尾印 `whisper zh-TW: n=… latency={'p50': …, 'p95': …} CER=… raw=…` 等四行（FunASR en-US 標 `not usable in app`）與報告路徑。
3. 預期：Whisper GPU P50 約 0.1–0.2 s（10/29 benchmark：auto＋beam 5 暖機中位 0.167 s）；FunASR zh P50 約 0.04–0.13 s。字錯率以 `error_rate` 比較，`raw_error_rate` 顯示 Whisper 簡體輸出對字幕的影響。
4. 決策注意：選 FunASR 為預設時 en-US 對話會被 `check_language_support` 拒絕（`english_requires_whisper`）；Whisper 中文常輸出簡體，若選 Whisper 需另評估字幕轉繁。
5. 選定後：更新 `config/config.yaml` 預設與 `docs/project-status.md`，重啟後端並以 `scripts/measure_first_audio.py` 驗證語音輪次 `asr` 階段，結果補在本 Comments，再設 `Status: resolved`。
