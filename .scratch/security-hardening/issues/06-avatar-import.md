<!-- Copyright (c) 2026 HongXian0903. SPDX-License-Identifier: Apache-2.0. -->
# 角色匯入覆寫與上傳上限
Status: ready-for-agent
Blocked by: 03

依[規格](../spec.md)。

- `src/avatars/builder.py:118-119,148-150`：`overwrite` 直接 `rmtree` 現有角色，不檢查使用中、不進回收桶，失敗再刪一次。改為在 `data/avatars/.building-<uuid>` 建置；成功後把舊角色移入回收桶（重用刪除端點的封存邏輯）再換上；使用中或被數位人設定檔引用者拒絕覆寫；失敗只刪暫存目錄。建置期間的 `/offer` 不得載入半成品。
- `src/server/routes/settings.py:568-581`：影片以 `read_chunk()` 串流且無上限（`client_max_size` 不管 `read_chunk`），並在驗證前落地；提前 return 留下 `data/imports/<uuid>/source.*`。改為先驗證引擎／ID／session／鎖，再寫檔並累計位元組，超限 413；`try/finally` 清除；多個 `video` part 拒絕。
- `routes/settings.py:587`：`quality` 在驗證前即全域儲存，繞過角色守門；改為驗證通過後才存。
- `src/server/import_jobs.py`：`_JOBS` 修剪已完成的舊工作；`job.error` 不回傳絕對路徑。

完成：覆寫使用中角色被拒、建置失敗保留舊角色、超限 413 且無殘留檔的回歸測試；完整 CI 通過。

## Comments
