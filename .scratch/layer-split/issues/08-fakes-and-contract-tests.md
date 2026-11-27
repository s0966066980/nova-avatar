<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 各層的 fake 引擎與契約測試
Status: resolved
Blocked by: 07

依規格決定 15。

- 每一層都提供一個 `fake` 引擎：
  - STT 回傳固定文字；
  - LLM 回傳固定的口語文字增量與看板事件；
  - TTS 回傳指定長度的靜音 PCM；
  - 數位人渲染輸出固定畫面。
  - 透過設定即可選用，但不出現在控制台的引擎清單中。
- 每一層各有一組契約測試，驗證 adapter 的輸入輸出符合 `contracts/` 的模型與事件順序，包括取消時的行為。
- 核心的輪次、插話、交接測試改用 fake 引擎，不再各自手寫假物件。
- 需要 GPU 或真實模型的測試，統一用 pytest marker（例如 `gpu`）標記；GitHub CI 預設排除它們。
- 驗收：
  - 在沒有 GPU、沒有模型權重的機器上，`uv run --no-sync pytest` 全部通過；
  - 測試數量與覆蓋率不低於修改前，若有減少要說明原因。

## Comments

### 2026-11-27 STT 層

分支 `ls/08-stt`，只涵蓋 STT 層；LLM、TTS、數位人渲染由各自分支處理，工單仍維持開啟。

- `fake` 引擎：`src/asr/engines/fake.py` 的 `FakeASR`，註冊在 `src/asr/factory.py`。不需要 GPU 或權重，也不解碼音訊，對每段語音回傳固定文字。
- 選用方式：設定檔 `asr.type: fake`，並以 `asr.model_size` 當作要回傳的文字（例如 `model_size: 歡迎光臨`；空字串代表無聲）。為了不改契約，沒有新增欄位。語言依請求回報，`auto` 一律回 `zh`；信心分數為 1.0。
- 不出現在控制台：`STT_ENGINE_META` 沒有它，所以引擎清單看不到，也無法從控制台套用（會回「不支援的 STT 引擎」）。
- 契約測試（`tests/test_stt_contract.py`）新增：以真正的 adapter 與 factory 搭配 fake 引擎，檢查輸出符合 `nova_contracts.stt` 的模型，涵蓋語言、`prepare`／`health`、切換引擎、切換失敗（載入失敗與未知引擎）保留目前引擎，以及切換載入期間的請求仍由目前的辨識器回答；另有設定檔選用與控制台不列出的測試。STT 契約測試由 12 增為 22；全部測試 2342 passed、2 skipped。
- 順手修正：`InProcessSttService.apply_engine` 對未知引擎原本丟出 `ValueError`，現在與載入失敗一致，轉成 `ServiceError` 並保留目前的辨識器（契約規定的行為）。
- 取消：STT 在同一行程內沒有可取消的長時間呼叫（loopback 時由核心關閉連線取消），所以以「切換中放棄／失敗不影響目前辨識器」驗證；沒有為 fake 加入假的取消行為。
- 核心的輪次、插話、交接測試改用 fake 引擎，屬後續整合工作，本次未動。

### 2026-11-27 TTS 層

分支 `ls/08-tts`。只做 TTS 層的 fake 引擎與契約測試；核心測試改用 fake 引擎留給後續步驟。

- `fake` 引擎（`src/tts/engines/fake.py`）回傳靜音 PCM，長度由片段的 `estimated_seconds` 決定（`synthesize` 會帶入；沒有或為 0 時，每個字 `SECONDS_PER_CHARACTER` = 0.1 秒）。
  - 即時路徑與真引擎相同：從 Matcha 抽出預取機制到 `src/tts/engines/prefetching.py` 的 `PrefetchingTTS`（佇列、epoch 丟棄、預取一段、播放柵欄、`TurnPCMEmitter` 事件），`MatchaTTS` 與 `FakeTTS` 都繼承它。Matcha 行為不變，既有 Matcha 測試未改。
  - 靜音會被 `StreamingSilenceTrimmer` 全部裁掉，所以 `TurnPCMEmitter` 新增選用參數 `trimmer`，fake 傳入不裁剪的版本，音框與片段事件才完整。
