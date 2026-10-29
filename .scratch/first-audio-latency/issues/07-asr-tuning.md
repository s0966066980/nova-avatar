<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 語音辨識加速與 FunASR 對照
Status: resolved
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

### 2026-10-30 中英自動偵測（Q24，分支 `fal/07b-asr-zh-en-detect`）

實測（`after-06-2026-10-30.json`）固定 zh 時，zh-TW 對話裡的英文被辨識成中文亂碼，10 輪交接有 2 輪失敗；依 Q24 改為只在中英文間自動偵測。

- `src.asr.base.SPEECH_LANGUAGES = ("zh", "en")`（取自對話語系對照）。Whisper `language="auto"` 改為限中英：先用 faster-whisper 內建偵測；最高者不是 zh／en 時，取 `all_language_probs` 中 zh、en 較高者重新解碼。faster-whisper 解碼是惰性的，錯誤語言的片段不會被產生，只多算一次特徵。beam 1、記憶體直傳不變；`BytesIO` 重試前 `seek(0)`。
- 回報：結果 `language` 為實際採用的 zh／en，另加 `language_probability`；`[ASR] transcription completed language=` 照常記錄。固定語言時回報指定語言。
- `voice_session` 語音輪次一律 `language="auto"`，不再依對話語系固定。Whisper 預熱改走偵測路徑。`/asr` 上傳路由仍用設定 `asr.language`；設為 `auto` 時同樣只偵測中英（應用只支援這兩種）。`asr_language` 保留給 `compare_asr` 計分與 `tts_bakeoff`（已知語言的 TTS 評分）。
- `scripts/compare_asr.py`：Whisper 每句以 `auto` 辨識，記錄 `expected_language`／`detected_language`，報告新增各語系 `language_accuracy`（FunASR 為 null），結尾行印出。
- 成本：faster-whisper 1.2.1 的非批次 `transcribe` 偵測時另跑一次編碼器（30 s 窗），解碼時不重用。CPU int8 small 同 6 句×2 輪：固定語言中位 1.057 s、偵測 2.049 s（CPU 上編碼器占大宗）。GPU 上多一次 small 編碼器，估計只多數 ms 至十多 ms，**待實機驗證**。若實測明顯超過 0.1 s，可改為自行編碼一次、以 `model.detect_language` 限中英後把同一份 encoder output 交給 `generate_segments`。這要用到 faster-whisper 內部 API，這次沒做。
- CPU 冒煙（`compare_asr.py --engines whisper --device cpu --rounds 1`，32 句）：語言偵測 zh-TW 18/18、en-US 14/14 正確；CER 0.012（raw 0.107，簡體）、WER 0。
- 測試：`tests/test_whisper_asr.py`（一次偵測、限中英重試且不解碼錯誤語言、容器重讀、固定語言回報、log、預熱）、`tests/test_voice_session.py`（各語系皆 `auto`）、`tests/test_asr_comparison.py`（偵測正確率）。全套 1271 passed，僅已知 2 項 worktree 基準失敗；ruff、pyright、`check-integration.py` 通過。

#### 待實機驗證（中英偵測）

1. 合併並重啟後端（由編排者執行）。
2. GPU 有約 1.5 GB 可用時：`.venv/bin/python scripts/compare_asr.py --rounds 3 --note "whisper small 中英自動偵測 beam1 記憶體直傳 vs paraformer-zh" --output .scratch/first-audio-latency/asr-comparison-2026-10-30.json`。預期 whisper 兩語系 `language_accuracy` 接近 1.000，latency P50 約 0.1 s 以內（固定語言時為 0.065 s）。
3. 以 `scripts/measure_first_audio.py` 用與 after-06 相同的 builtin 錄音集重跑（英文句在 zh-TW 對話中），確認 `asr` 階段 P50 約 0.1 s、英文不再被辨識成中文，交接不再失敗；`logs/` 中 `transcription completed language=en` 會出現在英文輪次。

### 2026-10-30 GPU 比較結果（orchestrator）
`asr-comparison-2026-10-30.json`（MuseTalk＋E2B 已載入，3 輪、96 句）：
- Whisper small（中英自動偵測、beam 1、記憶體直傳）：zh-TW P50 0.059／P95 0.082 s、CER 0.012；en-US P50 0.051／P95 0.073 s、WER 0；語言偵測 100%。
- FunASR paraformer-zh：zh-TW P50 0.050／P95 0.054 s、CER 0.012；英文 WER 0.069 且應用中不接受英文。
決定：預設維持 Whisper（中英偵測），速度與 FunASR 同級且支援英文。`docs/project-status.md` 中「場域用 FunASR」的敘述由 issue 14 修正。中英偵測的實際首音量測併入下一次整合量測。
