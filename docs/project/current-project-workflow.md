<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 目前專案工作流程

更新日期：2026-11-28

這份文件取代零散的接續工作，建立可重複執行的 Nova Avatar 維護流程。目前的基線記錄在
[project-status.md](project-status.md)；進行中的規格與工作項目，依專案的 issue-tracker 慣例放在
本機、不進 git 的 `.scratch/`。

## 開始新的工作項目

1. 先看 `docs/project/project-status.md`、`CONTEXT.md`、`docs/adr/` 中相關的 ADR，以及
   [來源歸屬稽核](source-attribution-audit.md)。
2. 建立 `.scratch/<feature>/spec.md`，每個實作議題在 `.scratch/<feature>/issues/` 下各一個工單檔。
3. 使用 `docs/agents/triage-labels.md` 的標籤；不要把舊的基準檔案本身當成未完成的工作。
4. 選定相關的設定檔，並寫明這項工作是否影響商業審查設定檔或受限制的第三方元件。

## 實作與驗證

1. 以最小的原始碼、設定與文件變更，完成已接受的工作項目。
2. 先跑聚焦的測試。驗證指令需先用 `uv sync --group dev` 準備開發環境，再執行
   `uv run ruff check .`、`uv run pyright` 與 `npm --prefix web run lint`。Ruff 涵蓋應用程式碼、腳本與測試，
   隨附的引擎／vendor 目錄已在 `pyproject.toml` 排除。Pyright 檢查 `core/nova_core/server` 的未綁定與可能未綁定名稱，
   加上目前已通過的基本模式規則。ESLint 涵蓋前端原始碼、測試與設定，使用 JavaScript recommended 與 Vue essential 規則；
   初期門檻延後處理未使用程式碼的清理與錯誤成因慣例，說明見 `web/eslint.config.js`。
3. 執行離線的專案檢查：

   ```bash
   uv run python scripts/check-integration.py
   ```

4. 只有在刻意啟用所設定的 LLM 與 TTS 服務時，才執行它們的 smoke 檢查；沒有指定輸出路徑就不會寫出音訊：

   ```bash
   uv run python scripts/check-integration.py --smoke
   ```

5. 交付前執行 Python 測試、前端測試與正式建置。只有在範圍包含真實服務與硬體時，才跑語音／WebRTC soak，
   並把報告路徑記在該工作項目的紀錄中。

GitHub Actions 透過 `.github/workflows/ci.yml`，在 push 與 pull request 時執行這些離線檢查。
其 Python 工作使用 Python 3.11、CPU 版 PyTorch wheel、`vad` extra，以及 `dev` 與 `ci` 依賴群組；
`ci` 群組提供離線檢查所需的 MuseTalk import 探測，不載入模型。要在獨立環境重現 Python 工作：

```bash
export UV_PROJECT_ENVIRONMENT=/tmp/nova-avatar-ci-venv
uv venv --python 3.11 "$UV_PROJECT_ENVIRONMENT"
uv pip install --python "$UV_PROJECT_ENVIRONMENT/bin/python" \
  --no-sources --torch-backend cpu --group dev --group ci \
  -e ./contracts -e './core[vad]' -e ./services/stt -e ./services/llm \
  -e ./services/tts -e ./avatar -e .
uv run --no-sync ruff check .
uv run --no-sync pyright
uv run --no-sync lint-imports
uv run --no-sync python scripts/generate_openapi.py --check
uv run --no-sync python scripts/check-integration.py
uv run --no-sync pytest
```

在那個隔離環境中，指令請保留 `--no-sync`，才會沿用已安裝的 CPU wheel，不會再依部署用的 CUDA 索引重新解析。
CPU 後端使用 uv 的 [PyTorch pip 整合](https://docs.astral.sh/uv/guides/integration/pytorch/#automatic-backend-selection)。

前端工作使用 Node.js 22，在 `web/` 內執行 `npm ci`、`npm run lint`、`npm test` 與 `npm run build`。
需要真實服務與硬體的檢查仍須明確執行，不屬於這個離線流程。

## 清除過往工作項目與流程

1. `.scratch/` 只在本機：已列入 `.gitignore`，不會推送。其中的規格、工單、原型、截圖與 soak JSON 都是證據，
   不是隱含的待辦。截至 commit `b2b610b` 的追蹤版本仍在 git 歷史中
   （`git show b2b610b:.scratch/<路徑>`）。
2. 每個過往的工作項目，都要在它的工單或規格記下最終狀態：已交付、已被取代、受阻，或保留作基準。
   仍支持發行聲明的證據要保留，並從目前的工作項目連結過去。
3. 只有在維護者確認確切路徑與保留需求後，才能把過時的實驗成品移出進行中的功能目錄。
   受追蹤的檔案不得連結到 `.scratch/`；支持發行聲明的結果，請複製到 `docs/` 或 ADR。
4. `docs/project/project-status.md` 只記錄已完成且可重現驗證的能力。不要把本機原型或沒有重跑的基準升格為目前基線。
5. 工作項目被取代時，加上指向替代者的簡短說明；不要抹除它的授權、基準或決策歷史。
6. `docs/` 只放持續維護的參考文件：`project/`（專案狀態、本流程、軟體組合、來源歸屬稽核、測試基準）、
   `guides/`（安裝與元件指南，如 `ragflow.md`）與 `adr/`。一次性的實作提示與任務規格放在 `.scratch/`；
   交付後，把長久的決定記成 ADR，並移除提示，不要在 `docs/` 留下過時的副本。

## 發行交接

1. 執行品牌與第三方稽核；保留的上游名稱必須有出處，不能成為使用者可見的產品品牌。
2. 對照 `THIRD_PARTY_NOTICES.md` 與 `docs/project/software-stack.md`，確認散布版本所選的設定與外部成品。
3. 不得更動根目錄的 `LICENSE`，保留適用的聲明，並在修改歸屬檔頭前，先為每個變更的原始檔分類。
4. 把最終的驗證結果記在 `docs/project/project-status.md` 或相關 ADR，並在各項門檻通過後才更新專案狀態。

### 品牌與第三方稽核

```bash
git grep -n -I -E 'Linly-Talker-Stream|Linly_Talker_Stream|linly-talker|Kedreamix|kedreamix'
git grep -n -I -E 'Wav2Lip|MuseTalk|LiveTalking|Whisper|FunASR|TalkingGaussian|ER-NeRF'
```

上游名稱預期出現在 `NOTICE`、`THIRD_PARTY_NOTICES.md`、README 的引用，以及繼承原始碼的歸屬中。
只有目前的介面標題、套件中繼資料、產品描述與使用者可見的提示詞必須使用 Nova Avatar。
第三方引擎名稱不要求比對結果為零。

### 發行檢查清單

- 法務：`LICENSE` 與 `NOTICE` 存在；保留 Kedreamix、LiveTalking（適用時）與 MuseTalk MIT 的歸屬；
  修改過的繼承原始碼帶有變更聲明；沒有隨附 Wav2Lip 整合，且它的 **Research / Non-commercial**
  限制紀錄仍留在 `THIRD_PARTY_NOTICES.md`；沒有任何第三方模型被描述為 Apache-2.0。
- 品牌：使用者可見的產品名稱是 Nova Avatar；套件 slug 是 `nova-avatar` 與 `nova-avatar-web`；
  儲存庫網址正確；舊品牌不出現在目前的介面。
- 執行：在所選的散布設定上，實際驗證後端啟動、前端建置、WebRTC 連線、麥克風、VAD、STT、LLM、TTS、
  MuseTalk、插話、播放提交、字幕生命週期與執行期設定。
