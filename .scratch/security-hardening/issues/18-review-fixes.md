<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 整合分支審查修正
Status: ready-for-agent
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17

依[規格](../spec.md)。`git diff main...security-hardening` 的程式碼審查結果（未驗證）。每項先以測試重現；重現不了的在 Comments 記為「不成立」並說明，不要修改。

1. `web/src/composables/useRuntimeSettings.js:1099`：套用模型永遠送出目前的 `runtime.llm.endpoint`，忽略控制台選的 provider；沒有 `llm.endpoints` 的預設 config 只產生一個端點 → Ollama／llama.cpp 互換失效。預設設定須能同時提供兩者，且套用時送出所選端點。
2. `src/server/access.py:250`：`same_origin` 拿 `Origin` 比對請求自己的 `Host`；舞台類又信任 loopback → DNS rebinding（場域主機瀏覽器開 evil.com 重綁到 127.0.0.1）可通過。`Host` 須在允許清單內（localhost、127.0.0.1、::1、設定的主機名與本機 IP）。
3. `src/server/runtime_settings.py:868`：切到 `openai` 端點時沿用 `extra_body`（Ollama 專用 `options`/`keep_alive`、`reasoning_effort`）→ 嚴格的 OpenAI 相容 API 回 400。依 provider 過濾。
4. `src/tts/engines/sovits.py:27`（及 xtts、indextts2）：`ref_file` 為空時仍呼叫 `voice_path()` 拋錯，而 `check_reference` 允許空值、遷移也會清成空 → TTS 全斷。空值須維持原行為（交給伺服器預設）。
5. `src/server/voice_session.py:517`：`_consume_track` 對任何例外都呼叫 `on_lost()`，處理錯誤被當成麥克風遺失而關閉整條 peer。只有 track 結束／讀取錯誤才算遺失；處理錯誤記錄後繼續。
6. `src/server/access.py:282`：admin.env 被移除時 `_cached` 重設為 None，之後設定新密碼不會清除既有 session。密碼 hash 變動（含從無到有）一律清 session。
7. `src/profiles/store.py:302`：每次 `load()` 都重跑 `_migrate_voice_settings`（解碼音訊並 hash）且不寫回。遷移只在 `initialize` 做一次並寫回。
8. `src/server/runtime_settings.py:1390`：`speech_snapshot` 在 event loop 上同步做 `list_voices()`、`local_models()` 檔案掃描。移到 `to_thread` 或快取。
9. `src/server/routes/audio.py:61`：`/asr` 解碼兩次，且 `av.open` 未指定格式（音訊庫有限定 demuxer 防 playlist/concat 讀主機檔）；`/humanaudio` 同。共用音訊庫的安全開檔方式並只解碼一次。
10. `src/server/routes/settings.py:624`：`_avatar_replace_conflict` 呼叫 `roles.store.load()` 未處理 ProfileError（`_voice_in_use` 有處理），在建置執行緒內會於長時間建置後才失敗。改為 fail closed 回清楚的 409，並在建置前就檢查。
11. 測試衛生：完整 pytest 在 worktree 留下 `data/imports/`、`data/tts/`；找出寫入 repo `data/` 的測試，改用 tmp 目錄。

完成：每項有回歸測試或「不成立」說明；完整 CI 通過。

## Comments
