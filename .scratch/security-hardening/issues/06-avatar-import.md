<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 角色匯入覆寫與上傳上限
Status: resolved
Blocked by: 03

依[規格](../spec.md)。

- `src/avatars/builder.py:118-119,148-150`：`overwrite` 直接 `rmtree` 現有角色，不檢查使用中、不進回收桶，失敗再刪一次。改為在 `data/avatars/.building-<uuid>` 建置；成功後把舊角色移入回收桶（重用刪除端點的封存邏輯）再換上；使用中或被數位人設定檔引用者拒絕覆寫；失敗只刪暫存目錄。建置期間的 `/offer` 不得載入半成品。
- `src/server/routes/settings.py:568-581`：影片以 `read_chunk()` 串流且無上限（`client_max_size` 不管 `read_chunk`），並在驗證前落地；提前 return 留下 `data/imports/<uuid>/source.*`。改為先驗證引擎／ID／session／鎖，再寫檔並累計位元組，超限 413；`try/finally` 清除；多個 `video` part 拒絕。
- `routes/settings.py:587`：`quality` 在驗證前即全域儲存，繞過角色守門；改為驗證通過後才存。
- `src/server/import_jobs.py`：`_JOBS` 修剪已完成的舊工作；`job.error` 不回傳絕對路徑。

完成：覆寫使用中角色被拒、建置失敗保留舊角色、超限 413 且無殘留檔的回歸測試；完整 CI 通過。

## Comments

### 2026-10-29 實作結果（分支 `sh/06-avatar-import`）

- `builder.build_character` 改在 `data/avatars/.building-<uuid>` 建置（目錄以點開頭，目錄掃描與 `/offer` 看不到）；成功後以 `archive_avatar` 把舊角色移入 `.deleted` 再 rename 換上，rename 失敗則把舊角色搬回。失敗只刪暫存目錄。新增 `replace_guard`，建置前與換上前各檢查一次。
- 匯入端點：`video` 必須是表單最後一個欄位；寫檔前先驗證引擎、ID、session、鎖、同名未覆寫（409），覆寫時拒絕使用中或被設定檔引用的角色（409）。串流累計位元組，超過 `MAX_IMPORT_VIDEO_BYTES`（500 MB）回 413；第二個 `video` 或影片後的欄位回 400；`try/finally` 清除 `data/imports/<id>`。檔案寫入與清除走 `asyncio.to_thread`。
- `quality` 收到時只驗證，工作啟動後才 `apply_mouth_quality` 全域儲存。
- `import_jobs`：worker 鎖改在 `start_import_job` 取得、由工作執行緒在清除上傳檔後釋放；完成的工作最多保留 20 筆；非預期例外只回固定訊息，細節留伺服器日誌。500 回應同樣不再回傳例外字串。
- 前端 `importCharacter` 改為最後才 append `video`。
- 測試：新增 `tests/test_avatar_import.py`（14 項）；`test_mouth_quality.py` 的假 builder 接受 `replace_guard`，並等鎖釋放後才結束。
- 驗證：ruff、check-integration、pytest（842 通過，僅既知的 2 項 worktree 基準失敗）、web lint／test／build 全過。
