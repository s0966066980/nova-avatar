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

- 2026-11-27：fake 引擎與契約測試已完成；「核心的測試改用 fake」尚未做，狀態維持 `ready-for-agent`。
- 已完成：
  - fake 引擎：`src/asr/engines/fake.py`（固定逐字稿，`asr.type: fake`）、`src/tts/engines/fake.py`（0.5 秒靜音 PCM，`tts.type: fake`）、`src/llm/engines/fake.py`（固定回覆，簡答模式，`llm.provider: fake`，由 `llm/service.py` 的 `_new_llm` 選用）、`src/avatars/fake.py`（`FakeAvatar`：固定畫面，實作 `AvatarRenderer` 契約）。三個引擎都只在工廠裡登記，不在 `STT_ENGINE_META`、`TTS_ENGINES` 等控制台清單中，`tests/test_layer_contracts.py` 有測試鎖住這點。
  - 契約測試 `tests/test_layer_contracts.py`（9 個）：STT 回傳 `TranscribeResult`；TTS 以 20 ms 幀串流指定長度的 PCM、連續服務多個片段、提早關閉會取消引擎；LLM 事件順序為模式、口語增量、完成，關閉迭代器會停止生成，交接判斷回傳 `HandoffDecision`；渲染層轉送文字、回報說話狀態、清空佇列。全部在沒有 GPU、沒有權重的機器上執行。
  - pytest marker `gpu` 已加入，`addopts = -m "not gpu"` 讓 GitHub CI 預設排除；在場域主機用 `-m gpu` 執行。目前沒有需要 GPU 的測試，所以還沒有測試帶這個標記。
  - 測試總數從 2188 增加到 2216，沒有刪除任何測試；覆蓋率沒有重新量測。
- 未完成：「核心的輪次、插話、交接測試改用 fake 引擎，不再各自手寫假物件」。現有核心測試（`test_voice_session.py`、`test_reply_streaming.py` 等）有大量針對特定時序與失敗情境的手寫替身，改成 fake 引擎會失去這些精準控制；且 `FakeAvatar` 沒有接上 WebRTC 與 `VoiceTurnSession` 用到的媒體柵欄、播放確認等介面，所以也不能直接拿來當核心測試的渲染替身。建議另開工單，先替 `VoiceTurnSession` 設計一個可注入的渲染介面，再逐批替換測試。
