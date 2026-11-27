<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 各層的 fake 引擎與契約測試
Status: ready-for-agent
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
