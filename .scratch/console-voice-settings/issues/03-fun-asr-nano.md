<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# Fun-ASR-Nano-2512 取代 paraformer-zh
Status: ready-for-agent

依[規格](../spec.md)「語音辨識引擎」。調查摘要：Fun-ASR-Nano-2512（HF/ModelScope `FunAudioLLM/Fun-ASR-Nano-2512`，Apache-2.0，8 億參數，中文含方言、英文、日文，可中英混說，需 `trust_remote_code`）；輸出簡體，需 OpenCC `s2twp`。

- 下載腳本比照 `scripts/breezyvoice_weights.py`：釘 revision 與 sha256，放 `models/`。
- FunASR 引擎改載入此模型，遠端程式碼只允許釘住的版本；輸出轉繁體；中英文都接受（移除 `english_requires_whisper` 限制，若仍需要則說明）。
- 移除 `paraformer-zh` 與其下載／設定；`THIRD_PARTY_NOTICES.md` 加 Apache-2.0 聲明。
- `scripts/compare_asr.py` 支援新模型，GPU 實測交由 orchestrator（待實機驗證）；依結果在選單標「中英文」或「較慢」。

## Comments

### 2026-10-30 調查結果：依賴衝突，暫停整合（需決策）

- **載入方式（已查一手來源）**：HF `FunAudioLLM/Fun-ASR-Nano-2512` @ `272c57b82523ada6fd87095e955f8e29100979ab`（Apache-2.0）。模型庫本身沒有程式碼；已鎖定的 `funasr==1.4.15` 內建並註冊 `FunASRNano`（`funasr.models.fun_asr_nano`），本機資料夾以 `AutoModel(model=<dir>, device=..., disable_update=True, trust_remote_code=False)` 即可載入，**完全不需遠端程式碼**（比「只允許釘住版本的遠端程式碼」更嚴）。
- **權重**：新增 `scripts/fun_asr_nano_weights.py`（釘 revision、10 個檔案 sha256，`model.pt` 1.97 GB；`Qwen3-0.6B/` 只有 config 與 tokenizer，權重在 `model.pt`）。已下載到主 checkout `models/funasr/Fun-ASR-Nano-2512`，`--check` 通過。
- **阻擋點**：解碼器是 Qwen3-0.6B，`transformers` 需 ≥4.51（Fun-ASR 官方 requirements 為 `>=4.51.3`）。主環境釘 `transformers==4.46.0`，且 `src/avatars/musetalk/pyproject.toml` 釘 `transformers>=4.44.1,<4.47`；主 venv 實測 `AutoConfig` 回報「不認得 `qwen3`」。升級 transformers（連帶 `tokenizers` 0.20→0.21）會影響 MuseTalk 與現場主環境，不屬於可直接裝進主 venv 的小型依賴，故未安裝、未改 `pyproject.toml`，引擎／選單／移除 paraformer 也未動。
- **CPU 冒煙（另建 venv，不在 repo）**：`torch==2.5.0+cpu`、`transformers==4.51.3`、`funasr==1.4.15`，`trust_remote_code=False`。載入 36 s；模型卡範例 zh 約 1.0 s「开放时间早上九点至下午五点。」（簡體，需 `s2twp`）、en 約 1.6 s 正確。torch 2.5 可用，唯一缺的是 transformers。Edge TTS 合成測試語句時遭 429，fixtures 未跑。
- **可選方案**：(A) 全專案升 `transformers==4.51.3`／`tokenizers` 0.21，放寬 MuseTalk 上限，實機驗證 MuseTalk 嘴型與 GPU 比較；(B) 比照 BreezyVoice，在獨立 venv 以本機服務執行 Fun-ASR-Nano，主程序經 HTTP 呼叫；(C) 改用官方 llama.cpp／GGUF 版（`FunAudioLLM/Fun-ASR-Nano-GGUF`），與既有 llama.cpp 部署一致。決定後再完成引擎、選單、移除 paraformer、`THIRD_PARTY_NOTICES.md` 與 `compare_asr.py`。

### 2026-10-30 使用者決定（Q12）
選 (B)：Fun-ASR-Nano 以獨立本機服務執行（自己的 venv，transformers ≥ 4.51），比照 BreezyVoice 只綁 loopback、只在選 FunASR 時啟動；Nova 主環境的 transformers 維持 MuseTalk 相容版本。

### 2026-10-30 實作（Q12 方案 B，分支 `cvs/03-fun-asr-nano-service`）