- 選用方式：設定檔或角色設定檔的 `tts.type: fake`。契約的 `TtsEngine` 加入 `"fake"`（`contracts/openapi/tts.json` 已重新產生）；`voice_library.CONFIGURABLE_TTS_ENGINES` 才包含 fake，控制台用的 `TTS_ENGINES`、引擎清單 `speech_snapshot`、音訊庫與目錄都不列出，也不能從控制台套用（`apply_tts_settings` 回「不支援」）。
- 契約測試 `tests/test_tts_fake_engine.py`（18 個）透過 `InProcessTtsService` 驗證：
  - 輸入輸出：`synthesize` 的 PCM 型式、長度、`max_seconds`、分塊；頻道每個音框為 320 樣本靜音，事件順序（`media_sequence`、`fragment_start`／`fragment_end`、`status`）與 `FragmentEnvelope` 一致。
  - 播放柵欄：片段播完前 `has_pending_work` 為真；沒有 turn 的片段不等柵欄。
  - 取消：`flush` 丟棄佇列與已預取的片段、停止正在送出的片段、新一輪照常播放；`accepts_media` 拒絕的舊輪次不播；worker 結束後不再開始新片段；預取只領先一段。
- 全部 CI 步驟通過：ruff、pyright、`lint-imports --no-cache`、`generate_openapi.py --check`、`check-integration.py`、pytest（2350 passed、2 skipped；本步新增 18 個測試）。沒有新增 `ignore_imports`。
- 尚未驗證：Matcha 預取的抽出沒有在實機（Edge／Matcha 對話、插話）驗證，只靠既有 Matcha 測試；首音延遲未量測。

### 2026-11-27 數位人渲染層

分支 `ls/08-avatar`，只動數位人渲染（`src/avatars`、契約測試），核心測試尚未改用 fake。

- fake 引擎 `src/avatars/fake.py`：以設定 `model.type: fake` 選用，沒有權重、GPU 或角色素材檔。`catalog.avatar_bootable("fake", …)` 一律可啟動，`factory` 的建立、載入、換素材都接到 `FakeAvatarRenderer`；它不在 `ENGINE_META`，所以控制台的引擎清單看不到，`knows_engine("fake")` 為 `False`，也不能匯入、不能從設定頁切換。
- 渲染語意與真引擎一致：繼承 `BaseAvatar`，重用它的媒體柵欄、`media_sequence` 重編、`flush_talk`、`is_speaking`、錄影與角色轉場，只換掉推理。TTS PCM 是主時鐘，每個 20 ms 音框原樣送出並帶著 eventpoint（`status`、`fragment_start`、`fragment_end`），每兩個音框出一張 25 fps 畫面並標上該輪的 eventpoint，沒有語音時送靜音與固定畫面（720×1280、單一顏色，嘴型不動）。核心回報還有 PCM 要來時會短暫等待（上限 0.2 秒），插話時 `flush_talk` 丟掉佇列中的舊音訊與已算好的畫面，`bind_profile` 會遞增 `asset_epoch`，舊 epoch 的媒體被丟棄。
- `BaseAvatar.result_poll_seconds`（預設 1 秒，MuseTalk 行為不變）：fake 縮短為 0.05 秒，否則每次停止渲染要多等 1 秒。
- `pyproject.toml`：`avatar-internals-private` 的 `protected_modules` 加入 `src.avatars.fake`，沒有新增任何 `ignore_imports`。
- 契約測試（`tests/test_avatar_contract.py`，新增 9 項，共 22 項）以行程內轉接器加 fake 引擎驅動，用會套用媒體柵欄的假軌道收集輸出：
  - 可由設定選用、不在控制台清單；
  - 載入的 handle 與 `AvatarRenderer` 協定；
  - 閒置時輸出固定畫面與靜音；
  - 回覆音訊的 PCM、`media_sequence`／`fragment_media_sequence`、片段起訖與 `status` 事件的順序，以及播放端回報的邊界；
  - 說話中與結束後的 `is_speaking`；
  - 音訊在佇列時 `flush_talk`；
  - 插話（舊世代被丟棄並記錄 stale drop，新一輪正常播放）；
  - 軌道卡死時 `quit_event` 仍能取消渲染；
  - `bind_profile` 的 epoch 與丟棄舊回覆。
- 未做：核心的輪次、插話、交接測試改用 fake（之後的 ticket 08 步驟）；`gpu` marker。


### 2026-11-27 LLM 層

分支 `ls/08-llm`，只做 LLM 層（`src/llm`、契約的 `llm` 模組、LLM 測試），STT、TTS、數位人渲染由其他步驟處理。

