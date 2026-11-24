<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 目前版本的主要測試基準

本版基準定義在 [current-version-baseline.json](../tests/current-version-baseline.json)，
執行入口是 [check-current-version.py](../scripts/check-current-version.py)。
這是已可在本機重現的基準；GitHub GPU runner 尚未接上，現有 workflow 不能
因為本機通過而宣稱已符合本版 CUDA-only 設計。

## 範圍來源

以目前 `pyproject.toml` 的版本、`config/config.yaml` 的出廠預設、README 的支援
能力，以及已接受 ADR 的行為為依據。基準會核對出廠設定與版本；改動這些值時
需一併審查測試基準，不能容許「新舊預設都算通過」的過渡斷言一直留著。

| 類別 | 本版範圍 |
| --- | --- |
| 驗證環境 | Python 3.11、lock frozen、PyTorch 2.5.0+cu124、CUDA 12.4 與實際 NVIDIA GPU；Node 22 |
| 出廠預設 | MuseTalk、Whisper small、Silero、Edge TTS、llama.cpp／Gemma 4 E2B |
| 現行可選能力 | Qwen3.5-9B、Fun-ASR-Nano、BreezyVoice、Ollama／已配置的 OpenAI-compatible 端點 |
| 對話能力 | 目前的回覆規則、看板、串流、輪次隔離、角色交接、控制台與舞台隔離 |
| 安全與維護 | 路由權限、來源與限制標示、資產回收、舊設定拒絕／安全遷移、依賴契約 |

Edge 的出廠設定不等於商用或離線場域的正式聲音選擇；各模型、聲音與服務的
適用限制仍須依現有 notices 和實際用途處理。

## 必要基準

1. `uv lock --check` 與 `uv sync --frozen --check`；已安裝環境必須與選定 lock 群組一致。
2. 真實 CUDA tensor 運算，不只檢查套件名稱；沒有 CUDA 時直接失敗。
3. Ruff、Pyright、ESLint；保留各工具實際已啟用的範圍限制。
4. 品牌／來源聲明與離線整合稽核。
5. 七個產品領域的主要 Python 回歸，使用 `-m "not live"`，要求 **0 failure、0 skip**。
6. 前端測試使用 `CI=1`，缺 Chrome 必須失敗；要求 **0 failure、0 skip**。
7. 前端正式建置。

正式依賴 `npm audit --omit=dev` 仍是 advisory，結果會保存，尚未變更已決定前的
阻擋政策。開發依賴審計問題另有紀錄，安裝成功不代表安全審查完成。

不把固定案例總數當作成功定義：案例新增／刪除必須有行為與範圍理由。每次都
保存 collection、JUnit、日誌、實際版本、來源差異與 hash，供追查基準是否變動。

## 實機發行驗收

仍適用的真實環境檢查使用 `live` 標記，由主要回歸明確 deselect，不是執行後
以 skip 當成通過。目前有真 `llama-server -h` 環境檢查與兩個已配置模型的看板
契約；執行 live 時缺少 binary 應失敗，模型路徑從設定取得。

```bash
NOVA_AVATAR_LIVE_LLM_CONTRACT=1 uv run --no-sync pytest -v -ra -m live
```

它們屬於當前版本，沒有因清理而刪除；但這三項仍不足以取代實際選定模型的
CUDA 推理、WebRTC、插話／角色交接、感知首音延遲與視聽驗收。這些發布門檻
要另外保存實機證據，不能由本機主要基準的綠燈代替。

## 本機執行

在 repository root 使用獨立環境，避免覆蓋場域正在使用的 `.venv`：

```bash
export UV_PROJECT_ENVIRONMENT="$PWD/.cache/ci-current-cu124"
uv lock --check
uv sync --frozen --python 3.11 --group dev --group ci --extra vad

# 已有 Node 22 時可直接執行；此命令也可明確選用 Node 22。
npm exec --yes --package=node@22 -- \
  uv run --no-sync python scripts/check-current-version.py
```

第一次需下載鎖定套件與 CUDA 函式庫。`playwright-core` 不附 Chrome，前端畫面
測試需已安裝 Chrome，或透過 `CHROME_PATH` 指向可用執行檔。

逐步執行可加 `--stage environment|static|integration|python|web|build`，每次仍先
核對來源、版本與 CUDA 前置，再只執行指定階段；不把單階段成功當完整基準通過。
也可用 `--output` 指定尚不存在的紀錄目錄，避免覆寫既有結果。

預設結果保存在 `.scratch/current-version-baseline/<run>/`，含 `result.json`、
`source-sha256.json`、來源 HEAD／差異、各命令與日誌、Python JUnit 和 `sha256.json`。
目前工作若尚未提交，以 HEAD 加 diff 及檔案 hash 表達，不冒充乾淨 commit。

## 此次清理決策

| 舊案例 | 處理與原因 | 留下的保護 |
| --- | --- | --- |
| 需要 Qwen3.8-27B 實體檔的層數檢查 | 刪除該特定模型依賴，不列 optional skip | 使用最小 GGUF fixture 驗證通用 block_count parser |
| Gemma／Qwen 都可當預設的過渡斷言 | 收緊為本版 Gemma 4 E2B | Qwen3.5-9B 作為可選模型仍有 thinking-off／grammar 契約 |
| LFM 專用 thinking 測試 | 改為本版 Qwen3.5-9B 請求契約 | 通用請求與回覆 grammar 驗證保留 |
| 舊關鍵字計分＋灰區 classifier 的 11 個案例 | 刪除已無現行呼叫者、ADR-0012 已否決的行為測試 | 現用單一模型協定、可編輯規則、首句與串流測試仍在 |
| 強制 CI 保留 CPU wheel 選項 | 移除過時斷言；保留舊 workflow 的 lock 先後順序檢查 | 新本機入口以 frozen 檢查及真 GPU 運算保護 CUDA 基準 |
| 需要主機 binary 的 help 檢查 | 改列 live 前置，不混入自足主要回歸 | 真 binary 檢查保留，不用 mock 冒充可執行性 |

舊模型名稱若只是 catalog／程序所有權的假資料，改為中性 fixture 名稱並保留
行為驗證。舊設定遷移／拒絕、適用來源 notices、Wav2Lip 非商用標示，以及現行
CPU 子元件的契約仍然相關；不能只按字串或檔案年齡刪除。

歷史測試結果原樣保留，包含舊模型 skip；它們是當時證據，不是本版允許清單。
先前把 Qwen3.8 列為選用的提案已由本次範圍清理決定取代。
