<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# 處理層拆分

Status: 已確認（2026-11-26），待執行階段 0

目的是讓程式碼日後容易維護，也容易拆分：每個處理層都有清楚的邊界與契約，以後可以交給不同的人負責，也可以單獨拆成行程。目前只有一位主要維護者，所以**這次只做階段 0 和階段 1，不拆行程**。

- 架構決定見 [ADR 0027](../../docs/adr/0027-split-code-by-processing-layer.md)，repo 與依賴的決定見 [ADR 0028](../../docs/adr/0028-monorepo-with-contracts-package.md)。
- 用語見 `CONTEXT.md`（核心、處理層、引擎）。

## 已定案的決定

1. **混合式邊界**：STT、LLM、TTS 的目標是 loopback 服務；數位人渲染留在核心行程內，只用程式介面隔開。（Q1）
2. **單一 repo**：程式留在一個 repo，以資料夾劃分處理層。repo 留在個人帳號下，不移到 Organization。（Q2、Q16）
3. **以處理層為單位劃分**，各層內容如下表。（Q3）

   | 模組 | 涵蓋的現有程式 |
   |---|---|
   | 核心 | `src/server`（routes、reply_streaming、conversations、state）、`src/vad`、`src/profiles`（交接判斷、天氣以外的部分）、`src/config`、`src/greetings`（排程與預寫文案）、`src/utils` |
   | STT | `src/asr`（只剩 faster-whisper；Fun-ASR 已於 2026-11-26 移除） |
   | LLM | `src/llm`、`src/ragflow`、`src/web_search`、`src/profiles/routing.py`、`src/profiles/weather*.py`、AI 招呼生成 |
   | TTS | `src/tts`（引擎、音訊庫、聲線模型、聲線訓練） |
   | 數位人渲染 | `src/avatars`（MuseTalk）、`src/scene` |
   | Web 前端 | `web/` |

4. **部署**：只有一個場域、一台主機、一張 GPU。服務只走 `127.0.0.1`，拆分不是為了水平擴展。（Q4）
5. **資料夾結構**：`contracts/`、`core/`、`avatar/`、`services/{stt,llm,tts}/`、`web/`。每個資料夾有自己的 `tests/` 和 `README.md`。（Q5）
6. **狀態歸屬**：輪次狀態全部由核心持有，處理層只持有自己的資產，服務不記住任何一場對話。（Q6）
7. **傳輸方式**（拆成行程時採用）：
   - STT：`POST` 音訊，回傳 JSON。
   - LLM：SSE 串流回覆事件。
   - TTS：每個片段一個請求，以 chunked 回傳 PCM。
   - 取消的方式是由核心斷開連線。（Q7）
8. **行程監督**：由核心監督服務；設定中可以填 `url`，改連開發者自行啟動的服務。切換引擎時呼叫服務的 `PUT /engine`。（Q8）
9. **契約**：`contracts/` 的 Pydantic 模型是唯一來源。OpenAPI 由模型產生並提交，CI 檢查兩者一致。（Q9）
10. **前端**：只和核心溝通。服務沒有自己的驗證，路由分類仍依 ADR 0021。（Q10）
11. **拆解順序**：階段 0 清除反向依賴，階段 1 建立契約並搬移資料夾，階段 2 拆成行程。（Q11）
12. **片段切分**：可播回覆片段由核心切分；LLM 只送出口語文字增量與結構化事件。（Q12）
13. **渲染與 TTS 脫鉤**：數位人渲染不再持有 TTS，由核心把 TTS 的 PCM 交給渲染。Edge 的重試與熔斷移進 TTS 層。（Q13）
14. **聲線訓練能否開始**：舞台連線由核心檢查，顯存由 TTS 自己檢查。訓練進行中，核心拒絕新的舞台連線。程式原本沒有這條規則，只在開始訓練前檢查舞台；2026-11-26 工單 04 發現後，維護者決定新增，由工單 11 實作。（Q14）
15. **不需要 GPU 也能測試**：每一層都要有 fake 引擎與契約測試，核心的測試使用假服務。GitHub CI 全部跑在 CPU 上，需要 GPU 的測試加上 marker，只在場域主機上手動執行。（Q15）
16. **CODEOWNERS 與分支保護**：`CODEOWNERS` 依資料夾分段，目前全部填 `@s0966066980`，作為「哪段程式歸哪一層」的地圖。不開啟 `main` 的 branch protection，維護者照舊直接 push。（Q18、Q24）
17. **設定檔**：仍然只有一份 `config/config.yaml`，由核心把各段設定傳給各層。各層的 setup 與權重腳本搬到 `services/<層>/scripts/`。（Q17）
18. **契約版本**：契約不編版號；拆成行程後，服務在 `/health` 回報 `contract_version`，版本不符時核心拒絕使用。（Q19）
19. **交接判斷、天氣工具、AI 招呼生成**歸 LLM 層，相關資料仍由核心持有。（Q20）
20. **延遲驗收**：拆出一層時，首音延遲 P50 的增加不得超過 50 ms，P95 不得超過 100 ms。（Q21）
21. **階段 2 暫不執行**：出現具體需求時才拆行程，順序為 STT → LLM → TTS。（Q23）

