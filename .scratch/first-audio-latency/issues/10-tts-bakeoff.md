<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# TTS 評比
Status: ready-for-agent
Blocked by: 01, 04, 09

依[規格](../spec.md)。主角 BreezyVoice；對照 Qwen3-TTS 0.6B（`faster-qwen3-tts`，權重已在本機 HF 快取、`.venv-qwen-speech` 已裝 `qwen_tts`）與 Fun-CosyVoice3 0.5B（已整合）。在 MuseTalk 與 E2B 都載入的實機上量測：

- 第一個片段（約 15 字）合成時間 P50／P95，冷／暖、LLM 串流中；目標 P50 ≤ 0.4 s、P95 ≤ 0.7 s。
- 額外顯存。
- 100 句繁體中文字錯率（含台灣讀音字：垃圾、和、星期、企業；地名；新台幣金額與日期；中英混合）；英文字錯率。
- 500 句截斷／幻覺率；8 小時穩定性。
- 產生試聽頁給使用者評主觀音質。

未達時間目標依序：縮短首句（issue 08）→ 加速 BreezyVoice（半精度、TensorRT）→ 改用 Fun-CosyVoice3＋台灣讀音字典。結果與使用者決定寫入 Comments。

## Comments

### 2026-10-30 評比工具（分支 `fal/10-tts-bakeoff`）

只完成工具與單元測試；依實作指南不得在共用 GPU 載入模型，評比數據尚未量測。

**統一介面**：三個引擎都走 `/health`＋`/inference_zero_shot`（PCM16）。BreezyVoice 與 Fun-CosyVoice3
用現有 `scripts/cosyvoice_fastapi_server.py`；Qwen3-TTS 新增 `scripts/qwen3_tts_server.py`（faster-qwen3-tts
串流，只綁 loopback，模型只從命令列指定，生成在 worker 執行緒並以鎖串行；參考錄音依內容雜湊存成固定路徑，
讓 faster-qwen3-tts 的聲線快取命中）。Fun-CosyVoice3 的 prompt 前綴沿用 `CosyVoiceTTS._zero_shot_request`，
與應用送出的請求相同。

**`scripts/tts_bakeoff.py`**：
- `vram`：啟動伺服器前記錄顯存基準。
- `run`：第一個片段（20 句、平均約 15 字）冷啟（載入後第一筆＋每次閒置 30 s 後，共 5 筆）、暖機（3 輪 60 筆）、
  LLM 串流中（`--llm-url`，同 60 筆）的首音 P50／P95、整段時間與 RTF；背景每秒以 nvidia-smi 取樣，
  記錄峰值－基準與伺服器程序顯存；再把語料（100 句繁中＋30 句英文）重複到 `--stability-count`（預設 500）。
  首音定義與應用 `first audio:` 日誌相同；BreezyVoice 不串流，首音約等於整段合成。
- `score`：伺服器全停後以 Whisper turbo 回辨所有 WAV。第一輪算 CER／WER（沿用 `compare_asr` 計分，
  另把國字、阿拉伯與混寫數字視為相同，取最接近的可接受逐字稿）；全部輪次判截斷（結尾少 ≥ 2 單位）與
  幻覺（多 ≥ 30% 或重複片段），音訊長度另判 empty／too_short／too_long。
- `report`：輸出 `bakeoff.json` 與靜態試聽頁 `index.html`（總覽、第一個片段、逐句音檔與回辨結果；
  每格可評 1–5 分，`focus` 句可勾「台灣讀音正確」，評分存瀏覽器並可匯出 JSON）。
- `soak`：獨立長跑，逐筆寫 JSON lines，結束或中斷時寫 `soak-summary.json`（每小時 P50／P95、失敗率、
  顯存成長 MiB/h）；之後重跑 `report` 會併入。

**語句集**：`.scratch/first-audio-latency/tts-bakeoff/sentences.json`（原創文字）：台灣讀音 25（垃圾、和、
星期、企業、研究、危險、頭髮、液體、法國、品質、期待…）、地名 20、新台幣金額／日期／時間 20（附口語讀法）、
中英混合 20、一般與破音字 15；英文 30。產生的音檔與原始結果在 `tts-bakeoff/runs/`，已加入 `.gitignore`。

**限制**：回辨無法分辨「垃圾」讀 ㄌㄜˋㄙㄜˋ 或 ㄌㄚㄐㄧ，台灣讀音只能靠試聽頁人工勾選。
開發用參考錄音（ticket 09，僅供開發）合成的試聽頁不可對外發布。

**授權**：`THIRD_PARTY_NOTICES.md` 新增 Qwen3-TTS（Apache-2.0）、faster-qwen3-tts 0.5.4（MIT）、
qwen-tts-hf 0.1.1.post1（Apache-2.0，已查 PyPI metadata），僅評比用、不隨附。主 venv 與 `pyproject.toml` 不變。

**驗證**：`tests/test_tts_bakeoff.py` 22 項（含以本機假 HTTP 伺服器跑 run→score→report→soak）、
`tests/test_qwen3_tts_server.py` 6 項＋1 項 FastAPI 測試（主 venv 跳過，已在 `.venv-qwen-speech` 以 CPU 通過）。
另以 CPU Whisper tiny＋Edge TTS 實跑 `score` 路徑一次（發現 Whisper 會寫「3萬2千9百」，已補混寫數字正規化）。
全套 pytest 1224 passed、4 skipped，僅 2 項已知 worktree 基準失敗；ruff、pyright、`check-integration.py` 通過。

### 待實機驗證（Status 維持 ready-for-agent）

