<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# LLM 全 GPU 啟動
Status: ready-for-agent

依[規格](../spec.md)。`src/llm/llamacpp.py:266` 依啟動當下剩餘顯存決定 `-ngl`；llama-server 在 MuseTalk 載入後才啟動，10/29 21:29 只得到 31 層（生成約 35 tok/s，全 GPU 時 107–124）。最新 `logs/llama-server.log` 首行為「no usable GPU found」，一併查明。

- 啟動順序改為 llama-server 先於數位人模型載入。
- 算出的層數小於模型全部層數時，啟動失敗並說明需要的顯存與目前占用者；設定可明確允許部分卸載（預設不允許）。
- 非全 GPU 執行時，`/health` 與控制台顯示警告。

完成：模擬顯存不足的測試；實機啟動日誌顯示 `-ngl 99`。

## Comments

### 2026-10-30 實作（分支 `fal/03-llm-full-gpu`）

**「no usable GPU found」查明（唯讀）**：`logs/llama-server.log` 以附加模式寫入、從不分段，首行是檔案中最舊的一次啟動（檔案建立於 9/16；該次載入 LFM2.5-2.6B、`n_threads = 4`、生成約 13 tok/s，即純 CPU）。之後幾行 `libcudart.so.12: cannot open` 也是舊版本的殘留。現行 binary（`~/llama/llama.cpp/build/bin/llama-server`，8/19 編譯，`GGML_CUDA=ON`，連結 `libcudart.so.13`）可用 CUDA；21:29 那次（ngl 31）與目前執行中的 pid 3292136（`-ngl 99`，占用 6050 MiB）都在 CUDA0。結論：該行不代表目前狀態，是共用日誌沒有分段造成的誤讀。未執行 `--list-devices`，因為它會建立 CUDA context、占用顯存。

**變更**
- `src/server/app.py`：拆出 `_load_startup_models()`，先啟動 llama-server，再載入數位人。llama 啟動失敗只記錄錯誤，服務照常啟動，讓控制台仍可連入處理。
- `src/llm/llamacpp.py`：`ensure_server(..., allow_partial_offload=False)` 遇到以下情況時拋出 `GpuOffloadError`：算出的層數少於全部層數、只有 CPU 版、全 GPU 載入時 OOM、或本次日誌出現「no usable GPU found」。錯誤訊息列出需要的顯存（模型大小＋2048 MiB）、目前剩餘顯存、`nvidia-smi` 列出的占用程序前 6 名，以及開啟部分卸載的設定。只有允許部分卸載時，才保留原本「減半層數重試」的行為。每次啟動前，在 `llama-server.log` 寫入 `===== <時間> nova-avatar 啟動 llama-server: <cmd> =====` 分隔行，「no usable GPU found」只比對分隔行之後的內容。新增 `gpu_offload_status()`。外部（非本程序啟動）的 llama-server 會從其命令列讀取 `-ngl`。
- 設定：新增 `llm.llamacpp_allow_partial_offload: false`，`schema.py`、`config.yaml` 都已加入，四個 `ensure_server` 呼叫端都會傳入。
- `/health`：provider 為 llamacpp 且狀態已知時，多一個布林欄位 `llm_full_gpu`。**依 ADR 0021，`/health` 仍是公開路由，新增的公開資訊只有這一個布林值**；層數、顯存與占用程序只寫入後端日誌。測試會確認回應中不含層數與 pid。
- 控制台：新增 `web/src/backendHealth.js`。`llm_full_gpu === false` 時顯示常駐警告列，就緒後每 30 秒重新檢查（三語系）。

**驗證**：`tests/test_llamacpp.py` 新增 8 項（模擬顯存不足會拒絕、訊息含需求與占用者；全 GPU 時為 `-ngl 99`；允許時可部分卸載並回報；no usable GPU；日誌分段；CPU 版拒絕；啟動順序；顯存不足時服務仍啟動），`tests/test_health_route.py` 新增 3 項，`web/tests/backend-health.test.js` 新增 2 項。pytest 1094 passed、3 skipped，另有 2 項失敗，都是 worktree 缺少本機資產的已知基準失敗。ruff、pyright、check-integration 通過。前端 lint 通過、測試 208/208、build 成功。

**待實機驗證**（需要重啟 8010 後端與它擁有的 llama-server，由 orchestrator 依序執行）
1. 停掉現行後端，以本分支啟動：`scripts/start-backend.sh`（或 `uv run python src/server/app.py --config config/config.yaml`）。
2. 後端日誌應依序出現：「正在啟動 llama-server」→「llama-server 使用 CUDA 解除安裝 99 層」→「llama-server 已就緒」→「正在載入數字人」→「數字人載入完成」。
3. `tail -n 80 logs/llama-server.log`：最後一個 `===== … nova-avatar 啟動 llama-server: … -ngl 99 =====` 之後不應出現 `no usable GPU found`。`pgrep -a llama-server` 應含 `-ngl 99`。
4. `curl -s http://127.0.0.1:8010/health` 應含 `"llm_full_gpu": true`，控制台不顯示 GPU 警告。
5. 風險：LLM 改為先占顯存（Qwen3.5-9B 約需 5851＋2048 MiB），若 MuseTalk／TensorRT 因此載入失敗，日誌會出現「啟動時載入數字人失敗」，需記錄當下 `nvidia-smi`，再依 Q13 換用較小的 LLM。