## 依賴管理的補充

決定 5 原本寫的是「各服務是獨立的 uv 專案，有自己的 lock」。不過決定 21 讓所有處理層暫時都在同一個行程內，而一個行程只能有一個 Python 環境。因此：

- **階段 1**：各層有自己的 `pyproject.toml` 宣告依賴，由根專案以 path 依賴引用，共用根目錄的 `uv.lock`。
- **拆成行程時**：該層才改成獨立的 lock 與 venv（ADR 0028）。

Fun-ASR 移除之後，目前沒有互相衝突的依賴，所以這個做法沒有障礙。

## 現況（2026-11-26 盤點）

跨層 import（不含 `utils`）：

- **server 是匯集點**：它 import tts 51 處、llm 23 處、avatars 15 處、config 10 處、profiles 9 處，另外還有 web_search、ragflow、asr、vad、scene、greetings。
- **渲染持有 TTS**：`src/avatars/base.py:162` 由 `BaseAvatar` 建立 TTS，TTS 再透過 `parent` 每 20 ms 推音框回來。
- **處理層反向依賴核心的 `server.reply_streaming`**：
  - `src/llm/base.py` 使用 `SemanticFragmenter` 和 `SemanticWaitTimer`；
  - `src/tts/engines/edge.py` 使用 `PlayableFragment` 和 `RetryBudget`；
  - `src/llm/engines/openai.py` 使用 `timed_stage`。
- **處理層讀取核心的全域 `server.state`**：`src/llm/service.py`、`src/tts/training/gpu_guard.py`、`src/avatars/builder.py`。
- **處理層之間的越界 import**：
  - `src/llm/base.py` 和 `src/llm/service.py` import `BaseAvatar`；
  - `src/tts/base.py` import `BaseAvatar`；
  - `src/ragflow/settings.py` import `avatars.catalog`；
  - `src/asr/prewarm.py` import `vad.factory`。
- **核心直接依賴 llama.cpp 協定**：`src/profiles/routing.py` 使用 `llm.llamacpp_protocol`。
- **核心的 config 驗證伸進處理層內部**：`src/config/loader.py` 和 `src/config/overrides.py` import 了 tts、llm、greetings、avatars 的內部函式。

## 工單

工單都在 [issues/](issues/)。每張工單建議開一條短命分支、發一個 PR，由維護者自行合併，讓 CI 在合併前先跑過。這只是建議，不強制。

**階段 0：清除反向依賴（仍維持現有的 `src/` 結構）**

- 01：用 import-linter 守住處理層邊界
- 02：可播回覆片段改由核心切分
- 03：數位人渲染不再持有 TTS
- 04：`server.state` 改為注入，並拆分訓練開始條件的檢查
- 05：交接判斷、天氣工具、AI 招呼生成歸 LLM 層
- 06：清除其餘越界 import

**階段 1：建立契約並搬移資料夾**

- 07：建立 `contracts/` 與各層介面（已完成 2026-11-27）
- 08：各層的 fake 引擎與契約測試
- 09：搬到新的資料夾結構
- 10：`CODEOWNERS` 與 CI

**追加（2026-11-26）**

- 11：聲線訓練進行中拒絕新的舞台連線

**階段 2（暫不執行）**：拆成行程時，依決定 7、8、18、20 進行，並另開工單。

## 驗收（整體）

- `.github/workflows/ci.yml` 的每一步都通過，包括 `scripts/check-integration.py`。
- import-linter 的處理層規則全部啟用，沒有任何例外清單。
- 動到即時路徑的工單（02、03），首音延遲與修改前相比，P50 增加不超過 50 ms、P95 增加不超過 100 ms（用 `scripts/measure_first_audio.py` 量測）。
- 舞台與控制台的實機行為不變：免按對話、插話、角色交接、閒置招呼、聲線訓練都照常運作。