- **`fake` 引擎**：`src/llm/engines/fake.py` 的 `FakeLLM` 只取代模型，依回覆協定串流固定內容（兩個 chunk：一句口語文字加兩項看板），所以協定解析、片段審查、看板事件與對話記憶都照真實路徑執行；完全離線，不連任何模型伺服器。可用 `answer_chunks(text)` 或自訂 `chunks` 寫腳本。
- **選用方式**：設定檔 `llm.engine: fake`（空白或未設定＝`openai-compatible`，即原本的 OpenAI 相容客戶端）。契約的 `LlmSettings` 新增 `engine` 欄位（預設 `openai-compatible`，OpenAPI 已重新產生），adapter 依每個對話的設定從 `ENGINES` 選引擎；`engine: fake` 時不啟動自有 llama-server，`prewarm` 直接回報就緒。未知的引擎名稱在載入設定時以 `ValueError` 拒絕。`fake` 不是端點，不在 `PROVIDERS` 或 `llm.endpoints`，控制台的端點清單看不到它（有測試確認）。
- **契約測試**：新增 `tests/test_llm_fake_engine.py`（11 個測試），對行程內 adapter 搭配 fake 引擎驗證：每個事件都能通過 `nova_contracts.llm` 模型的 JSON 往返；事件順序（`ReplyStarted` 最先、`ReplyDone` 最後，看板開始、項目、整體依序）；取消時回覆停止、不再產生事件、模型串流被釋放且沒有多讀下一個 chunk；輪次提交只入歷史一次、提交後不能捨棄、捨棄後不能提交且下一輪乾淨；以及經設定選用與不列入控制台清單。
- **`tests/llm_fakes.py`**：`reply_events()` 原本手寫事件序列，改為由 fake 引擎產生；其餘（腳本化的 `FakeLlm`、`answering`、`ask`）維持不變，核心測試沒有遷移，留待工單 08 的後續步驟。移除了沒人用的 `board_events()` 與 `reply_events` 的 `mode` 參數。
- 驗證：ruff、pyright（0 errors）、`lint-imports --no-cache`（11 條契約全保持、沒有 `ignore_imports`）、`generate_openapi.py --check`、`check-integration.py` 通過；pytest 2344 passed、2 skipped、63 subtests passed（整合分支為 2332，多出的 12 個為本次新增）。`web/` 沒有變動，未跑前端步驟；`uv lock --check` 沒有相依變動，未重跑。
- 已知限制：fake 引擎只取代回覆的模型呼叫；交接判斷、AI 招呼生成與網頁搜尋規劃仍使用真實的 OpenAI 相容客戶端，離線測試這些路徑時，需在測試中注入假的用戶端工廠（交接的關鍵字預篩選本來就不呼叫模型）。

### 2026-11-27 核心測試與 gpu marker

分支 `ls/08-core`（接在整合分支 `layer-split` tip 414af4c 之上），完成工單剩下的兩項：核心測試改用共用的 fake／真 adapter，以及 `gpu` marker。

**基準（修改前，tip 414af4c，`pytest --cov=src`）**：2381 passed、2 skipped、63 subtests passed；總覆蓋率 76.93%（25467 行、未覆蓋 5875）。

| 套件 | 行數 | 未覆蓋 | 覆蓋率 |
| --- | --- | --- | --- |
| `src/asr` | 257 | 23 | 91.1% |
| `src/avatars` | 5673 | 2963 | 47.8% |
| `src/llm` | 3136 | 439 | 86.0% |
| `src/profiles` | 1409 | 181 | 87.2% |
| `src/server` | 6922 | 1425 | 79.4% |
| `src/tts` | 5391 | 444 | 91.8% |

**核心測試改用 fake／真 adapter**

- `tests/session_fakes.py`
  - `FakeStt` 手寫物件改為 `fake_stt(text)`：真正的 `InProcessSttService` 搭配 STT 層的 `fake` 引擎（`asr.type: fake`）。
  - `test_voice_session.py`、`test_stage_idle_reset.py`、`test_conversation_attachments.py` 使用它；原本以 `SimpleNamespace(transcribe=Mock())` 檢查「未呼叫」與「呼叫參數」的測試，改為 `Mock(wraps=fake_stt(...))`，斷言不變。
  - 需要特定信心分數（低信心轉錄不進 LLM）的測試仍手寫轉錄結果，因為 fake 引擎固定回報信心 1.0。