- **服務**：`scripts/fun_asr_nano_server.py`（標準函式庫 HTTP，只接受 loopback `--host`，預設 `127.0.0.1:50010`）。`GET /health` 回報模型資料夾與裝置；`POST /recognize?language=auto|zh|en&script=traditional-tw|simplified` 收 16 kHz 單聲道 PCM16（上限 60 秒），以 `AutoModel(..., trust_remote_code=False)` 推論、預設經 OpenCC `s2twp`，回 `{text, language}`（含漢字為 zh）。推論以鎖序列化。
- **venv**：`integrations/fun-asr-nano/requirements.in` → 編譯後完整釘版的 `requirements.txt`（torch/torchaudio 2.5.0+cu124 與主環境相同、funasr 1.4.15、transformers 4.51.3、OpenCC 1.4.2）；`bash scripts/setup-fun-asr-nano.sh [路徑]` 以 `uv pip sync` 建立 `~/.venvs/fun-asr-nano`（已建立，5.7 GB；其他路徑設 `FUN_ASR_NANO_PYTHON`）。
- **Nova 端**：`src/asr/fun_asr_nano_service.py` 管理程序（比照 BreezyVoice：獨立 session、`logs/fun-asr-nano-server.log`、健康檢查比對模型與裝置、只停本 checkout 腳本的殘留程序），`FunASR` 引擎改為 HTTP 用戶端，載入時才啟動服務（即只在選 FunASR 時）；改選 Whisper 時 `stop_server()` 釋放顯存，後端結束時停止；`process-control.sh` 的 `nova_stop_model_servers` 一併清理孤兒。模型只接受清單 ID `Fun-ASR-Nano-2512`，舊設定的 `paraformer-zh` 自動改用它，其他字串拒絕（規則 1）。
- **英文**：移除 `english_requires_whisper`（後端與前端字串），FunASR 可用於英文對話；`supports_language_options=True`，語音輪次為 auto。
- **移除 paraformer-zh**：引擎程式、`pyproject` 的 `funasr` extra（`uv.lock` 同步刪除 funasr 相依）、CI 安裝、`check-integration`（改查服務 venv 與權重）、文件。`THIRD_PARTY_NOTICES.md` 新增 Fun-ASR-Nano（Apache-2.0）、Qwen3-0.6B、FunASR（MIT）、OpenCC 條目。主 checkout 的 `models/funasr/paraformer-zh` 未刪，可自行移除。
- **compare_asr**：預設 `--funasr-model Fun-ASR-Nano-2512`，FunASR 計入中英文，跑完停止服務。
- **CPU 冒煙（模型卡範例音檔）**：`ensure_server` 啟動＋預熱 16.6 s；zh 0.7–0.8 s「開飯時間早上九點至下午五點。」、en 1.05 s 正確、靜音回空字串、`simplified` 保留簡體；`stop_server` 後服務已關。註：「开放／开饭」為邊界字，float 波形得「开放」、同一音訊量化為 int16 即得「开饭」，與傳輸無關（語音輪次本來就是 PCM16）。
- **檢查**：pytest 1368 passed（僅兩個已知 worktree 基線失敗）、ruff、pyright、check-integration、`uv lock --check`、web lint／test（216）／build 通過。

### 待實機驗證（orchestrator）

1. GPU 比較（後端可不停）：`uv run --no-sync python scripts/compare_asr.py --engines whisper,funasr --device cuda --note "Fun-ASR-Nano-2512 service"`；預期 `.scratch/first-audio-latency/asr-comparison-<日期>.json` 列出兩引擎 zh-TW／en-US 延遲與 CER/WER，FunASR 的 en-US `supported_in_app: true`。Edge TTS 若 429，稍後重試。
2. 依結果把 `src/server/runtime_settings.py` 的 `STT_ENGINE_META["funasr"]["label"]` 改為「Fun-ASR-Nano-2512（中英文）」或「（較慢）」。
3. 控制台套用 FunASR（device auto）：`logs/fun-asr-nano-server.log` 出現 `Fun-ASR-Nano ready http://127.0.0.1:50010 ... device=cuda`，`nvidia-smi` 多一個 `fun_asr_nano_server.py` 程序；舞台中文、英文各說一句，字幕為繁體／英文。記錄與 MuseTalk＋E2B 同時的顯存峰值。
4. 改回 Whisper：`ss -ltn 'sport = :50010'` 無監聽、`nvidia-smi` 該程序消失。
