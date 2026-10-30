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