- `FakeAvatar` 合併成一份：session_fakes 的 `FakeAvatar` 成為唯一的工作階段數位人替身，行為與 `SpeakingAvatar.put_msg_txt` 一致（去除不可朗讀的標記、空字串不成為片段、只有帶 turn 的片段才登記 `on_fragment_queued`），並保留媒體柵欄回呼供測試扮演 TTS。刪除 6 份各自手寫的版本：`test_playback_commit.FakeAvatar`、`test_concurrent_routing._Avatar`、`test_turn_lifecycle.SanitizingAvatar`、`test_ragflow_integration._Avatar`、`test_first_audio_latency._Avatar`，以及 `role_fakes.Avatar`（改為繼承 `FakeAvatar`，只保留角色轉場的部分）；原本未使用的 `FakeRenderer` 一併移除。
- `tests/clock_fakes.py` 新增 `FakeClock`，取代 5 份各自手寫的時鐘（`test_turn_lifecycle`、`test_reply_streaming`、`test_first_audio_latency`、`test_concurrent_routing`、`test_voice_session` 內的巢狀類別）；起始值維持各測試原本的 0.0 或 100.0。
- 輪次、插話、交接測試的 LLM、TTS、數位人轉接器本來就已經走真 adapter（`FakeLlm`、`in_process_tts`、`create_avatar_service`），這次不需再動。
- 刻意沒有改的：
  - 以 `BaseLLM` 子類測試回覆串流與回覆片段切分（`test_reply_streaming`、`test_reply_speech_seam`、`test_first_fragment_exception`、`test_response_protocol` 等），它們測的是 LLM 層對原始串流的處理，不是核心。
  - `test_speaking_avatar.py` 的 `FakeRenderer`／`FakeTTS`，它們測 `SpeakingAvatar` 與渲染器、TTS 之間的接縫。
  - Edge 重試、Matcha 預取等針對真實引擎行為的測試。
  - 讓核心測試改接真正的 `fake` TTS 通道與 `fake` 渲染器，會讓回放事件變成非同步，破壞既有的確定性（例如播放提交測試靠手動呼叫回呼），所以核心的數位人替身仍是記錄用的同步物件，fake 引擎由各層契約測試驗證。

**`gpu` marker**

- `pyproject.toml` 註冊 `gpu` marker，並設 `addopts = '-m "not gpu"'`：本機 `uv run --no-sync pytest` 與 CI 的 pytest 步驟預設不跑它們，不需要改 `ci.yml`；命令列的 `-m` 會取代 `addopts`，維護者用 `-m gpu` 執行。
- 在 `tests/conftest.py` 的 `GPU_FILES`／`GPU_TESTS` 登記（沿用該檔集中標記 area、live、slow 的做法）：兩個已配置模型的看板契約（`test_live_llm_board_contract.py`）與真 `llama-server -h` 檢查（`test_llamacpp.py`）；它們原本就是 `live`，所以 `-m "not live"`（目前版本基準使用）行為不變。綠幕合成的 CPU 時間預算屬 `live`，但不需要 GPU，未標 `gpu`。
- 文件：`docs/current-version-testing.md` 新增「`gpu` 標記與各層的 fake 引擎」一節。

**在沒有 GPU、沒有權重的環境驗證**

- 以 `CUDA_VISIBLE_DEVICES=`、`HF_HOME`／`TORCH_HOME`／`XDG_CACHE_HOME` 指向空目錄、`HF_HUB_OFFLINE=1` 執行 `uv run --no-sync pytest`：全部通過。工作樹是乾淨的 checkout，沒有 `data/`、`models/` 權重。
- 順手修正一個與環境有關的測試：`test_unavailable_engines_keep_the_original_models` 原本在安裝了 TensorRT、但看不到 GPU 的機器上，會因為真的 TensorRT runtime 而造成整個 pytest 行程 segfault（`CUDA_VISIBLE_DEVICES=` 時可重現；CI 沒有安裝 TensorRT，所以不受影響）。改為注入假的 `tensorrt` 模組，走到與原本相同的程式行（讀不到引擎檔而退回原模型），斷言沒有改動，覆蓋的行數與基準相同。

**修改後（含 `--cov=src`，CUDA 隱藏）**：2380 passed、3 deselected（即 gpu 的 1 個通過加 2 個 skipped）、63 subtests passed；總覆蓋率 76.93%，與基準相同，逐檔未覆蓋行數也與基準完全相同。

| 套件 | 修改前 → 修改後（未覆蓋） | 覆蓋率 |
| --- | --- | --- |
| `src/asr` | 23 → 23 | 91.1% |
| `src/avatars` | 2963 → 2963 | 47.8% |
| `src/llm` | 439 → 439 | 86.0% |
| `src/profiles` | 181 → 181 | 87.2% |
| `src/server` | 1425 → 1425 | 79.4% |
| `src/tts` | 444 → 444 | 91.8% |

測試數量說明：收集到的測試仍是 2383 個，沒有刪除任何測試；「2381 passed、2 skipped」中的 3 個案例改為預設 deselect（gpu），所以預設的 passed 數是 2380，不是測試減少。合併重複的替身沒有減少案例數。

CI 步驟全部通過：`uv lock --check`、ruff、pyright（0 errors）、`lint-imports --no-cache`（11 條契約全保持，沒有新增 `ignore_imports`）、`generate_openapi.py --check`、`check-integration.py`、pytest；`web/` 沒有變動，未跑前端步驟。

尚未驗證：實際執行 `-m gpu`（需 `NOVA_AVATAR_LIVE_LLM_CONTRACT=1`，以及有 GPU 與模型伺服器的機器）；在 CI 平台上的實際執行（本機沒有推送）。
