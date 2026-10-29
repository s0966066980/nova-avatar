<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 整合分支審查修正
Status: resolved
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

### 2026-10-29 實作結果

每項先寫回歸測試確認失敗，再修正。

1. 成立。前端 `applyLlmModel` 改送所選 provider 的端點名稱（同 provider 沿用目前端點；該 provider 無端點時拒絕，不再偷送目前端點）；`config/config.yaml` 預設列出 `llamacpp`、`ollama` 兩個端點（名稱同舊單一端點，既有設定檔與覆寫相容）。測試：`web/tests/llm-endpoint-selection.test.js`、`test_default_config_offers_both_local_servers`。
2. 成立（`evil.example` 重綁後 GET `/api/stage` 回 200）。存取守衛對每個請求先驗 `Host`：`localhost`、IP 字面值、設定檔新增的 `app.allowed_hosts`；其他回 403 `host_not_allowed`。IP 字面值一律接受：瀏覽器以 IP 連線時來源就是該 IP，無法被重綁，且免列舉網卡（VPN／DHCP 變動）。README 已說明以主機名稱連入需加入清單。測試：`test_stage_routes_reject_dns_rebinding_hosts`。
3. 成立。切到 `openai` 端點時移除 `options`／`keep_alive`／`think`／`reasoning_effort`。測試：`test_switching_away_from_ollama_drops_ollama_only_request_fields`。
4. 部分成立。新增 `voice_library.reference_path()`（空值回 ""）。GPT-SoVITS 空值照舊送空字串交給伺服器；XTTS 在 main 上空值本來就於建構時失敗（`open("")`），伺服器也無預設聲音，「維持原行為」不成立，改為建構成功、每句回報未選參考音訊，避免整個數字人連線建立失敗；IndexTTS2 建構成功、生成時記錄錯誤且不再把 `""` 交給 `handle_file`。測試：`tests/test_tts_empty_reference.py`。
5. 成立。只有 `track.recv()` 失敗算麥克風遺失；重取樣／VAD／開始回合的錯誤記錄後繼續收音。測試：`test_frame_processing_error_keeps_the_microphone_connected`。
6. 成立。admin.env 被移除時記住「無密碼」，之後任何 hash 變動（含從無到有）都清除 session。測試：`test_new_password_after_admin_env_removal_signs_everyone_out`。
7. 成立。`load()` 不再遷移；`initialize` 對原始 YAML 遷移一次並立即寫回（即使有未解決的舊端點而其餘內容暫不寫回）。測試：`test_profile_voice_migration_runs_once_at_startup_and_is_saved`。
8. 成立。`GET /api/speech`、`GET /api/settings` 與待套用設定回應的快照改在 `asyncio.to_thread` 產生。測試：`test_speech_snapshot_scans_files_off_the_loop`、`test_deferred_speech_settings_snapshot_scans_files_off_the_loop`。
9. `/asr` 成立：上傳的 ffconcat 清單可讓 PyAV 讀到工作目錄下的 WAV 並送進 ASR。抽出 `src/utils/audio_container.py`（音訊庫與 VAD 共用，依 magic bytes 指定 demuxer，其餘拒絕）；`/asr` 只解碼一次（`decode_audio` 有長度上限），VAD 對 PCM 執行（`preprocess_pcm`），ASR 只收到解碼後的 WAV；移除不再使用的 `ensure_audio_within`。`/humanaudio` 不成立：它只用 libsndfile 解碼一次、不經 PyAV，無法跟隨播放清單；仍補測試鎖定。測試：`test_asr_rejects_playlists_that_read_files_on_the_host`、`test_asr_decodes_the_upload_once_and_hands_asr_only_decoded_audio`、`test_asr_without_vad_hands_asr_only_decoded_audio`、`test_humanaudio_decodes_once_with_libsndfile_and_never_follows_playlists`。
10. 成立（ProfileError 讓匯入回 500）。`_avatar_replace_conflict` 讀不到角色設定時回覆清楚原因（fail closed），上傳前回 409、建置執行緒內也同樣拒絕；上傳前的檢查本來就有，改在 worker 執行緒讀檔。「建置前才檢查」的部分不成立。測試：`test_unreadable_profiles_refuse_overwrite_before_the_build`。
11. 成立（`data/imports/`）：`test_avatar_import.py` 兩項 import job 測試與 `test_mouth_quality.py::test_import_job_forwards_quality_into_builder` 經 `uploads_dir()` 建立目錄，改用 tmp 目錄。`data/tts/` 在目前分支完整 pytest 中未重現。`tests/conftest.py` 新增守衛：測試期間 repo `data/` 兩層內新增任何項目即令整個 pytest 失敗。

驗證：ruff、pyright（0 errors）、check-integration、npm lint／test（206）／build 通過；pytest 1083 passed、3 skipped、2 failed（`test_real_pdf_pages_are_validated_rendered_and_released`、`test_greeting_only_profile_apply_keeps_playing_media_and_avoids_rebinding`，worktree 缺本機資產的已知基準失敗），完整執行後 repo 無 `data/`。合併 security-hardening 無新提交（已是最新）。