前提：ticket 12 已釋出顯存；MuseTalk 與 E2B 照正式方式載入（每個 TTS 約需 2–4 GB）；ticket 09 第 1 步的
g2pw 已裝。每次只開一個 TTS 伺服器，埠用 50101–50103，避開應用自管的 50000。在合併後的主 checkout 執行：

```bash
cd /home/oliver/nova-avatar
P=/tmp/claude-1000/-home-oliver-nova-avatar/f284899e-3e7d-40e8-bf07-77d0ecc09394/scratchpad/breezy-dev-prompt.wav
T='在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。'
R=.scratch/first-audio-latency/tts-bakeoff/runs
LLM=http://127.0.0.1:8080/v1   # 會在 llama-server 上持續生成；舞台使用中請改用 18080 的評估實例
```

1. Qwen3-TTS 環境（不動 `.venv-qwen-speech`：faster-qwen3-tts 需 torch ≥ 2.5.1、transformers 5，且會取代 qwen-tts）：
   ```bash
   uv venv --python 3.11 /home/oliver/.venvs/faster-qwen3-tts
   uv pip install --python /home/oliver/.venvs/faster-qwen3-tts/bin/python \
     faster-qwen3-tts==0.5.4 fastapi==0.141.1 uvicorn==0.52.4 python-multipart==0.0.32
   Q=$(/home/oliver/nova-avatar/.venv-qwen-speech/bin/hf download Qwen/Qwen3-TTS-12Hz-0.6B-Base \
     --revision 5d83992436eae1d760afd27aff78a71d676296fc | tail -1)
   ```
   （本機快取只有 0.6B-CustomVoice 與 1.7B-Base；複製聲線需 0.6B-Base。）
2. 每個引擎各做一次「基準 → 啟動 → 量測 → 停止」：
   ```bash
   B=$(.venv/bin/python scripts/tts_bakeoff.py vram)
   # BreezyVoice
   BREEZYVOICE_G2PW_THREADS=6 /home/oliver/anaconda3/envs/cosyvoice/bin/python scripts/cosyvoice_fastapi_server.py \
     --host 127.0.0.1 --port 50101 --model_dir /home/oliver/nova-avatar/models/BreezyVoice \
     > logs/tts-bakeoff-breezyvoice.log 2>&1 & PID=$!; U=http://127.0.0.1:50101; E=breezyvoice; L=BreezyVoice
   # Qwen3-TTS 0.6B
   /home/oliver/.venvs/faster-qwen3-tts/bin/python scripts/qwen3_tts_server.py --model "$Q" --port 50102 \
     > logs/tts-bakeoff-qwen3-tts.log 2>&1 & PID=$!; U=http://127.0.0.1:50102; E=qwen3-tts; L="Qwen3-TTS 0.6B"
   # Fun-CosyVoice3
   /home/oliver/anaconda3/envs/cosyvoice/bin/python scripts/cosyvoice_fastapi_server.py \
     --host 127.0.0.1 --port 50103 --model_dir /home/oliver/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B-2512 \
     > logs/tts-bakeoff-cosyvoice3.log 2>&1 & PID=$!; U=http://127.0.0.1:50103; E=cosyvoice3; L=Fun-CosyVoice3
   ```
   每段只執行一個引擎的那行，等 `curl -s $U/health` 回 `family` 分別為 `breezyvoice`／`qwen3-tts`／`cosyvoice3` 後立刻：
   ```bash
   .venv/bin/python scripts/tts_bakeoff.py run --engine $E --label "$L" --url $U \
     --prompt-wav "$P" --prompt-text "$T" --server-pid $PID --vram-baseline-mib $B \
     --llm-url $LLM --note "MuseTalk+E2B 已載入；開發用參考錄音"
   kill $PID
   ```
   預期依序印 `cold 5 done`、`warm 60 done`、`contended 60 done`、`50/500 sentences`…，最後印三個階段的
   `{'n': …, 'first_audio_p50': …, 'first_audio_p95': …}` 與顯存摘要（`delta_peak_mib`）。每個引擎約 15–30 分。
   若印 `LLM produced no tokens`，LLM 中情境無效，檢查 `$LLM` 後重跑。
3. 三個伺服器都停掉後回辨（Whisper turbo 約 1.6 GB；顯存不足改 `--device cpu --asr-model small`）：
   ```bash
   .venv/bin/python scripts/tts_bakeoff.py score --runs $R/breezyvoice $R/qwen3-tts $R/cosyvoice3
   .venv/bin/python scripts/tts_bakeoff.py report --runs $R/breezyvoice $R/qwen3-tts $R/cosyvoice3
   ```
   每個 run 印 `scored 500 clips`；`report` 每引擎印一行 warm／target／zh／en／stability／vram，
   並寫出 `.scratch/first-audio-latency/tts-bakeoff/{bakeoff.json,index.html}`。
4. 8 小時穩定性（選定的引擎，預設 BreezyVoice；依第 2 步重新啟動該伺服器）：
   ```bash
   nohup .venv/bin/python scripts/tts_bakeoff.py soak --engine breezyvoice --url http://127.0.0.1:50101 \
     --prompt-wav "$P" --prompt-text "$T" --server-pid $PID --hours 8 > logs/tts-bakeoff-soak.log 2>&1 &
   ```
   結束寫 `$R/breezyvoice/soak-summary.json`（印 requests／failures／延遲漂移／顯存）；之後重跑第 3 步的 `report`。
5. 把 `index.html` 交給使用者試聽評分（以瀏覽器開本機檔），把延遲、顯存、字錯率、截斷／幻覺率、8 小時結果與
   使用者決定寫回本 Comments；未達 0.4／0.7 s 依規格順序處理後再設 `Status: resolved`。
