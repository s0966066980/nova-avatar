<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 停用預設 Ollama 與顯存盤點
Status: resolved
Blocked by: 04

依[規格](../spec.md)。10/29 實測 4090 已用 22.1／24.5 GB：Nova 10.7、llama-server 6.0、Ollama（11434）1.6、不明 python 約 2.9 GB。

- 主要 LLM 改走 llama.cpp 後，啟動腳本與設定不再需要 11434 的 Ollama；保留 RAGFlow 嵌入用的 11435。文件說明如何停用。
- 盤點不明 python 程序（指令列、啟動來源）並在 Comments 回報；不終止任何程序。
- 記錄 E2B＋MuseTalk＋BreezyVoice 同時載入時的顯存。

## Comments

### 2026-10-30 實作（分支 `fal/12-ollama-vram`）

**設定**：`config/config.yaml` 預設改為 `provider: llamacpp`、`base_url: http://127.0.0.1:8080/v1`、`model: Qwen3.5-9B-UD-Q4_K_XL`（ticket 04 的 E2B 仍待使用者決定，未切換）。後端啟動時依此自行拉起 llama-server，不再需要 11434。`ollama` 仍留在 `llm.endpoints` 供明確選用。刻意不寫 `llm.endpoint`：舊版 `runtime_overrides.yaml` 只存 provider／base_url（本機現況即如此），仍依網址選回原端點；寫死 `endpoint` 會把舊的 Ollama 選擇悄悄改成 llama.cpp。`extra_body.reasoning_effort` 對 llamacpp 原本就會剔除。`config_musetalk.yaml`、`config_wav2lip.yaml`、`config_commercial.yaml` 明確選 Ollama，維持不動。

**啟動腳本**：`start-all.sh`／`start-backend.sh` 本來就不碰 11434；`ragflow.sh up` 在非共用模式只用 11435。仍會連 11434 的是 RAGFlow 的 `pull-model`（`ollama` CLI 下載與核對 BGE-M3）、`connect-chat`、`unify-models`／`sync-models`（共用模式），文件註明執行前暫時啟動系統 Ollama。

**文件**：`docs/installation.md` 新增「停用預設 Ollama（11434）」（檢查無設定選 Ollama → `sudo systemctl disable --now ollama`，恢復方式、不可移除 Ollama 程式與模型目錄的原因）；README、`docs/ragflow.md` 改寫相關敘述。

**驗證**：新增 `tests/test_default_llm_endpoint.py` 6 項（預設選 llama.cpp、ollama 端點保留、已存的 Ollama 選擇與無 `endpoint` 的舊覆蓋仍走 11434、舊單端點設定不變、文件說明停用）。ruff、pyright、`check-integration.py` 通過；全套 pytest 1202 passed、3 skipped，另 2 項為 worktree 缺本機資產的已知基準失敗。未動 `web/`。

### 顯存盤點（2026-10-30 01:05，唯讀；未終止任何程序）

`nvidia-smi`：已用 21,805／24,564 MiB。

| PID | 程序 | 顯存 | 是什麼、誰啟動 |
|---|---|---|---|
| 142646 | `.venv/bin/python3`（Nova 後端 8010） | 10,750 MiB | MuseTalk、Whisper 等 |
| 143110 | `llama-server`（8080） | 6,052 MiB | Qwen3.5-9B，Nova 後端啟動 |
| 90297 | `ollama runner`（bge-m3） | 1,630 MiB | **不是 11434**：父程序 2523 `ollama serve` 監聽 `172.17.0.1:11435`，cgroup 為使用者服務 `nova-ragflow-embedding.service`（`scripts/ragflow_embedding.sh`）。模型 blob `sha256-daec91ff…` 對應 `bge-m3:latest`。10/29 11:35 載入後持續常駐（`OLLAMA_KEEP_ALIVE=5m` 仍未卸載，推測 RAGFlow 的嵌入請求帶常駐參數） |
| 2191149 | `python background_in_plus_max_hand_safe.py` | 932 MiB | Nova 以外的專案：cwd `/home/oliver/數字人`，conda 環境 `livetalking`（Python 3.10），10/29 18:40 由使用者在 GNOME Terminal（pts/3 的 bash）手動啟動，監聽 `127.0.0.1:7860`（Gradio 預設埠）。無 systemd／cron／autostart |
| 1549188、2252000、2269613 | `/usr/bin/showtime --gapplication-service` | 774＋774＋388 MiB | GNOME「Showtime」影片播放器（系統 Python 3.14 的 GTK 應用），由 `systemd --user` 的 D-Bus 啟用，10/29 16:37／18:50／18:54 各開一個（推測開影片檢視錄影） |
| 3338077 | `nautilus` | 31 MiB | 檔案管理員 |

- 系統 `ollama.service`（PID 6184，使用者 `ollama`，`enabled`，`127.0.0.1:11434`）目前**沒有載入任何模型**（RSS 約 17 MB、不在 GPU 清單）；journal 只有控制台列模型的 `/api/tags` 與 `ollama show`。停用它不會立即釋出顯存，作用是避免選到 Ollama 端點時再載一份 `qwen3.5:4b`。10/29 記為「Ollama（11434）1.6 GB」的其實是 11435 的 BGE-M3。
- 「不明 python 約 2.9 GB」＝ Showtime 三個實例 1,936 MiB ＋ `數字人` 專案 932 MiB；都與 Nova 無關，關閉與否由使用者決定。若 RAGFlow 嵌入改用 CPU 可再釋出約 1.6 GB，但會拉長檢索時間，未變更。
- 使用者決定停用 11434 時：先確認 `config/runtime_overrides.yaml` 與每個數位人的 `llm.endpoint` 都不是 ollama（本機現況皆為 llamacpp），再自行執行 `sudo systemctl disable --now ollama`。

### 待實機驗證（Status 維持 ready-for-agent）

E2B＋MuseTalk＋BreezyVoice 同時載入的顯存需在 ticket 04 使用者接受 E2B、ticket 09 合併後量測：
1. 數位人設定檔 `llm.model` 為 `gemma-4-E2B_q4_0-it`、TTS 選 BreezyVoice，重啟後端（`bash scripts/start-all.sh config/config.yaml`）；日誌應有 `--mmproj` 與 `-ngl 99`。
2. 跑一輪讓所有模型就緒：`.venv/bin/python scripts/measure_first_audio.py --rounds 1 --warmup 1 --note "ticket 12 VRAM"`。
3. 記錄：
   ```
   nvidia-smi --query-gpu=memory.used,memory.total --format=csv
   nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
   ```
   依 PID 分列 llama-server（E2B）、Nova 後端（MuseTalk＋Whisper）、BreezyVoice（CosyVoice 伺服器）、11435 BGE-M3，以及非 Nova 程序；回填本節合計與「扣除非 Nova 程序後」的數字。

### 2026-10-30 實機（orchestrator）
E2B（含 mmproj）＋MuseTalk 已載入時 GPU 共 18.0 GB；再載 BreezyVoice 峰值 23.9／24.5 GB、Fun-CosyVoice3 峰值 23.4 GB，餘量不足 1 GB。停用 11434 需使用者以 sudo 執行 `sudo systemctl disable --now ollama`（幾乎不省顯存，選擇性）。
